import { escapeHtml as esc, listen } from "../../components/native-ui.js";
import { openNativeJobDetail, jobStatus } from "./native-job-detail.js";

const running = (job) => ["queued", "running", "ready", "triggered", "retry_wait"].includes(job.status);
export function taskPopoverView() {
  return `<div class="pop-anchor"><button class="icon-btn" id="btnTasks" title="任务" aria-label="任务" aria-expanded="false" aria-controls="activityPop"><svg class="ic ic-sm"><use href="#i-activity"/></svg><b class="badge" id="taskBadge" hidden></b></button><div class="popover" id="activityPop"></div></div>`;
}

let dispose = () => {};
export function bindTaskPopover(api, openCenter) {
  dispose();
  const button = document.getElementById("btnTasks");
  const pop = document.getElementById("activityPop");
  if (!button || !pop) return;
  let jobs = [], filter = "all", timer, loading = false;
  function close() { pop.classList.remove("open"); button.setAttribute("aria-expanded", "false"); clearInterval(timer); }
  function render() {
    const active = jobs.filter(running);
    const review = jobs.filter((job) => job.status === "needs_review");
    const filtered = filter === "running" ? active : filter === "review" ? review : jobs;
    pop.innerHTML = `<div class="pop-top"><div><b>任务</b><small>进行中 ${active.length} · 待决定 ${review.length}</small></div><button class="link" data-task-center>任务中心 <svg class="ic"><use href="#i-arrow"/></svg></button></div>
      <div class="pop-tabs" role="tablist" aria-label="任务筛选">${[["all", "全部", jobs.length], ["running", "进行中", active.length], ["review", "待决定", review.length]].map(([key, label, count]) => `<button class="pop-tab ${filter === key ? "active" : ""}" role="tab" aria-selected="${filter === key}" data-task-filter="${key}">${label} ${count}</button>`).join("")}</div>
      <div class="pop-list">${filtered.slice(0, 5).map((job) => {
        const [label, tone] = jobStatus(job.status);
        const progress = typeof job.progress === "number" && Number.isFinite(job.progress) ? Math.max(0, Math.min(100, job.progress)) : job.status === "done" ? 100 : null;
        return `<button class="pop-task" data-task-detail="${job.id}"><div class="pop-task-copy"><b>${esc(job.display_title || job.title || `任务 #${job.id}`)}</b><small>${esc(job.message || job.stage || "等待执行")} · ${esc(job.provider || "")}</small>${progress !== null ? `<div class="progress ${tone === "err" ? "warn" : ""}" style="margin-top:6px"><i style="width:${progress}%"></i></div>` : ""}</div>${progress !== null && running(job) ? `<span class="pop-pct">${progress}%</span>` : `<span class="pill ${tone}"><i></i>${label}</span>`}<svg class="ic ic-sm pop-chev"><use href="#i-chev-r"/></svg></button>`;
      }).join("") || '<div class="empty-state">暂无此类任务</div>'}</div><div class="pop-foot"><span>5 秒自动刷新 · 仅显示最近 5 条</span><span>点击任务查看进度</span></div>`;
    pop.querySelector("[data-task-center]").onclick = () => { close(); openCenter(); };
    pop.querySelectorAll("[data-task-filter]").forEach((node) => { node.onclick = () => { filter = node.dataset.taskFilter; render(); }; });
    pop.querySelectorAll("[data-task-detail]").forEach((node) => { node.onclick = () => { close(); void openNativeJobDetail(api, node.dataset.taskDetail, refresh); }; });
  }
  async function refresh() {
    if (loading || !pop.isConnected) return;
    loading = true;
    try {
      const result = await api("/api/transfers");
      if (!pop.isConnected) return;
      jobs = Array.isArray(result) ? result : [];
      const count = jobs.filter((job) => running(job) || job.status === "needs_review").length;
      const badge = button.querySelector("#taskBadge");
      badge.hidden = count === 0; badge.textContent = String(count);
      if (pop.classList.contains("open")) render();
    } catch (error) {
      if (pop.classList.contains("open")) pop.innerHTML = `<div class="pop-top"><b>任务</b><button class="link" data-task-refresh>重试</button></div><div class="pop-list" role="alert">${esc(error.message)}</div>`;
      const retry = pop.querySelector("[data-task-refresh]");
      if (retry) retry.onclick = refresh;
    } finally { loading = false; }
  }
  listen(button, "click", () => {
    if (pop.classList.contains("open")) { close(); return; }
    document.querySelectorAll(".notice-pop.open,.appearance-pop.open").forEach((node) => node.classList.remove("open"));
    pop.classList.add("open"); button.setAttribute("aria-expanded", "true");
    render(); void refresh();
    timer = setInterval(() => { if (!pop.isConnected) { dispose(); return; } if (!document.hidden) void refresh(); }, 5000);
  });
  const outside = (event) => { if (!button.contains(event.target) && !pop.contains(event.target)) close(); };
  const escape = (event) => { if (event.key === "Escape") close(); };
  document.addEventListener("click", outside); document.addEventListener("keydown", escape);
  dispose = () => { close(); document.removeEventListener("click", outside); document.removeEventListener("keydown", escape); };
  void refresh();
}
