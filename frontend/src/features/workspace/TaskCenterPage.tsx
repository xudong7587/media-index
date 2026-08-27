import { ArrowClockwise, CaretRight, CheckCircle, CircleNotch, Clock, FolderOpen, Pause, WarningCircle, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { api, ReviewCandidate, TrackingTask, TransferJob, WishlistItem } from "../../lib/api";

type Tab = "running" | "planned";

const activeStates = new Set(["ready", "running", "triggered", "retry_wait"]);

function statusText(status: TransferJob["status"]) {
  return ({ ready: "准备执行", running: "执行中", triggered: "等待网盘", retry_wait: "等待重试", needs_review: "待确认", done: "已完成", failed: "失败", stopped: "已终止" } as Record<string, string>)[status] || status;
}

const taskStages = [
  ["tmdb_resolving", "TMDB 核对"],
  ["path_resolving", "路径规划"],
  ["resource_searching", "资源检索"],
  ["resource_matching", "资源验真"],
  ["submitting", "提交网盘"],
  ["completed", "完成"],
] as const;

function stagePosition(stage: string, status: TransferJob["status"]) {
  if (status === "done") return taskStages.length;
  const normalized = stage.toLowerCase();
  const index = taskStages.findIndex(([key]) => normalized.includes(key.replace("_resolving", "")));
  return index < 0 ? 0 : index;
}

export function TaskCenterPage() {
  const [tab, setTab] = useState<Tab>("running");
  const [jobs, setJobs] = useState<TransferJob[]>([]);
  const [reviews, setReviews] = useState<ReviewCandidate[]>([]);
  const [tracking, setTracking] = useState<TrackingTask[]>([]);
  const [wishlist, setWishlist] = useState<WishlistItem[]>([]);
  const [selected, setSelected] = useState<TransferJob | null>(null);
  const [filter, setFilter] = useState<"all" | "active" | "review" | "failed">("all");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    const [nextJobs, nextReviews, nextTracking, nextWishlist] = await Promise.all([api.transfers(), api.review(), api.tracking(), api.wishlist()]);
    setJobs(nextJobs); setReviews(nextReviews); setTracking(nextTracking); setWishlist(nextWishlist);
  }
  useEffect(() => { void load().catch((error: Error) => setMessage(error.message)); const timer = window.setInterval(() => void load().catch(() => undefined), 5000); return () => window.clearInterval(timer); }, []);

  const visible = useMemo(() => jobs.filter((job) => {
    if (filter === "active") return activeStates.has(job.status);
    if (filter === "review") return job.status === "needs_review";
    if (filter === "failed") return ["failed", "stopped"].includes(job.status);
    return true;
  }), [filter, jobs]);
  const selectedReviews = selected ? reviews.filter((item) => item.job_id === selected.id) : [];
  const selectedIsOrganizerReview = selected?.request_source === "cloud_download_organizer";

  async function stop(job: TransferJob) { setBusy(true); try { setMessage((await api.stopTransfer(job.id)).message); await load(); setSelected(null); } finally { setBusy(false); } }
  async function confirm(candidate: ReviewCandidate) { setBusy(true); try { const result = await api.confirmReview(candidate.id, candidate.files); setMessage(result.message || "已确认候选资源，任务继续执行"); await load(); setSelected(null); } finally { setBusy(false); } }
  async function research(job: TransferJob) { setBusy(true); try { const result = await api.researchReview(job.id); setMessage(result.message || "已重新搜索候选资源"); await load(); setSelected(null); } finally { setBusy(false); } }

  return (
    <section className="workspace-section task-center-page">
      <header className="portal-section-head"><div><h2>任务中心</h2><p>转存、同步、补集和跨盘任务共用一套状态；无法自动判定的任务会在详情里请求确认。</p></div><button type="button" className="ghost compact-action" onClick={() => void load()}><ArrowClockwise size={17} />刷新</button></header>
      <div className="portal-tabs" role="tablist">
        <button type="button" className={tab === "running" ? "active" : ""} onClick={() => setTab("running")}>执行任务 <span>{jobs.length}</span></button>
        <button type="button" className={tab === "planned" ? "active" : ""} onClick={() => setTab("planned")}>计划任务 <span>{tracking.length + wishlist.length}</span></button>
      </div>
      {message && <div className="notice page-notice">{message}</div>}
      {tab === "running" && <>
        <div className="task-filter-row">
          {([['all','全部',jobs.length],['active','进行中',jobs.filter((job) => activeStates.has(job.status)).length],['review','待确认',jobs.filter((job) => job.status === 'needs_review').length],['failed','异常',jobs.filter((job) => ['failed','stopped'].includes(job.status)).length]] as const).map(([key,label,count]) => <button type="button" key={key} className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}<strong>{count}</strong></button>)}
        </div>
        <div className="task-table" role="list">
          {visible.length === 0 ? <div className="workspace-empty">当前筛选下没有任务</div> : visible.map((job) => <button type="button" className={`task-center-row status-${job.status}`} key={job.id} onClick={() => setSelected(job)}>
            <span className={`task-state-icon ${job.status}`}>{activeStates.has(job.status) ? <CircleNotch className="spin" /> : job.status === "done" ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}</span>
            <span className="task-center-main"><strong>{job.display_title || "网盘任务"}{job.season_number ? ` · S${job.season_number}` : ""}</strong><small>{job.message || job.stage}</small></span>
            <span className="task-provider">{job.provider === "p115" ? "115" : job.provider === "quark" ? "夸克" : job.provider || "MediaIndex"}</span>
            <span className={`task-status ${job.status}`}>{statusText(job.status)}</span>
            <CaretRight />
          </button>)}
        </div>
      </>}
      {tab === "planned" && <div className="planned-task-grid">
        <section><h3>智能追更</h3><strong>{tracking.length}</strong><p>按播出进度检查缺集并创建任务。</p>{tracking.slice(0, 5).map((item) => <div className="planned-task-item" key={item.id}><span>{item.title}</span><small>{item.status}</small></div>)}</section>
        <section><h3>愿望单</h3><strong>{wishlist.length}</strong><p>按上映时间和检查时间创建资源任务。</p>{wishlist.slice(0, 5).map((item) => <div className="planned-task-item" key={item.id}><span>{item.title}</span><small>{item.status}</small></div>)}</section>
      </div>}
      {selected && createPortal(<div className="task-detail-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}>
        <article className="task-detail-panel" role="dialog" aria-modal="true" aria-label={`任务 ${selected.id} 详情`}>
          <header><div><span>任务 #{selected.id}</span><h2>{selected.display_title || "网盘任务"}</h2></div><button type="button" className="icon" onClick={() => setSelected(null)} aria-label="关闭任务详情"><X /></button></header>
          <div className="task-pipeline" aria-label="任务流程">
            {taskStages.map(([key, label], index) => {
              const current = stagePosition(selected.stage || "", selected.status);
              const state = index < current ? "done" : index === current && selected.status !== "done" ? "current" : "pending";
              return <div className={state} key={key}><span>{index + 1}</span><small>{label}</small></div>;
            })}
          </div>
          <div className="task-detail-status"><span className={`task-status ${selected.status}`}>{statusText(selected.status)}</span><strong>{selected.stage || "等待执行"}</strong><p>{selected.message}</p></div>
          <dl className="task-detail-facts"><div><dt>执行端</dt><dd>{selected.provider || "MediaIndex"}</dd></div><div><dt>目标</dt><dd>{selected.target === "local" ? "本地" : "网盘"}</dd></div><div><dt>保存路径</dt><dd>{selected.save_path || "任务尚未确定"}</dd></div><div><dt>创建时间</dt><dd>{selected.created_at || "未记录"}</dd></div></dl>
          {selected.status === "needs_review" && (selectedIsOrganizerReview
            ? <section className="task-review-section"><h3>需要修正来源</h3><p>云下载整理的待确认状态仅用于安全阻断，不提供普通候选确认或重新搜索。请修正源目录名称、内容或目标命名冲突；下次该媒体的 MediaIndex 转存完成事件会定点重新核对。</p></section>
            : <section className="task-review-section"><h3>需要你确认</h3>{selectedReviews.length === 0 ? <p>当前没有可用候选项，可以让 MediaIndex 重新搜索。</p> : selectedReviews.map((candidate) => <article key={candidate.id}><strong>{candidate.source_title}</strong><p>{candidate.reasons.join(" · ") || candidate.job_message}</p><span>{candidate.files.length} 个文件 · {candidate.source}</span><button type="button" className="primary compact-action" disabled={busy} onClick={() => void confirm(candidate)}>确认此候选并继续</button></article>)}<button type="button" className="ghost compact-action" disabled={busy} onClick={() => void research(selected)}><ArrowClockwise />重新搜索</button></section>)}
          <footer>{activeStates.has(selected.status) && <button type="button" className="ghost danger-action" disabled={busy} onClick={() => void stop(selected)}><Pause />终止任务</button>}<button type="button" className="ghost" onClick={() => setSelected(null)}>关闭</button></footer>
        </article>
      </div>, document.body)}
    </section>
  );
}
