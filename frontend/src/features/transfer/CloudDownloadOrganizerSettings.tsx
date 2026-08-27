import {
  ArrowRight,
  CheckCircle,
  CircleNotch,
  Cloud,
  FolderOpen,
  HardDrives,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError, type CloudDownloadOrganizerMode, type ConfigStatus, type TransferJob } from "../../lib/api";
import { ProviderDirectoryPicker } from "../../components/DirectoryPickers";
import "./cloud-download-organizer.css";

type Provider = "quark" | "p115";
type ResultMessage = { ok: boolean; text: string } | null;

function DirectoryField({ label, value, placeholder, help, onChange, onPick }: { label: string; value: string; placeholder: string; help: string; onChange: (value: string) => void; onPick: () => void }) {
  return <div className="settings-field"><span className="settings-label">{label}<small className="settings-field-help">{help}</small></span><div className="settings-input-content"><div className="settings-input-action"><div className="settings-plain-input"><input aria-label={label} type="text" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></div><button type="button" className="ghost compact-action" onClick={onPick}>选择目录</button></div></div></div>;
}
type DirectoryOption = { name: string; path: string };
type PickerState = { provider: Provider; field: "library" | "download" } | null;

const providers: Provider[] = ["quark", "p115"];
const activeStates = new Set<TransferJob["status"]>(["ready", "running", "triggered", "retry_wait"]);

function OrganizerSection({ title, body, children }: { title: string; body: string; children: ReactNode }) {
  return <section className="settings-section organizer-settings-section"><header><strong>{title}</strong><span>{body}</span></header><div className="settings-section-body">{children}</div></section>;
}

function providerLabel(provider: Provider) { return provider === "p115" ? "115" : "夸克"; }
function providerIcon(provider: Provider) { return provider === "p115" ? <HardDrives size={21} /> : <Cloud size={21} />; }
function normalizePath(value: string) {
  const normalized = String(value || "").trim().replace(/\\/g, "/").replace(/\/{2,}/g, "/");
  if (!normalized || normalized === "/") return "/";
  return `/${normalized.replace(/^\/+|\/+$/g, "")}`;
}
function childPath(root: string, name: string) { const base = normalizePath(root); return `${base === "/" ? "" : base}/${name}`; }
function leafName(path: string) { const parts = normalizePath(path).split("/").filter(Boolean); return parts.at(-1) || ""; }
function sameStringSet(left: string[], right: string[]) { return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort()); }
function requestError(error: unknown, fallback: string) { return error instanceof ApiError || error instanceof Error ? error.message : fallback; }

function statusLabel(status: TransferJob["status"]) {
  return ({ ready: "等待执行", running: "正在整理", triggered: "等待网盘", retry_wait: "等待重试", needs_review: "待确认", done: "已完成", failed: "失败", stopped: "已终止" } as Record<TransferJob["status"], string>)[status];
}

function jobStageLabel(stage: string) {
  return ({ organizer_tmdb_resolving: "TMDB 信息核对", organizer_transferring: "网盘内转存", organizer_post_processing: "定点生成 STRM 并通知入库", organizer_completed: "整理完成", organizer_failed: "整理失败", organizer_needs_review: "等待人工确认", organizer_recovering: "核验并续作精确目标", organizer_stopped: "用户已停止整理" } as Record<string, string>)[stage] || stage || "等待处理";
}

export function CloudDownloadOrganizerSettings({ onOpenTasks }: { onOpenTasks: () => void }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [configError, setConfigError] = useState("");
  const [enabled, setEnabled] = useState<Record<Provider, boolean>>({ quark: false, p115: false });
  const [mode, setMode] = useState<CloudDownloadOrganizerMode>("copy");
  const [libraryRoots, setLibraryRoots] = useState<Record<Provider, string>>({ quark: "", p115: "" });
  const [downloadRoots, setDownloadRoots] = useState<Record<Provider, string>>({ quark: "", p115: "" });
  const [selectedDirectories, setSelectedDirectories] = useState<Record<Provider, string[]>>({ quark: [], p115: [] });
  const [directoryOptions, setDirectoryOptions] = useState<Record<Provider, DirectoryOption[]>>({ quark: [], p115: [] });
  const [directoryLoaded, setDirectoryLoaded] = useState<Record<Provider, boolean>>({ quark: false, p115: false });
  const [directoryLoading, setDirectoryLoading] = useState<Provider | "">("");
  const [directoryErrors, setDirectoryErrors] = useState<Record<Provider, string>>({ quark: "", p115: "" });
  const [picker, setPicker] = useState<PickerState>(null);
  const [jobs, setJobs] = useState<TransferJob[]>([]);
  const [jobsError, setJobsError] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<ResultMessage>(null);

  function applyConfig(next: ConfigStatus) {
    setConfig(next);
    setEnabled({ quark: next.quark_cloud_download_organizer_enabled, p115: next.p115_cloud_download_organizer_enabled });
    setMode(next.cloud_download_organizer_mode);
    setLibraryRoots({ quark: next.quark_root_path, p115: next.p115_root_path });
    setDownloadRoots({ quark: next.quark_cloud_download_path, p115: next.p115_cloud_download_path });
    setSelectedDirectories({ quark: [...(next.quark_cloud_download_organizer_directories || [])], p115: [...(next.p115_cloud_download_organizer_directories || [])] });
  }

  async function loadConfig() {
    setConfigError("");
    try { applyConfig(await api.config()); } catch (error) { setConfigError(requestError(error, "云下载整理配置读取失败")); }
  }
  async function loadJobs() {
    try { setJobs(await api.transfers()); setJobsError(""); } catch (error) { setJobsError(requestError(error, "整理任务状态读取失败")); }
  }

  useEffect(() => {
    void loadConfig(); void loadJobs();
    const timer = window.setInterval(() => void loadJobs(), 5_000);
    return () => window.clearInterval(timer);
  }, []);

  const organizerJobs = useMemo(() => jobs.filter((job) => job.request_source === "cloud_download_organizer").slice(0, 6), [jobs]);
  const activeJobs = organizerJobs.filter((job) => activeStates.has(job.status));
  const dirty = Boolean(config) && (providers.some((provider) => (
    enabled[provider] !== (provider === "p115" ? config?.p115_cloud_download_organizer_enabled : config?.quark_cloud_download_organizer_enabled)
    || libraryRoots[provider] !== (provider === "p115" ? config?.p115_root_path : config?.quark_root_path)
    || downloadRoots[provider] !== (provider === "p115" ? config?.p115_cloud_download_path : config?.quark_cloud_download_path)
    || !sameStringSet(selectedDirectories[provider], (provider === "p115" ? config?.p115_cloud_download_organizer_directories : config?.quark_cloud_download_organizer_directories) || [])
  )) || mode !== config?.cloud_download_organizer_mode);

  function connected(provider: Provider) { return provider === "p115" ? Boolean(config?.has_p115_cookie) : Boolean(config?.has_quark_cookie); }
  function mappedTarget(provider: Provider, source: string) { return childPath(libraryRoots[provider], leafName(source)); }

  async function loadProviderDirectories(provider: Provider) {
    const root = downloadRoots[provider];
    if (!root) return;
    setDirectoryLoading(provider); setDirectoryErrors((current) => ({ ...current, [provider]: "" }));
    try {
      const result = await api.browseProviderPath(provider, root, true);
      setDirectoryOptions((current) => ({ ...current, [provider]: result.directories.filter((item) => item.is_dir).map((item) => ({ name: item.name, path: childPath(result.path, item.name) })) }));
      setDirectoryLoaded((current) => ({ ...current, [provider]: true }));
    } catch (error) {
      setDirectoryErrors((current) => ({ ...current, [provider]: requestError(error, `${providerLabel(provider)}一级子目录读取失败`) }));
      setDirectoryLoaded((current) => ({ ...current, [provider]: false }));
    } finally { setDirectoryLoading(""); }
  }

  function updateDownloadRoot(provider: Provider, value: string) {
    setDownloadRoots((current) => ({ ...current, [provider]: value }));
    setSelectedDirectories((current) => ({ ...current, [provider]: [] }));
    setDirectoryLoaded((current) => ({ ...current, [provider]: false }));
    setDirectoryOptions((current) => ({ ...current, [provider]: [] }));
  }

  async function save() {
    if (!config) return;
    for (const provider of providers) {
      if (enabled[provider] && selectedDirectories[provider].length === 0) {
        setMessage({ ok: false, text: `开启${providerLabel(provider)}监控前，请至少勾选一个云下载一级子目录。` });
        return;
      }
    }
    setSaving(true); setMessage(null);
    try {
      await api.saveConfig({
        p115_cloud_download_organizer_enabled: enabled.p115,
        quark_cloud_download_organizer_enabled: enabled.quark,
        cloud_download_organizer_mode: mode,
        p115_root_path: libraryRoots.p115,
        quark_root_path: libraryRoots.quark,
        p115_cloud_download_path: downloadRoots.p115,
        quark_cloud_download_path: downloadRoots.quark,
        p115_cloud_download_organizer_directories: selectedDirectories.p115,
        quark_cloud_download_organizer_directories: selectedDirectories.quark,
      });
      applyConfig(await api.config());
      setMessage({ ok: true, text: "云下载整理设置已保存；之后仅由 MediaIndex 已完成的精确转存事件触发。" });
    } catch (error) { setMessage({ ok: false, text: requestError(error, "云下载整理设置保存失败") }); }
    finally { setSaving(false); }
  }

  if (!config) {
    if (configError) return <div className="organizer-load-state error" role="alert"><WarningCircle size={28} /><div><strong>无法读取云下载整理配置</strong><span>{configError}</span></div><button type="button" className="ghost compact-action" onClick={() => void loadConfig()}>重试</button></div>;
    return <div className="workspace-loading"><CircleNotch className="spin" />正在读取云下载整理设置</div>;
  }

  const enabledProviders = providers.filter((provider) => enabled[provider]);
  const ready = enabledProviders.length > 0 && enabledProviders.every((provider) => connected(provider) && selectedDirectories[provider].length > 0) && config.has_tmdb_key;
  const overview = enabledProviders.length === 0
    ? { className: "off", title: "云下载整理已关闭", body: "两个网盘都不会启动监控或整理。" }
    : activeJobs.length
      ? { className: "running", title: `${activeJobs.length} 个定点整理任务正在执行`, body: activeJobs[0]?.message || "正在核验精确目标" }
      : ready
        ? { className: "ready", title: "事件驱动整理已就绪", body: "只响应 MediaIndex 前序转存完成事件，不轮询网盘目录。" }
        : { className: "warning", title: "设置尚未就绪", body: "请检查已开启网盘的连接、TMDB 和子目录勾选。" };

  return <section className="cloud-download-organizer workspace-section">
    <header className="portal-section-head"><div><h2>云下载整理</h2><p>接收 MediaIndex 已完成的转存目标，定点核验、规范命名、转存并生成 STRM。</p></div></header>
    <div className={`organizer-overview ${overview.className}`} aria-live="polite"><div className="organizer-overview-icon">{overview.className === "running" ? <CircleNotch className="spin" /> : overview.className === "ready" ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}</div><div><strong>{overview.title}</strong><span>{overview.body}</span></div><div className="organizer-overview-actions"><button type="button" className="ghost compact-action" onClick={onOpenTasks}>查看任务中心</button></div></div>
    {message && <div className={`settings-inline-result organizer-message ${message.ok ? "success" : "error"}`} role="status">{message.text}</div>}

    <OrganizerSection title="整理方式" body="没有分钟级扫描，也没有手动全量整理入口。前序动作完成后才处理该媒体。">
      <div className="settings-field"><span>触发方式<small className="settings-field-help">MediaIndex 根据本次转存的文件 ID、目标目录和文件名定点核验；不会遍历其他媒体或兄弟目录。</small></span><strong>前序动作事件</strong></div>
      <div className="settings-field"><span>转存模式<small className="settings-field-help">复制保留来源；移动只在目标逐项核验成功后，按持久化文件 ID 清理本次来源残留。</small></span><div className="toggle-group organizer-mode-toggle" role="group" aria-label="云下载整理转存模式"><button type="button" className={mode === "copy" ? "active" : ""} onClick={() => setMode("copy")}>复制</button><button type="button" className={mode === "move" ? "active" : ""} onClick={() => setMode("move")}>移动</button></div></div>
    </OrganizerSection>

    <div className="organizer-provider-grid">
      {providers.map((provider) => {
        const label = providerLabel(provider); const selected = selectedDirectories[provider]; const options = directoryOptions[provider]; const isConnected = connected(provider);
        return <article className="settings-section organizer-provider-card" key={provider}>
          <header><div className="organizer-provider-title">{providerIcon(provider)}<div><strong>{label} 云下载</strong><span>独立开关、独立根目录与授权范围</span></div></div><button type="button" role="switch" aria-checked={enabled[provider]} className={`organizer-provider-switch ${enabled[provider] ? "active" : ""}`} onClick={() => setEnabled((current) => ({ ...current, [provider]: !current[provider] }))}>{enabled[provider] ? "已开启" : "已关闭"}</button></header>
          <div className="settings-section-body organizer-provider-body">
            <div className={`organizer-provider-state ${isConnected ? "success" : "warning"}`}>{isConnected ? <CheckCircle weight="fill" /> : <WarningCircle />}{isConnected ? `${label}已连接` : `${label}未连接`}</div>
            <DirectoryField label="正式媒体库根目录" value={libraryRoots[provider]} placeholder="/媒体库" onChange={(value) => setLibraryRoots((current) => ({ ...current, [provider]: value }))} help="整理目标固定为该根目录下与云下载一级子目录同名的分类目录。" onPick={() => setPicker({ provider, field: "library" })} />
            <DirectoryField label="云下载根目录" value={downloadRoots[provider]} placeholder={`${libraryRoots[provider]}/下载文件夹`} onChange={(value) => updateDownloadRoot(provider, value)} help="只允许选择这个根目录下的直接子目录作为整理入口。" onPick={() => setPicker({ provider, field: "download" })} />
            <div className="organizer-provider-actions"><button type="button" className="ghost compact-action" disabled={!isConnected || !downloadRoots[provider] || Boolean(directoryLoading)} onClick={() => void loadProviderDirectories(provider)}>{directoryLoading === provider ? <CircleNotch className="spin" /> : <FolderOpen />}{directoryLoading === provider ? "读取中" : "读取一级子目录"}</button></div>
            {directoryErrors[provider] && <div className="organizer-provider-state error" role="alert"><WarningCircle />{directoryErrors[provider]}</div>}
            {!directoryLoaded[provider] && selected.length === 0 && <div className="organizer-directory-empty"><FolderOpen size={27} /><strong>尚未选择整理范围</strong><span>读取云下载根的一级子目录后勾选；不会默认授权整个根目录。</span></div>}
            {!directoryLoaded[provider] && selected.length > 0 && <div className="organizer-saved-mappings"><strong>已保存的整理范围</strong>{selected.map((path) => <MappingPreview key={path} provider={provider} source={path} target={mappedTarget(provider, path)} />)}</div>}
            {directoryLoaded[provider] && <div className="organizer-directory-scope"><div className="organizer-directory-scope-head"><div><strong>选择整理范围</strong><span>{selected.length} / {options.length} 个已勾选</span></div><div><button type="button" onClick={() => setSelectedDirectories((current) => ({ ...current, [provider]: options.map((item) => item.path) }))}>全选</button><button type="button" onClick={() => setSelectedDirectories((current) => ({ ...current, [provider]: [] }))}>清空</button></div></div><div className="organizer-directory-list">{options.map((option) => <label className={selected.includes(option.path) ? "selected" : ""} key={option.path}><input type="checkbox" checked={selected.includes(option.path)} onChange={(event) => setSelectedDirectories((current) => ({ ...current, [provider]: event.target.checked ? Array.from(new Set([...current[provider], option.path])) : current[provider].filter((item) => item !== option.path) }))} /><FolderOpen size={18} /><span><strong>{option.name}</strong><small><code>{option.path}</code><ArrowRight /><code>{mappedTarget(provider, option.path)}</code></small></span></label>)}</div></div>}
          </div>
        </article>;
      })}
    </div>

    <OrganizerSection title="最近整理状态" body="这里只展示由精确转存事件创建的媒体任务；状态读取来自本地数据库，不访问网盘。">
      {jobsError && <div className="organizer-provider-state error" role="alert"><WarningCircle />{jobsError}</div>}
      {!jobsError && organizerJobs.length === 0 && <div className="organizer-job-empty"><FolderOpen size={28} /><strong>还没有定点整理任务</strong><span>开启对应网盘后，下一次 MediaIndex 转存完成会自动触发。</span></div>}
      {!jobsError && organizerJobs.length > 0 && <div className="organizer-job-list">{organizerJobs.map((job) => <article className={`organizer-job-row status-${job.status}`} key={job.id}><span className="organizer-job-state">{activeStates.has(job.status) ? <CircleNotch className="spin" /> : job.status === "done" ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}</span><div><strong>{job.display_title || job.source_file || "云下载媒体整理"}</strong><span>{providerLabel(job.provider === "p115" ? "p115" : "quark")} · 任务 #{job.id} · {jobStageLabel(job.stage)}</span><p>{job.message || "等待状态更新"}</p>{(job.source_file || job.save_path) && <small>{job.source_file || "精确来源"}<ArrowRight />{job.save_path || "目标路径待核对"}</small>}</div><em>{statusLabel(job.status)}</em></article>)}</div>}
    </OrganizerSection>

    <OrganizerSection title="使用指引与安全边界" body="目录只负责授权和固定映射；真正的触发依据是 MediaIndex 已完成的前序动作。">
      <div className="organizer-guide"><ol>
        <li><strong>分别开启需要使用的网盘</strong><p>115 和夸克互不影响。关闭某个网盘后，它不会接收新的定点整理事件，另一网盘仍可继续工作。</p></li>
        <li><strong>设置两类根目录</strong><p>例如云下载根 <code>/媒体库/下载文件夹</code>，正式媒体库根 <code>/媒体库</code>。在云下载根勾选 <code>01电影</code> 后，目标固定映射到正式媒体库的 <code>/媒体库/01电影</code>。</p></li>
        <li><strong>由前序转存精确触发</strong><p>MediaIndex 转存完成后携带本次文件 ID、目录和名称，只核验该媒体；不会每隔几分钟读取整个云下载根，也不会触碰未勾选目录。</p></li>
        <li><strong>核对并规范整理</strong><p>系统使用 TMDB 核对媒体身份，继承“转存和整理规则”的目录、文件和季度命名模板。歧义、重名或目标冲突进入人工复核。</p></li>
        <li><strong>定点联动入库</strong><p>目标逐项确认后，只为本次精确文件生成或更新 STRM，再按既有开关通知 Emby 与发送入库通知。任何步骤都不会回退成全量或增量扫描。</p></li>
      </ol><div className="organizer-mode-guide"><article><strong>复制模式</strong><p>目标核验后保留云下载来源，适合先观察规则。</p></article><article className="move"><strong>移动模式</strong><p>只按本次持久化文件 ID 清理已确认的来源残留；发现新文件、身份变化或冲突立即停止清理。</p></article></div><div className="organizer-example-flow"><code>/媒体库/下载文件夹/01电影/资源目录</code><ArrowRight /><code>/媒体库/01电影/片名 (年份)/标准文件名</code></div></div>
    </OrganizerSection>

    <div className="settings-footer organizer-footer"><span>{dirty ? "当前有尚未保存的云下载整理修改" : "云下载整理设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={!dirty || saving} onClick={() => void save()}>{saving && <CircleNotch className="spin" />}{saving ? "保存中" : "保存云下载整理设置"}</button></div>
    {picker && <ProviderDirectoryPicker provider={picker.provider} label={`${providerLabel(picker.provider)}${picker.field === "library" ? "正式媒体库根目录" : "云下载根目录"}`} startPath={(picker.field === "library" ? libraryRoots : downloadRoots)[picker.provider] || "/"} onClose={() => setPicker(null)} onSelect={(path) => { if (picker.field === "library") setLibraryRoots((current) => ({ ...current, [picker.provider]: path })); else updateDownloadRoot(picker.provider, path); setPicker(null); }} />}
  </section>;
}

function MappingPreview({ provider, source, target }: { provider: Provider; source: string; target: string }) {
  return <div className="organizer-mapping-preview"><span>{providerIcon(provider)}<code>{source}</code></span><ArrowRight /><span><FolderOpen /><code>{target}</code></span></div>;
}
