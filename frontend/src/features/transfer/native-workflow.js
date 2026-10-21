import { escapeHtml as esc } from "../../components/native-ui.js";

export const workflowNodes = [
  ["resource_search", "网盘资源查询"], ["tmdb_rename", "TMDB 核对和改名"],
  ["transfer", "提交网盘"], ["landing_confirm", "落盘确认"], ["openlist_sync", "115 补齐"],
  ["strm_generate", "STRM 生成"], ["emby_refresh", "通知 Emby 入库"], ["library_notification", "发送入库通知"],
];
export function workflowStepsView(lane = {}, horizontal = false) {
  const recorded = new Map((lane.steps || []).map((step) => [step.key, step]));
  const states = { running: "current", done: "done", failed: "failed", review: "review", skipped: "skipped", pending: "pending" };
  const labels = { running: "进行中", done: "完成", failed: "异常", review: "待确认", skipped: "跳过", pending: "等待", unknown: "未记录" };
  return `<div class="steps ${horizontal ? "workflow-horizontal" : ""}" aria-label="完整入库链路">${workflowNodes.map(([key, label], index) => {
    let step = recorded.get(key) || { status: "unknown", message: "此任务没有记录该节点结果" };
    if (lane.status === "done" && index < 4 && ["pending", "running"].includes(step.status)) {
      step = { ...step, status: "unknown", message: `转存已结束，此节点未记录最终结果；最后记录：${step.message || "等待开始"}` };
    }
    const icon = step.status === "done" ? '<svg class="ic"><use href="#i-check"/></svg>' : step.status === "failed" ? '<svg class="ic"><use href="#i-close"/></svg>' : step.status === "skipped" ? "—" : index + 1;
    const stamp = step.updated_at || "";
    if (horizontal) return `<button type="button" class="step ${states[step.status] || "pending"}" data-workflow-node="${key}" data-workflow-label="${esc(label)}" data-workflow-status="${esc(labels[step.status] || "未记录")}" data-workflow-message="${esc(step.message || "未记录")}" data-workflow-time="${esc(stamp)}" aria-expanded="false"><span class="dot">${icon}</span><b>${esc(label)}</b><span class="workflow-node-status">${esc(labels[step.status] || "未记录")}</span></button>`;
    return `<div class="step ${states[step.status] || "pending"}" data-workflow-node="${key}"><span class="dot">${icon}</span><span><b>${esc(label)}</b><small>${esc(step.message || labels[step.status] || "未记录")}</small></span><time title="${esc(stamp)}">${esc(labels[step.status] || "未记录")}${!horizontal && stamp ? `<small>${esc(stamp.replace("T", " ").split(" ")[1]?.slice(0, 8) || stamp)}</small>` : ""}</time></div>`;
  }).join("")}</div>`;
}
export function workflowLanes(data) {
  return data?.providers?.length ? data.providers : data?.job_id ? [data] : [];
}
export function fallbackJobWorkflow(job) {
  const stage = String(job.stage || "");
  const key = /search|resource|checking_saved|no_resource/.test(stage) ? "resource_search"
    : /tmdb|matching|names|review/.test(stage) ? "tmdb_rename"
    : /strm/.test(stage) ? "strm_generate" : /emby/.test(stage) ? "emby_refresh"
    : /notification/.test(stage) ? "library_notification"
    : /completed|partial|confirmation/.test(stage) ? "landing_confirm" : /provider|qas/.test(stage) ? "transfer" : null;
  return { steps: key ? [{ key, status: job.status === "done" ? "done" : job.status === "failed" ? "failed" : job.status === "needs_review" ? "review" : "running", message: job.message, updated_at: job.finished_at }] : [] };
}
