import {
  ArrowClockwise,
  ArrowRight,
  CheckCircle,
  CircleNotch,
  Cloud,
  FolderOpen,
  HardDrives,
  Play,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  api,
  ApiError,
  type CloudDownloadOrganizerMode,
  type CloudDownloadOrganizerRunJob,
  type ConfigStatus,
  type TransferJob,
} from "../../lib/api";
import "./cloud-download-organizer.css";

type Provider = "quark" | "p115";
type ResultMessage = { ok: boolean; text: string } | null;
type DirectoryOption = { name: string; path: string };

const providers: Provider[] = ["quark", "p115"];
const activeStates = new Set<TransferJob["status"]>(["ready", "running", "triggered", "retry_wait"]);

function OrganizerSection({ title, body, children }: { title: string; body: string; children: ReactNode }) {
  return (
    <section className="settings-section organizer-settings-section">
      <header><strong>{title}</strong><span>{body}</span></header>
      <div className="settings-section-body">{children}</div>
    </section>
  );
}

function providerLabel(provider: Provider) {
  return provider === "p115" ? "115" : "夸克";
}

function providerIcon(provider: Provider) {
  return provider === "p115" ? <HardDrives size={21} /> : <Cloud size={21} />;
}

function normalizePath(value: string) {
  const normalized = String(value || "").trim().replace(/\\/g, "/").replace(/\/{2,}/g, "/");
  if (!normalized || normalized === "/") return "/";
  return `/${normalized.replace(/^\/+|\/+$/g, "")}`;
}

function childPath(root: string, name: string) {
  const base = normalizePath(root);
  return `${base === "/" ? "" : base}/${name}`;
}

function leafName(path: string) {
  const parts = normalizePath(path).split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}

function sameStringSet(left: string[], right: string[]) {
  return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
}

function requestError(error: unknown, fallback: string) {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return fallback;
}

function statusLabel(status: TransferJob["status"]) {
  return ({
    ready: "等待执行",
    running: "正在整理",
    triggered: "等待网盘",
    retry_wait: "等待重试",
    needs_review: "待确认",
    done: "已完成",
    failed: "失败",
    stopped: "已终止",
  } as Record<TransferJob["status"], string>)[status];
}

function jobStageLabel(stage: string) {
  return ({
    cloud_download_scanning: "扫描云下载目录",
    organizer_scanning: "扫描云下载目录",
    organizer_waiting_stable: "等待下载内容稳定",
    organizer_resuming: "核验上次中断状态",
    organizer_recovering: "续作上次中断整理",
    organizer_tmdb_resolving: "TMDB 信息核对",
    organizer_transferring: "网盘内转存",
    organizer_post_processing: "生成 STRM 并通知入库",
    organizer_completed: "整理完成",
    organizer_failed: "整理失败",
    organizer_needs_review: "等待人工确认",
    organizer_scan_completed: "本轮扫描完成",
    organizer_scan_failed: "本轮扫描失败",
    organizer_scan_stopped: "本轮扫描已停止",
    organizer_stopped: "用户已停止整理",
    tmdb_resolving: "TMDB 信息核对",
    media_organizing: "建立目录并规范命名",
    provider_transferring: "网盘内转存",
    post_transfer: "生成 STRM 与通知入库",
    needs_review: "等待人工确认",
    done: "整理完成",
    failed: "整理失败",
  } as Record<string, string>)[stage] || stage || "等待处理";
}

export function CloudDownloadOrganizerSettings({
  onOpenProviderRules,
  onOpenTasks,
}: {
  onOpenProviderRules: (provider: Provider) => void;
  onOpenTasks: () => void;
}) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [configError, setConfigError] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [mode, setMode] = useState<CloudDownloadOrganizerMode>("copy");
  const [intervalMinutes, setIntervalMinutes] = useState("10");
  const [stableMinutes, setStableMinutes] = useState("10");
  const [selectedDirectories, setSelectedDirectories] = useState<Record<Provider, string[]>>({ quark: [], p115: [] });
  const [directoryOptions, setDirectoryOptions] = useState<Record<Provider, DirectoryOption[]>>({ quark: [], p115: [] });
  const [directoryLoaded, setDirectoryLoaded] = useState<Record<Provider, boolean>>({ quark: false, p115: false });
  const [directoryLoading, setDirectoryLoading] = useState<Provider | "">("");
  const [directoryErrors, setDirectoryErrors] = useState<Record<Provider, string>>({ quark: "", p115: "" });
  const [jobs, setJobs] = useState<TransferJob[]>([]);
  const [jobsError, setJobsError] = useState("");
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState<"all" | Provider | "">("");
  const [message, setMessage] = useState<ResultMessage>(null);
  const [lastRunJobs, setLastRunJobs] = useState<CloudDownloadOrganizerRunJob[]>([]);

  function applyConfig(next: ConfigStatus) {
    setConfig(next);
    setEnabled(next.cloud_download_organizer_enabled);
    setMode(next.cloud_download_organizer_mode);
    setIntervalMinutes(String(next.cloud_download_organizer_interval_minutes));
    setStableMinutes(String(next.cloud_download_organizer_stable_minutes));
    setSelectedDirectories({
      quark: [...(next.quark_cloud_download_organizer_directories || [])],
      p115: [...(next.p115_cloud_download_organizer_directories || [])],
    });
  }

  async function loadConfig() {
    setConfigError("");
    try {
      applyConfig(await api.config());
    } catch (error) {
      setConfigError(requestError(error, "云下载整理配置读取失败"));
    }
  }

  async function loadJobs() {
    try {
      setJobs(await api.transfers());
      setJobsError("");
    } catch (error) {
      setJobsError(requestError(error, "云下载整理任务状态读取失败"));
    }
  }

  useEffect(() => {
    void loadConfig();
    void loadJobs();
    const timer = window.setInterval(() => void loadJobs(), 5_000);
    return () => window.clearInterval(timer);
  }, []);

  const organizerJobs = useMemo(
    () => jobs.filter((job) => job.request_source === "cloud_download_organizer").slice(0, 6),
    [jobs],
  );
  const activeJobs = organizerJobs.filter((job) => activeStates.has(job.status));
  const selectedCount = selectedDirectories.quark.length + selectedDirectories.p115.length;
  const dirty = Boolean(config) && (
    enabled !== config?.cloud_download_organizer_enabled
    || mode !== config?.cloud_download_organizer_mode
    || Number(intervalMinutes) !== config?.cloud_download_organizer_interval_minutes
    || Number(stableMinutes) !== config?.cloud_download_organizer_stable_minutes
    || !sameStringSet(selectedDirectories.quark, config?.quark_cloud_download_organizer_directories || [])
    || !sameStringSet(selectedDirectories.p115, config?.p115_cloud_download_organizer_directories || [])
  );

  function sourceRoot(provider: Provider) {
    if (!config) return "";
    return provider === "p115" ? config.p115_cloud_download_path : config.quark_cloud_download_path;
  }

  function libraryRoot(provider: Provider) {
    if (!config) return "";
    return provider === "p115" ? config.p115_root_path : config.quark_root_path;
  }

  function connected(provider: Provider) {
    if (!config) return false;
    return provider === "p115" ? config.has_p115_cookie : config.has_quark_cookie;
  }

  function mappedTarget(provider: Provider, source: string) {
    return childPath(libraryRoot(provider), leafName(source));
  }

  async function loadProviderDirectories(provider: Provider) {
    const root = sourceRoot(provider);
    if (!root) return;
    setDirectoryLoading(provider);
    setDirectoryErrors((current) => ({ ...current, [provider]: "" }));
    try {
      const result = await api.browseProviderPath(provider, root, true);
      const options = result.directories
        .filter((item) => item.is_dir)
        .map((item) => ({ name: item.name, path: childPath(result.path, item.name) }));
      setDirectoryOptions((current) => ({ ...current, [provider]: options }));
      setDirectoryLoaded((current) => ({ ...current, [provider]: true }));
    } catch (error) {
      setDirectoryErrors((current) => ({ ...current, [provider]: requestError(error, `${providerLabel(provider)}一级子目录读取失败`) }));
      setDirectoryLoaded((current) => ({ ...current, [provider]: false }));
    } finally {
      setDirectoryLoading("");
    }
  }

  function toggleDirectory(provider: Provider, path: string, checked: boolean) {
    setSelectedDirectories((current) => ({
      ...current,
      [provider]: checked
        ? Array.from(new Set([...current[provider], path]))
        : current[provider].filter((item) => item !== path),
    }));
  }

  function selectAllDirectories(provider: Provider) {
    setSelectedDirectories((current) => ({
      ...current,
      [provider]: directoryOptions[provider].map((item) => item.path),
    }));
  }

  async function save() {
    if (!config) return;
    const interval = Number(intervalMinutes);
    const stable = Number(stableMinutes);
    if (!Number.isInteger(interval) || interval < 1 || interval > 1_440) {
      setMessage({ ok: false, text: "自动检查间隔必须是 1-1440 分钟的整数。" });
      return;
    }
    if (!Number.isInteger(stable) || stable < 1 || stable > 1_440) {
      setMessage({ ok: false, text: "文件稳定等待必须是 1-1440 分钟的整数。" });
      return;
    }
    if (enabled && selectedCount === 0) {
      setMessage({ ok: false, text: "开启自动整理前，请至少为一个网盘勾选一个一级子目录。" });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await api.saveConfig({
        cloud_download_organizer_enabled: enabled,
        cloud_download_organizer_mode: mode,
        cloud_download_organizer_interval_minutes: interval,
        cloud_download_organizer_stable_minutes: stable,
        p115_cloud_download_organizer_directories: selectedDirectories.p115,
        quark_cloud_download_organizer_directories: selectedDirectories.quark,
      });
      applyConfig(await api.config());
      setMessage({ ok: true, text: "云下载整理规则已保存；新一轮任务会使用这份范围和模式。" });
    } catch (error) {
      setMessage({ ok: false, text: requestError(error, "云下载整理规则保存失败") });
    } finally {
      setSaving(false);
    }
  }

  async function runNow(provider?: Provider) {
    if (!enabled) {
      setMessage({ ok: false, text: "请先开启并保存云下载整理功能，再发起立即整理。" });
      return;
    }
    if (!config?.has_tmdb_key) {
      setMessage({ ok: false, text: "TMDB API Key 尚未配置，无法安全核对媒体身份。" });
      return;
    }
    if (dirty) {
      setMessage({ ok: false, text: "当前规则尚未保存，请先保存再发起整理。" });
      return;
    }
    if (provider && selectedDirectories[provider].length === 0) {
      setMessage({ ok: false, text: `${providerLabel(provider)}尚未勾选任何一级子目录。` });
      return;
    }
    if (mode === "move" && !window.confirm("当前为移动模式。目标逐项核验后，只会按文件 ID 精确清理当时仍在源媒体目录内的残留普通文件，并保留源目录壳；如发现新到达文件或疑似视频会停止清理。确认立即整理吗？")) return;
    setRunning(provider || "all");
    setMessage(null);
    setLastRunJobs([]);
    try {
      const result = await api.runCloudDownloadOrganizer(provider);
      setLastRunJobs(result.jobs || []);
      setMessage({ ok: result.ok, text: result.message || "云下载整理任务已创建。" });
      await loadJobs();
      window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setMessage({ ok: false, text: requestError(error, "云下载整理任务启动失败") });
    } finally {
      setRunning("");
    }
  }

  if (!config) {
    if (configError) {
      return (
        <div className="organizer-load-state error" role="alert">
          <WarningCircle size={28} />
          <div><strong>无法读取云下载整理配置</strong><span>{configError}</span></div>
          <button type="button" className="ghost compact-action" onClick={() => void loadConfig()}>重试</button>
        </div>
      );
    }
    return <div className="workspace-loading"><CircleNotch className="spin" />正在读取云下载整理规则</div>;
  }

  const overviewState = !enabled
    ? { className: "off", title: "自动整理已关闭", body: "现有目录和任务不会被改动。" }
    : selectedCount === 0
      ? { className: "warning", title: "规则尚未就绪", body: "至少勾选一个一级子目录后才能自动运行。" }
      : activeJobs.length > 0
        ? { className: "running", title: `${activeJobs.length} 个整理任务正在执行`, body: activeJobs[0]?.message || "正在核对云下载目录" }
        : !config.has_tmdb_key
          ? { className: "warning", title: "TMDB 尚未配置", body: "自动整理会保持关闭式失败，不会在缺少媒体身份时猜测命名或移动。" }
          : providers.some((provider) => selectedDirectories[provider].length > 0 && !connected(provider))
            ? { className: "warning", title: "已选网盘尚未连接", body: "请先完成对应网盘连接；连接失败不会被当成空目录。" }
            : { className: "ready", title: "自动整理已就绪", body: `每 ${intervalMinutes} 分钟检查一次，仅处理稳定至少 ${stableMinutes} 分钟的内容。` };

  return (
    <section className="cloud-download-organizer">
      <div className={`organizer-overview ${overviewState.className}`} aria-live="polite">
        <div className="organizer-overview-icon">
          {overviewState.className === "running" ? <CircleNotch className="spin" /> : overviewState.className === "ready" ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}
        </div>
        <div><strong>{overviewState.title}</strong><span>{overviewState.body}</span></div>
        <div className="organizer-overview-actions">
          <button type="button" className="ghost compact-action" onClick={onOpenTasks}>查看任务中心</button>
          <button type="button" className="primary compact-action" disabled={!enabled || !config.has_tmdb_key || dirty || selectedCount === 0 || !providers.some((provider) => selectedDirectories[provider].length > 0 && connected(provider)) || Boolean(running) || saving} onClick={() => void runNow()}>
            {running === "all" ? <CircleNotch className="spin" /> : <Play weight="fill" />}{running === "all" ? "正在启动" : "立即整理全部"}
          </button>
        </div>
      </div>

      {message && <div className={`settings-inline-result organizer-message ${message.ok ? "success" : "error"}`} role="status">{message.text}</div>}
      {lastRunJobs.length > 0 && (
        <div className="organizer-run-results" aria-label="本次启动结果">
          {lastRunJobs.map((item, index) => (
            <span className={(item.ok ?? item.accepted) ? "success" : "error"} key={`${item.provider}-${item.job_id || index}`}>
              {(item.ok ?? item.accepted) ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}
              <strong>{providerLabel(item.provider)}</strong>{item.message}{item.job_id ? `（任务 #${item.job_id}）` : ""}
            </span>
          ))}
        </div>
      )}

      <OrganizerSection title="自动整理规则" body="总开关只控制云下载整理，不改变现有转存、STRM 或通知开关。">
        <div className="settings-field">
          <span>自动整理开关<small className="settings-field-help">关闭后不再自动扫描，也不会删除配置、目录或历史任务。</small></span>
          <div className="toggle-group" role="group" aria-label="自动整理开关">
            <button type="button" className={enabled ? "active" : ""} onClick={() => setEnabled(true)}>已开启</button>
            <button type="button" className={!enabled ? "active" : ""} onClick={() => setEnabled(false)}>已关闭</button>
          </div>
        </div>
        <div className="settings-field">
          <span>转存模式<small className="settings-field-help">复制不改来源；移动在目标完整核验后仅按 ID 精确清理残留普通文件，并保留源目录壳。</small></span>
          <div className="toggle-group organizer-mode-toggle" role="group" aria-label="云下载整理转存模式">
            <button type="button" className={mode === "copy" ? "active" : ""} onClick={() => setMode("copy")}>复制</button>
            <button type="button" className={mode === "move" ? "active" : ""} onClick={() => setMode("move")}>移动</button>
          </div>
        </div>
        <label className="settings-field organizer-number-setting">
          <span>自动检查间隔<small className="settings-field-help">定时读取已勾选目录；范围 1-1440 分钟。</small></span>
          <div><input type="number" inputMode="numeric" min={1} max={1440} value={intervalMinutes} onChange={(event) => setIntervalMinutes(event.target.value.replace(/[^0-9]/g, ""))} /><em>分钟</em></div>
        </label>
        <label className="settings-field organizer-number-setting">
          <span>文件稳定等待<small className="settings-field-help">新文件在这段时间内不再变化，才会进入 TMDB 核对。</small></span>
          <div><input type="number" inputMode="numeric" min={1} max={1440} value={stableMinutes} onChange={(event) => setStableMinutes(event.target.value.replace(/[^0-9]/g, ""))} /><em>分钟</em></div>
        </label>
      </OrganizerSection>

      <div className="organizer-provider-grid">
        {providers.map((provider) => {
          const label = providerLabel(provider);
          const root = sourceRoot(provider);
          const targetRoot = libraryRoot(provider);
          const options = directoryOptions[provider];
          const selected = selectedDirectories[provider];
          const availablePaths = new Set(options.map((item) => item.path));
          const staleSelections = directoryLoaded[provider] ? selected.filter((path) => !availablePaths.has(path)) : [];
          const isConnected = connected(provider);
          return (
            <article className="settings-section organizer-provider-card" key={provider}>
              <header>
                <div className="organizer-provider-title">{providerIcon(provider)}<div><strong>{label} 云下载目录</strong><span>只整理明确勾选的一级子目录</span></div></div>
                <span className={`connection-pill ${isConnected ? "connected" : ""}`}>{isConnected ? <CheckCircle weight="fill" /> : <WarningCircle />}{isConnected ? "已连接" : "未连接"}</span>
              </header>
              <div className="settings-section-body organizer-provider-body">
                <dl className="organizer-root-summary">
                  <div><dt>云下载根</dt><dd><code>{root || "未配置"}</code></dd></div>
                  <div><dt>正式媒体库根</dt><dd><code>{targetRoot || "未配置"}</code></dd></div>
                </dl>
                <div className="organizer-provider-actions">
                  <button type="button" className="ghost compact-action" onClick={() => onOpenProviderRules(provider)}>修改{label}目录规则</button>
                  <button type="button" className="ghost compact-action" disabled={!isConnected || !root || Boolean(directoryLoading)} onClick={() => void loadProviderDirectories(provider)}>
                    {directoryLoading === provider ? <CircleNotch className="spin" /> : <ArrowClockwise />}{directoryLoading === provider ? "读取中" : "读取一级子目录"}
                  </button>
                  <button type="button" className="ghost compact-action" disabled={!enabled || !config.has_tmdb_key || !isConnected || dirty || selected.length === 0 || Boolean(running) || saving} onClick={() => void runNow(provider)}>
                    {running === provider ? <CircleNotch className="spin" /> : <Play />}{running === provider ? "正在启动" : `整理${label}`}
                  </button>
                </div>
                {!isConnected && <div className="organizer-provider-state warning"><WarningCircle />{label}未连接，MediaIndex 不会把连接失败当作目录为空。</div>}
                {directoryErrors[provider] && <div className="organizer-provider-state error" role="alert"><WarningCircle />{directoryErrors[provider]}<button type="button" onClick={() => void loadProviderDirectories(provider)}>重试</button></div>}

                {!directoryLoaded[provider] && !directoryErrors[provider] && selected.length === 0 && (
                  <div className="organizer-directory-empty"><FolderOpen size={27} /><strong>尚未读取一级子目录</strong><span>点击“读取一级子目录”后选择范围；不会默认整理整个云下载根。</span></div>
                )}
                {!directoryLoaded[provider] && selected.length > 0 && (
                  <div className="organizer-saved-mappings">
                    <strong>已保存的整理范围</strong>
                    {selected.map((path) => <MappingPreview key={path} provider={provider} source={path} target={mappedTarget(provider, path)} />)}
                  </div>
                )}
                {directoryLoaded[provider] && options.length === 0 && (
                  <div className="organizer-directory-empty"><FolderOpen size={27} /><strong>当前云下载目录没有一级子目录</strong><span>请先按正式媒体库分类建立一级子目录；云下载根目录本身的散落文件不会整理。</span></div>
                )}
                {directoryLoaded[provider] && options.length > 0 && (
                  <div className="organizer-directory-scope">
                    <div className="organizer-directory-scope-head">
                      <div><strong>选择整理范围</strong><span>{selected.length} / {options.length} 个当前目录已勾选</span></div>
                      <div><button type="button" onClick={() => selectAllDirectories(provider)}>全选当前目录</button><button type="button" onClick={() => setSelectedDirectories((current) => ({ ...current, [provider]: [] }))}>清空</button></div>
                    </div>
                    <div className="organizer-directory-list">
                      {options.map((option) => (
                        <label className={selected.includes(option.path) ? "selected" : ""} key={option.path}>
                          <input type="checkbox" checked={selected.includes(option.path)} onChange={(event) => toggleDirectory(provider, option.path, event.target.checked)} />
                          <FolderOpen size={18} />
                          <span><strong>{option.name}</strong><small><code>{option.path}</code><ArrowRight /><code>{mappedTarget(provider, option.path)}</code></small></span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
                {staleSelections.length > 0 && (
                  <div className="organizer-stale-scope" role="alert">
                    <strong><WarningCircle weight="fill" />以下已保存目录本次未读取到，已保留选择但不会静默当作空目录：</strong>
                    {staleSelections.map((path) => <MappingPreview key={path} provider={provider} source={path} target={mappedTarget(provider, path)} stale />)}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <OrganizerSection title="最近整理状态" body="与任务中心使用同一份标准任务记录；一个网盘失败不会隐藏另一个网盘的结果。">
        {jobsError && <div className="organizer-provider-state error" role="alert"><WarningCircle />{jobsError}<button type="button" onClick={() => void loadJobs()}>重试</button></div>}
        {!jobsError && organizerJobs.length === 0 && (
          <div className="organizer-job-empty"><FolderOpen size={28} /><strong>还没有云下载整理任务</strong><span>保存并开启规则后等待自动检查，或点击“立即整理全部”。</span></div>
        )}
        {!jobsError && organizerJobs.length > 0 && (
          <div className="organizer-job-list">
            {organizerJobs.map((job) => {
              const runningJob = activeStates.has(job.status);
              return (
                <article className={`organizer-job-row status-${job.status}`} key={job.id}>
                  <span className="organizer-job-state">{runningJob ? <CircleNotch className="spin" /> : job.status === "done" ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}</span>
                  <div>
                    <strong>{job.display_title || job.source_file || "云下载目录整理"}</strong>
                    <span>{providerLabel(job.provider === "p115" ? "p115" : "quark")} · 任务 #{job.id} · {jobStageLabel(job.stage)}</span>
                    <p>{job.message || "等待状态更新"}</p>
                    {(job.source_file || job.save_path) && <small>{job.source_file || "已选来源目录"}<ArrowRight />{job.save_path || "目标路径待核对"}</small>}
                  </div>
                  <em>{statusLabel(job.status)}</em>
                </article>
              );
            })}
          </div>
        )}
        <div className="settings-action-strip"><button type="button" className="ghost compact-action" onClick={onOpenTasks}>打开任务中心查看全部详情</button></div>
      </OrganizerSection>

      <OrganizerSection title="使用指引与安全边界" body="云下载目录负责接收文件，正式媒体库负责保存核对、命名后的结果。">
        <div className="organizer-guide">
          <ol>
            <li><strong>配置网盘与两类根目录</strong><p>先在“夸克规则”或“115 规则”中连接网盘，设置正式媒体库根和云下载根。建议云下载根使用独立目录，例如 <code>/媒体库/下载文件夹</code>。</p></li>
            <li><strong>按正式媒体库同名建立一级子目录</strong><p>在云下载根下建立 <code>01电影</code>、<code>03电视剧</code> 等直接子目录。MediaIndex 固定按同名一一映射，不接受浏览器提交任意目标绝对路径。已选分类下既可放独立媒体目录，也可直接放标题可识别的媒体文件。</p></li>
            <li><strong>只勾选需要自动整理的范围</strong><p>未勾选目录和云下载根本身的散落文件不会扫描；更深层目录不能被单独授权，但已选分类下的媒体目录会按整理单元递归读取。目录读取失败会明确报错，不会退化为“目录为空”。</p></li>
            <li><strong>等待稳定并核对 TMDB</strong><p>内容稳定达到设定时间后，MediaIndex 核对 TMDB 身份，再继承“通用规则”的媒体文件夹、标准文件名和季度文件夹模板。证据不足、重名或目标冲突会进入待确认。</p></li>
            <li><strong>安全重试并联动入库</strong><p>异常重启或重试会先按已保存计划重新核验目标，复用已经唯一匹配的结果，不重复写入。目标完整核验成功后才进入既有后处理流程：按各自开关与范围生成 STRM、刷新媒体库并发送通知。</p></li>
          </ol>
          <div className="organizer-mode-guide">
            <article><strong>复制模式</strong><p>将核对后的媒体复制到正式媒体库，云下载来源目录和文件保持不动。适合先观察规则或保留下载副本。</p></article>
            <article className="move"><strong>移动模式</strong><p>所有目标名称和大小逐项唯一核验后，再与持久化文件 ID 回执对账，只按文件 ID 精确清理当时再次确认仍在源媒体目录内的残留普通文件，并轮询确认回收站结果；绝不回收整个源媒体文件夹。直接放在分类下的文件只移动当前安全分组的计划文件，不清理同级其他文件。同 stem 字幕与 NFO 会随媒体规范命名并转移；发现新到达文件、疑似视频、身份变化、TMDB 歧义、命名冲突或任一步失败时，会停止残留清理并提示核对；授权范围或根目录变更也会立即停止。</p></article>
          </div>
          <div className="organizer-example-flow" aria-label="目录映射示例">
            <code>/媒体库/下载文件夹/01电影/待整理资源</code><ArrowRight /><code>/媒体库/01电影/标准媒体目录/标准文件名</code>
            <code>/媒体库/下载文件夹/01电影/片名.2026.mkv</code><ArrowRight /><code>/媒体库/01电影/片名 (2026)/片名.2026.mkv</code>
          </div>
        </div>
      </OrganizerSection>

      <div className="settings-footer organizer-footer">
        <span>{dirty ? "当前有尚未保存的云下载整理修改" : "云下载整理规则已与服务端同步"}</span>
        <button type="button" className="primary compact-action" disabled={!dirty || saving || Boolean(running)} onClick={() => void save()}>
          {saving && <CircleNotch className="spin" />}{saving ? "保存中" : "保存云下载整理规则"}
        </button>
      </div>
    </section>
  );
}

function MappingPreview({ provider, source, target, stale = false }: { provider: Provider; source: string; target: string; stale?: boolean }) {
  return (
    <div className={`organizer-mapping-preview ${stale ? "stale" : ""}`}>
      <span>{providerIcon(provider)}<code>{source}</code></span><ArrowRight /><span><FolderOpen /><code>{target}</code></span>
    </div>
  );
}
