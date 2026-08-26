import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowClockwise,
  ArrowSquareOut,
  CheckCircle,
  Clock,
  FolderOpen,
  Pause,
  TerminalWindow,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { AppRoute } from "../../app/routes";
import { api, OpenListCopyTask, TransferJob } from "../../lib/api";
import { OpenListTaskMonitor } from "../openlist/OpenListTaskMonitor";

const PIPELINE = [
  ["tmdb_resolving", "TMDB"],
  ["checking_saved", "目录"],
  ["searching_sources", "搜索"],
  ["matching_files", "文件匹配"],
  ["provider_submitting", "提交转存"],
  ["provider_completed", "网盘确认"],
] as const;

const stageLabels: Record<string, string> = {
  tmdb_resolving: "读取 TMDB 媒体和分集信息",
  checking_saved: "检查目标网盘已有文件",
  validating_link: "验证上次使用的分享链接",
  searching_sources: "通过 PanSou 搜索候选资源",
  matching_files: "核对文件日期、期次和 TMDB 集数",
  preparing_names: "生成媒体库文件名",
  qas_transferring: "向夸克提交转存和改名",
  provider_submitting: "向目标网盘提交转存",
  provider_submitted: "任务已提交，等待网盘处理",
  provider_triggered: "网盘正在处理",
  provider_completed: "目标网盘已确认文件存在",
  source_not_updated: "候选资源尚未包含到期新内容，等待下次检查",
  not_due: "当前没有已播出且未保存的内容",
  openlist_sync: "OpenList 正在复制缺失文件",
  openlist_sync_done: "OpenList 已完成目录检查和提交",
  openlist_sync_failed: "OpenList 同步失败",
  strm_queued: "STRM 任务已排队",
  strm_scanning: "正在只读扫描网盘目录",
  strm_generating: "正在生成 STRM 与刮削资料",
  strm_completed: "STRM 生成完成",
  strm_failed: "STRM 生成失败",
  deletion_requested: "已收到 Emby 删除事件",
  deletion_trashing: "正在移入 115 回收站",
  deletion_completed: "115 删除同步完成",
  deletion_failed: "115 删除同步失败",
  cover_rendering: "正在生成并写入 Emby 媒体库封面",
  cover_completed: "Emby 媒体库封面生成完成",
  cover_failed: "Emby 媒体库封面生成失败",
  scheduled_running: "计划任务正在执行",
  scheduled_completed: "本轮计划任务已完成",
  scheduled_failed: "计划任务执行失败",
  needs_review: "文件核验存在歧义，等待人工确认",
  stopped: "任务已终止",
  internal_error: "任务执行异常",
};

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

function providerLabel(provider: TransferJob["provider"]) {
  if (provider === "qas") return "夸克（历史任务）";
  if (provider === "p115") return "115";
  if (provider === "moviepilot_115") return "MoviePilot 115";
  if (provider === "openlist") return "OpenList";
  if (provider === "strm") return "STRM";
  if (provider === "deletion") return "删除同步";
  if (provider === "emby") return "Emby 封面";
  if (provider === "scheduler") return "计划任务";
  return "MediaIndex";
}

function jobTitle(job: TransferJob) {
  if (job.provider === "openlist") return job.display_title || "网盘间同步";
  if (job.provider === "strm") return job.display_title || "STRM 生成";
  if (job.provider === "deletion") return job.display_title || "Emby → 115 删除同步";
  if (job.provider === "emby") return job.display_title || "Emby 媒体库封面";
  if (job.provider === "scheduler") return job.display_title || "计划任务";
  const action = job.target === "local" ? "保存到本地" : "网盘转存";
  return job.display_title ? `${job.display_title} · ${action}` : action;
}

function statusLabel(job: TransferJob) {
  if (job.status === "running") return "执行中";
  if (job.status === "ready") return "准备执行";
  if (job.status === "retry_wait") return "等待重试";
  if (job.status === "triggered") return "等待网盘确认";
  if (job.status === "done") return "已完成";
  if (job.status === "needs_review") return "待确认";
  if (job.status === "stopped") return "已终止";
  return "失败";
}

function formatDate(value?: string) {
  if (!value) return "";
  const parsed = new Date(value.includes("T") ? value : `${value.replace(" ", "T")}Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function progressIndex(stage: string) {
  const direct = PIPELINE.findIndex(([key]) => key === stage);
  if (direct >= 0) return direct;
  if (["validating_link"].includes(stage)) return 2;
  if (["preparing_names"].includes(stage)) return 3;
  if (["qas_transferring", "provider_submitted", "provider_triggered"].includes(stage)) return 4;
  return -1;
}

function routeForJob(job: TransferJob): AppRoute {
  const title = job.display_title || "";
  const source = job.request_source || "";
  if (job.status === "needs_review" && source !== "cloud_download_organizer") return { page: "discover", section: "review" };
  if (job.provider === "openlist") return { page: "cross-cloud" };
  if (job.provider === "strm") return { page: "strm", section: `${title} ${job.message}`.includes("夸克") ? "quark" : "p115" };
  if (job.provider === "deletion") return { page: "strm", section: "p115" };
  if (job.provider === "emby" || title.includes("Emby 媒体库封面")) return { page: "media-server" };
  if (title.includes("智能追更") || source.startsWith("tracking")) return { page: "subscriptions", section: "tracking" };
  if (title.includes("愿望单") || source.startsWith("wishlist")) return { page: "subscriptions", section: "wishlist" };
  if (title.includes("115 生活监控")) return { page: "strm", section: "p115" };
  if (title.includes("云下载整理") || source === "cloud_download_organizer") return { page: "workspace", section: "rules-organizer" };
  return { page: "workspace", section: "tasks" };
}

export function ActivityCenter({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<TransferJob[]>([]);
  const [openListTasks, setOpenListTasks] = useState<OpenListCopyTask[]>([]);
  const [stopping, setStopping] = useState(false);
  const [stoppingJobId, setStoppingJobId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [filter, setFilter] = useState<"all" | "active" | "failed" | "scheduled">("all");
  const loadingRef = useRef(false);

  async function load() {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const [next, openList] = await Promise.all([api.transfers().catch(() => []), api.openListTasks().catch(() => ({ available: false, message: "", tasks: [] }))]);
      setJobs(next.slice(0, 100));
      setOpenListTasks(openList.tasks.slice(0, 50));
    } finally { loadingRef.current = false; }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 2_500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    function refreshTasks() { void load(); }
    window.addEventListener("mediaindex:tasks-changed", refreshTasks);
    return () => window.removeEventListener("mediaindex:tasks-changed", refreshTasks);
  }, []);

  useEffect(() => {
    if (!open) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.body.classList.add("activity-dialog-open");
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.classList.remove("activity-dialog-open");
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  async function stopAll() {
    setStopping(true);
    setMessage("");
    try {
      const result = await api.stopActiveTransfers();
      setMessage(result.stopped ? `已停止 ${result.stopped} 个任务` : "当前没有可停止的任务");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "停止任务失败");
    } finally {
      setStopping(false);
    }
  }

  async function stopJob(job: TransferJob) {
    setStoppingJobId(job.id);
    setMessage("");
    try {
      const result = await api.stopTransfer(job.id);
      setMessage(result.message);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "终止任务失败");
    } finally {
      setStoppingJobId(null);
    }
  }

  function openJobPage(job: TransferJob) {
    setOpen(false);
    onNavigate(routeForJob(job));
  }

  const activeCount = jobs.filter((job) => job.provider !== "scheduler" && ["ready", "running", "triggered"].includes(job.status)).length + openListTasks.filter((task) => task.state === "running").length;
  const stoppableCount = jobs.filter((job) => !["emby", "scheduler"].includes(job.provider || "") && ["ready", "running", "triggered"].includes(job.status)).length;
  const scheduledJobs = jobs.filter((job) => job.request_source === "scheduler" || job.provider === "scheduler");
  const visibleJobs = useMemo(() => jobs.filter((job) => {
    const scheduled = job.request_source === "scheduler" || job.provider === "scheduler";
    if (filter === "scheduled") return scheduled;
    if (scheduled) return false;
    if (filter === "active") return ["ready", "running", "triggered"].includes(job.status);
    if (filter === "failed") return ["failed", "needs_review", "stopped"].includes(job.status);
    return true;
  }), [filter, jobs]);
  const visibleOpenListTasks = filter === "scheduled" ? [] : openListTasks.filter((task) => filter === "active" ? task.state === "running" : filter === "failed" ? task.state === "failed" : true);

  return (
    <div className="activity-center">
      <button className="icon notification-trigger" onClick={() => setOpen(true)} title="运行日志" aria-label={`运行日志${activeCount ? `，${activeCount} 个进行中` : ""}`} aria-expanded={open}>
        <TerminalWindow size={18} />
        {activeCount > 0 && <span className="notification-badge">{activeCount > 99 ? "99+" : activeCount}</span>}
      </button>
      {open && createPortal(
        <div className="activity-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section className="activity-dialog" role="dialog" aria-modal="true" aria-labelledby="activity-dialog-title">
            <header className="activity-dialog-head">
              <div className="activity-dialog-title">
                <span className="activity-dialog-icon"><TerminalWindow size={22} /></span>
                <div>
                  <h2 id="activity-dialog-title">运行日志</h2>
                  <p>{activeCount ? `${activeCount} 个任务正在执行，状态每 2.5 秒刷新` : "当前没有运行中的任务"}</p>
                </div>
              </div>
              <div className="activity-dialog-tools">
                <button className="ghost compact-action" onClick={() => void load()}><ArrowClockwise size={17} />刷新</button>
                <button className="ghost compact-action danger-action" onClick={() => void stopAll()} disabled={!stoppableCount || stopping}>{stopping ? <Spinner /> : <Pause size={17} />}全部停止</button>
                <button className="ghost compact-action activity-dialog-close" onClick={() => setOpen(false)} title="关闭运行日志" aria-label="关闭运行日志"><X size={18} />关闭</button>
              </div>
            </header>

            <div className="activity-dialog-summary">
              {([['all', '全部', jobs.length - scheduledJobs.length], ['active', '进行中', activeCount], ['failed', '异常', jobs.filter((job) => job.provider !== "scheduler" && ["failed", "needs_review", "stopped"].includes(job.status)).length], ['scheduled', '计划任务', scheduledJobs.length]] as const).map(([value, label, count]) => (
                <button type="button" className={filter === value ? "active" : ""} onClick={() => setFilter(value)} key={value}><span>{label}</span><strong>{value === "all" ? count + openListTasks.length : value === "active" ? activeCount : value === "failed" ? count + openListTasks.filter((task) => task.state === "failed").length : count}</strong></button>
              ))}
            </div>

            {message && <div className="activity-dialog-message">{message}</div>}
            <div className="activity-log-list">
              {visibleJobs.length === 0 && visibleOpenListTasks.length === 0 ? (
                <div className="activity-log-empty"><TerminalWindow size={30} /><strong>没有符合条件的任务</strong><span>新的转存、追更、封面和同步任务会显示在这里</span></div>
              ) : <>
                {visibleOpenListTasks.length > 0 && <section className="activity-openlist-tasks"><header><div><strong>OpenList 原生复制队列</strong><span>Token 实时读取</span></div><button type="button" className="ghost compact-action" onClick={() => { setOpen(false); onNavigate({ page: "cross-cloud" }); }}><ArrowSquareOut size={15} />打开跨盘转存</button></header><OpenListTaskMonitor compact tasks={visibleOpenListTasks} /></section>}
                {visibleJobs.map((job) => {
                const running = ["ready", "running", "triggered"].includes(job.status);
                const step = progressIndex(job.stage);
                return (
                  <article className={`activity-log-item status-${job.status}`} key={job.id}>
                    <div className="activity-log-topline">
                      <div className="activity-log-heading">
                        <span className={`activity-log-state ${job.status}`}>{running ? <Spinner /> : job.status === "done" ? <CheckCircle size={18} weight="fill" /> : job.status === "retry_wait" ? <Clock size={18} weight="fill" /> : <WarningCircle size={18} weight="fill" />}</span>
                        <div><h3>{jobTitle(job)}{job.season_number ? ` · S${job.season_number}` : ""}</h3><p>任务 #{job.id} · {providerLabel(job.provider)}</p></div>
                      </div>
                      <span className={`activity-status-pill ${job.status}`}>{statusLabel(job)}</span>
                    </div>

                    <div className="activity-current-step">
                      <strong>{stageLabels[job.stage] || job.stage || "正在处理任务"}</strong>
                      <span>{job.message || "等待服务返回执行结果"}</span>
                    </div>

                    {running && job.provider !== "openlist" && job.provider !== "strm" && job.provider !== "emby" && job.provider !== "scheduler" && (
                      <div className="activity-pipeline" aria-label="任务进度">
                        {PIPELINE.map(([key, label], index) => <span className={index < step ? "done" : index === step ? "current" : "pending"} key={key}>{index < step ? <CheckCircle size={13} weight="fill" /> : <i />}{label}</span>)}
                      </div>
                    )}

                    <div className="activity-log-meta">
                      {job.save_path && <span title={job.save_path}><FolderOpen size={15} />{job.save_path}</span>}
                      <span><Clock size={15} />开始 {formatDate(job.created_at) || "时间未记录"}{job.finished_at ? ` · 结束 ${formatDate(job.finished_at)}` : ""}</span>
                      {job.source_file && <span title={job.source_file}>源文件：{job.source_file}{job.renamed_file ? ` → ${job.renamed_file}` : ""}</span>}
                    </div>
                    <div className="activity-log-actions">
                      <button type="button" className="ghost compact-action" onClick={() => openJobPage(job)}><ArrowSquareOut size={15} />打开对应页面</button>
                      {running && !["emby", "scheduler"].includes(job.provider || "") && <button className="activity-item-stop" onClick={() => void stopJob(job)} disabled={stoppingJobId === job.id}>{stoppingJobId === job.id ? <Spinner /> : <Pause size={15} />}终止此任务</button>}
                    </div>
                  </article>
                );
                })}
              </>}
            </div>
          </section>
        </div>,
        document.body,
      )}
    </div>
  );
}
