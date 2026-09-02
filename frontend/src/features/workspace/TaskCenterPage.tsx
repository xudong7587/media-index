import { ArrowClockwise, ArrowRight, CaretRight, CheckCircle, CircleNotch, FolderOpen, Pause, WarningCircle, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { api, ReviewCandidate, TrackingTask, TransferJob, WishlistItem } from "../../lib/api";

type Tab = "running" | "planned";

const activeStates = new Set(["ready", "running", "triggered", "retry_wait"]);

function statusText(status: TransferJob["status"], organizer = false) {
  if (status === "needs_review" && organizer) return "需处理";
  return ({ ready: "准备执行", running: "执行中", triggered: "等待网盘", retry_wait: "等待重试", needs_review: "待确认", done: "已完成", failed: "失败", stopped: "已终止" } as Record<string, string>)[status] || status;
}

const taskStages = [
  ["tmdb_resolving", "媒体核对"],
  ["path_resolving", "路径规划"],
  ["resource_searching", "资源检索"],
  ["resource_matching", "资源验真"],
  ["submitting", "提交网盘"],
  ["completed", "完成"],
] as const;

function stageText(stage: string) {
  return ({
    organizer_needs_review: "目录需要重新核对",
    organizer_failed: "云下载整理失败",
    organizer_retry_requested: "等待重新核对",
    organizer_tmdb_resolving: "正在生成整理计划",
    organizer_transferring: "正在整理到媒体库",
    organizer_post_processing: "正在执行入库后处理",
    organizer_completed: "云下载整理完成",
  } as Record<string, string>)[stage] || stage || "等待执行";
}

function organizerCategoryText(category?: string) {
  return ({ movie: "电影", tv: "电视剧", anime: "动漫", variety: "综艺", documentary: "纪录片", concert: "演唱会" } as Record<string, string>)[category || ""] || "未记录";
}

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
    if (filter === "review") return job.status === "needs_review" || job.backfill_confirmation_state === "pending";
    if (filter === "failed") return ["failed", "stopped"].includes(job.status);
    return true;
  }), [filter, jobs]);
  const selectedReviews = selected ? reviews.filter((item) => item.job_id === selected.id) : [];
  const selectedIsOrganizerReview = selected?.request_source === "cloud_download_organizer";
  const selectedNewerJob = selected?.superseded_by_job_id
    ? jobs.find((job) => job.id === selected.superseded_by_job_id) || null
    : null;
  const selectedOrganizerIsVariety = selected?.organizer_category === "variety";

  async function stop(job: TransferJob) { setBusy(true); try { setMessage((await api.stopTransfer(job.id)).message); await load(); setSelected(null); } finally { setBusy(false); } }
  async function confirm(candidate: ReviewCandidate) { setBusy(true); try { const result = await api.confirmReview(candidate.id, candidate.files); setMessage(result.message || "已确认候选资源，任务继续执行"); await load(); setSelected(null); } finally { setBusy(false); } }
  async function research(job: TransferJob) { setBusy(true); try { const result = await api.researchReview(job.id); setMessage(result.message || "已重新搜索候选资源"); await load(); setSelected(null); } finally { setBusy(false); } }
  async function retryOrganizer(job: TransferJob) { setBusy(true); try { const result = await api.retryCloudDownloadOrganizer(job.id); setMessage(result.message); await load(); setSelected(null); } catch (error) { setMessage(error instanceof Error ? error.message : "重新核对失败"); } finally { setBusy(false); } }
  async function decideBackfill(job: TransferJob, start: boolean) { setBusy(true); try { const result = await api.decideOrganizedBackfill(job.id, start); setMessage(result.message); await load(); setSelected(null); } catch (error) { setMessage(error instanceof Error ? error.message : "补集操作失败"); } finally { setBusy(false); } }

  return (
    <section className="workspace-section task-center-page">
      <header className="portal-section-head"><div><h2>任务中心</h2><p>转存、同步、补集和跨盘任务共用一套状态；无法自动判定的任务会在详情里请求确认、修正或重新核对。</p></div><button type="button" className="ghost compact-action" onClick={() => void load()}><ArrowClockwise size={17} />刷新</button></header>
      <div className="portal-tabs" role="tablist">
        <button type="button" className={tab === "running" ? "active" : ""} onClick={() => setTab("running")}>执行任务 <span>{jobs.length}</span></button>
        <button type="button" className={tab === "planned" ? "active" : ""} onClick={() => setTab("planned")}>计划任务 <span>{tracking.length + wishlist.length}</span></button>
      </div>
      {message && <div className="notice page-notice">{message}</div>}
      {tab === "running" && <>
        <div className="task-filter-row">
          {([['all','全部',jobs.length],['active','进行中',jobs.filter((job) => activeStates.has(job.status)).length],['review','待决定 / 需处理',jobs.filter((job) => job.status === 'needs_review' || job.backfill_confirmation_state === 'pending').length],['failed','异常',jobs.filter((job) => ['failed','stopped'].includes(job.status)).length]] as const).map(([key,label,count]) => <button type="button" key={key} className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}<strong>{count}</strong></button>)}
        </div>
        <div className="task-table" role="list">
          {visible.length === 0 ? <div className="workspace-empty">当前筛选下没有任务</div> : visible.map((job) => <button type="button" className={`task-center-row status-${job.status}`} key={job.id} onClick={() => setSelected(job)}>
            <span className={`task-state-icon ${job.status}`}>{activeStates.has(job.status) ? <CircleNotch className="spin" /> : job.status === "done" ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}</span>
            <span className="task-center-main"><strong>{job.display_title || "网盘任务"}{job.season_number ? ` · S${job.season_number}` : ""}</strong><small>{job.message || job.stage}</small></span>
            <span className="task-provider">{job.provider === "p115" ? "115" : job.provider === "quark" ? "夸克" : job.provider || "MediaIndex"}</span>
            <span className={`task-status ${job.status}`}>{statusText(job.status, job.request_source === "cloud_download_organizer")}</span>
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
          <div className="task-detail-status" aria-live="polite"><div className="task-detail-status-line"><span className={`task-status ${selected.status}`}>{statusText(selected.status, selectedIsOrganizerReview)}</span><strong>{stageText(selected.stage)}</strong></div><p>{selected.message}</p></div>
          <dl className="task-detail-facts">
            <div><dt>来源目录</dt><dd>{selected.source_file || "未记录"}</dd></div>
            <div><dt>媒体分类</dt><dd>{selectedIsOrganizerReview ? organizerCategoryText(selected.organizer_category) : selected.media_type || "未记录"}</dd></div>
            <div><dt>执行端</dt><dd>{selected.provider || "MediaIndex"}</dd></div>
            <div><dt>目标</dt><dd>{selected.target === "local" ? "本地" : "网盘"}</dd></div>
            <div><dt>正式媒体库路径</dt><dd>{selected.save_path || "尚未生成"}</dd></div>
            <div><dt>创建时间</dt><dd>{selected.created_at || "未记录"}</dd></div>
          </dl>
          {selected.backfill_confirmation_state && <section className={`task-followup-panel state-${selected.backfill_confirmation_state}`}>
            <div className="task-followup-heading"><span>{selected.backfill_confirmation_state === "pending" ? "入库后缺集" : selected.backfill_confirmation_state === "started" ? "补集已启动" : "本次不补集"}</span><strong>{selected.backfill_available_episode_count || 0} / {selected.backfill_total_episode_count || 0} 集</strong></div>
            <p>{selected.backfill_confirmation_state === "pending"
              ? `正式媒体库已确认 ${selected.backfill_available_episode_count || 0} 集，缺 ${(selected.backfill_missing_episode_numbers || []).map((number) => `E${String(number).padStart(2, "0")}`).join("、")}。补集会通过 PanSou 单独检索并直接写入正式媒体库，不经过云下载。`
              : selected.backfill_decision_message || (selected.backfill_confirmation_state === "started" ? "补集已作为独立任务运行。" : "转存与入库结果保持完成，后续追更不受影响。")}</p>
            {selected.backfill_confirmation_state === "pending" && <div className="task-followup-actions"><button type="button" className="primary compact-action" disabled={busy} onClick={() => void decideBackfill(selected, true)}>{busy ? <CircleNotch className="spin" /> : <ArrowRight />}启动一次补集</button><button type="button" className="ghost compact-action" disabled={busy} onClick={() => void decideBackfill(selected, false)}>暂不补集</button></div>}
          </section>}
          {selectedIsOrganizerReview && ["needs_review", "failed"].includes(selected.status)
            ? <section className={`task-resolution-panel${selected.superseded_by_job_id ? " superseded" : selectedOrganizerIsVariety ? " strict" : ""}`}>
                <span className="task-resolution-icon" aria-hidden="true"><FolderOpen weight="duotone" /></span>
                <div className="task-resolution-copy">
                  <span>{selected.superseded_by_job_id ? "目录已更新" : selectedOrganizerIsVariety ? "综艺严格核对" : "普通剧集直接整理"}</span>
                  <h3>{selected.superseded_by_job_id ? `请继续任务 #${selected.superseded_by_job_id}` : selectedOrganizerIsVariety ? "按期数与节目结构重新核对" : "按已确认信息重新生成改名计划"}</h3>
                  <p>{selected.superseded_by_job_id
                    ? "这是一条较早的目录记录，同一媒体已有更新任务。旧记录不再重复扫描或执行文件操作。"
                    : selectedOrganizerIsVariety
                      ? "综艺仍会核对日期、期数、上下篇和特别内容，再决定改名与落盘。"
                      : "片名、年份和季度以用户确认结果为准，不再用网盘文件名筛选剧名。系统只要求集号明确且不重复，然后按命名规则整理到正式媒体库。"}</p>
                </div>
                {selected.superseded_by_job_id
                  ? <button type="button" className="secondary compact-action task-resolution-action" disabled={!selectedNewerJob} onClick={() => selectedNewerJob && setSelected(selectedNewerJob)}>查看新任务 <ArrowRight /></button>
                  : <button type="button" className="primary compact-action task-resolution-action" disabled={busy} onClick={() => void retryOrganizer(selected)}>{busy ? <CircleNotch className="spin" /> : <ArrowClockwise />}重新核对</button>}
              </section>
            : selected.status === "needs_review"
              ? <section className="task-review-section"><h3>需要你确认</h3>{selectedReviews.length === 0 ? <p>当前没有可用候选项，可以让 MediaIndex 重新搜索。</p> : selectedReviews.map((candidate) => <article key={candidate.id}><strong>{candidate.source_title}</strong><p>{candidate.reasons.join(" · ") || candidate.job_message}</p><span>{candidate.files.length} 个文件 · {candidate.source}</span><button type="button" className="primary compact-action" disabled={busy} onClick={() => void confirm(candidate)}>确认此候选并继续</button></article>)}<button type="button" className="ghost compact-action" disabled={busy} onClick={() => void research(selected)}><ArrowClockwise />重新搜索</button></section>
              : null}
          <footer>{activeStates.has(selected.status) && <button type="button" className="ghost danger-action" disabled={busy} onClick={() => void stop(selected)}><Pause />终止任务</button>}<button type="button" className="ghost" onClick={() => setSelected(null)}>关闭</button></footer>
        </article>
      </div>, document.body)}
    </section>
  );
}
