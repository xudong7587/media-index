import { escapeHtml as esc, runAction } from "../../components/native-ui.js";
import { workflowStepsView, fallbackJobWorkflow } from "../transfer/native-workflow.js";

export function jobStatus(status) {
  return ({ done: ["完成", "ok"], failed: ["异常", "err"], needs_review: ["待决定", "warn"], queued: ["排队", "info"], stopped: ["已停止", "muted"], running: ["进行中", "info"], ready: ["就绪", "info"], triggered: ["已提交", "info"], retry_wait: ["等待重试", "warn"] })[status] || [status || "未知", "muted"];
}
export async function openNativeJobDetail(api, id, onChanged = async () => {}) {
  const dialog = document.createElement("dialog");
  dialog.className = "task-dialog";
  dialog.innerHTML = `<div class="td-head"><div class="grow"><span>任务 #${esc(id)}</span><h2 data-job-title>正在读取…</h2><div data-job-badge></div></div><button class="icon-btn" data-job-close aria-label="关闭任务详情"><svg class="ic"><use href="#i-close"/></svg></button></div><div class="td-body"><p class="muted-note" data-job-summary></p><div class="steps"></div><p class="inline-result" role="status"></p><div data-job-log hidden></div></div><dl class="td-facts"></dl><div class="td-foot"></div>`;
  document.body.append(dialog);
  dialog.querySelector("[data-job-close]").onclick = () => dialog.close();
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.showModal();
  const output = dialog.querySelector('[role="status"]');
  let expanded = false;
  let refreshing = false;
  let timer;
  dialog.addEventListener("close", () => window.clearTimeout(timer));
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
    const job = await api(`/api/transfers/${encodeURIComponent(id)}`);
    if (!dialog.isConnected) return;
    dialog.querySelector("[data-job-title]").textContent = job.display_title || job.title || `任务 #${id}`;
    const [label, tone] = jobStatus(job.status);
    dialog.querySelector("[data-job-badge]").innerHTML = `<span class="pill ${tone}">${esc(label)}</span>`;
    dialog.querySelector("[data-job-summary]").textContent = job.message || "";
    let lane = fallbackJobWorkflow(job);
    let workflowError = "";
    try {
      const workflow = await api(`/api/transfers/${encodeURIComponent(id)}/workflow`);
      if (String(workflow.job_id) === String(id)) lane = workflow;
    } catch (error) { workflowError = `完整链路读取失败：${error.message}`; }
    if (!dialog.isConnected) return;
    dialog.querySelector(".steps").outerHTML = workflowStepsView(lane);
    if (workflowError) output.textContent = workflowError;
    const fields = [["来源目录", job.source_file || "未记录"], ["媒体分类", ({movie:"电影",tv:"剧集",variety:"综艺"})[job.media_type] || job.media_type || "未记录"], ["执行端", ({quark:"夸克",p115:"115"})[job.provider] || job.provider], ["目标", job.target === "cloud" ? "网盘" : job.target || "网盘"], ["保存路径", job.save_path || "未记录"], ["创建时间", job.created_at]];
    dialog.querySelector(".td-facts").innerHTML = fields.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd title="${esc(value)}">${esc(value)}</dd></div>`).join("");
    dialog.querySelector("[data-job-log]").innerHTML = `<div class="job-grid">${[["阶段",job.stage],["状态",job.status],["来源",job.request_source],["处理结果",job.message],["结束时间",job.finished_at]].map(([key,value])=>`<div class="job-row"><span>${esc(key)}</span><b>${esc(value || "未记录")}</b></div>`).join("")}</div><p class="muted-note">节点状态来自后端保存的入库链路；历史任务未记录的节点显示为未记录。</p>`;
    const canStop = ["queued", "running", "ready", "triggered", "retry_wait"].includes(job.status) && !["emby", "scheduler"].includes(job.provider);
    const canRetry = job.request_source === "cloud_download_organizer" && ["failed", "needs_review"].includes(job.status);
    dialog.querySelector(".td-foot").innerHTML = `${canStop ? '<button class="mini-btn danger" data-job-stop>终止任务</button>' : ""}<div class="row-actions"><button class="mini-btn" data-job-refresh>刷新状态</button><button class="mini-btn" data-job-show-log aria-expanded="${expanded}">${expanded ? "关闭完整记录" : "查看完整记录"}</button>${canRetry ? '<button class="mini-btn" data-job-retry>重新核对来源目录</button>' : ""}<button class="mini-btn primary" data-job-done>关闭</button></div>`;
    dialog.querySelector("[data-job-done]").onclick = () => dialog.close();
    dialog.querySelector("[data-job-log]").hidden = !expanded;
    dialog.querySelector("[data-job-show-log]").onclick = (event) => {
      expanded = !expanded;
      dialog.querySelector("[data-job-log]").hidden = !expanded;
      event.currentTarget.textContent = expanded ? "关闭完整记录" : "查看完整记录";
      event.currentTarget.setAttribute("aria-expanded", String(expanded));
    };
    const bind = (selector, action) => {
      const button = dialog.querySelector(selector);
      if (button) button.onclick = () => void runAction(button, output, action);
    };
    bind("[data-job-refresh]", async () => { await refresh(); return { message: "状态已更新" }; });
    bind("[data-job-stop]", async () => {
      const result = await api(`/api/transfers/${id}/stop`, { method: "POST" });
      await refresh(); await onChanged();
      return result;
    });
    bind("[data-job-retry]", async () => {
      const result = await api(`/api/transfers/cloud-download-organizer/jobs/${id}/retry`, { method: "POST" });
      await refresh(); await onChanged();
      return result;
    });
    } finally { refreshing = false; }
  }
  async function poll() {
    if (!dialog.isConnected) return;
    try { await refresh(); } catch (error) { output.textContent = error.message; }
    if (dialog.isConnected) timer = window.setTimeout(poll, 5000);
  }
  try { await refresh(); timer = window.setTimeout(poll, 5000); } catch (error) { output.textContent = error.message; }
}
