import { ArrowClockwise, CheckCircle, CircleNotch, Cloud, FileVideo, FolderOpen, HardDrives, PlayCircle, ShieldCheck, Trash, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { AppRoute } from "../../app/routes";
import { api, ApiError, ConfigStatus } from "../../lib/api";
import { SettingsInput, SettingsToggle } from "../settings/SettingsFormParts";
import { LocalDirectoryPicker, ProviderDirectoryPicker } from "../../components/DirectoryPickers";

const sections = [
  { key: "emby", label: "STRM 通用设置", icon: PlayCircle },
  { key: "p115", label: "115 STRM", icon: HardDrives },
  { key: "quark", label: "夸克 STRM", icon: Cloud },
] as const;

type RefreshData = { config: ConfigStatus };

export function StrmPortal({ route, onNavigate }: { route: AppRoute; onNavigate: (route: AppRoute) => void }) {
  const [data, setData] = useState<RefreshData | null>(null);
  const [error, setError] = useState("");
  const section = route.section === "deletion" ? "p115" : route.section || "emby";
  async function refresh() {
    const config = await api.config();
    setData({ config });
  }
  useEffect(() => { void refresh().catch((reason: Error) => setError(reason.message || "STRM 配置读取失败")); }, []);

  return <section className="strm-portal">
    <div className="page-head workspace-portal-head"><div><p className="eyebrow">LIBRARY PLAYBACK</p><h1>STRM 与 302</h1><p>统一配置播放入口和媒体服务器，再分别管理 115 与夸克的 STRM 扫描生成。</p></div></div>
    <nav className="portal-subnav" aria-label="STRM 与 302 模块">{sections.map(({ key, label, icon: Icon }) => <button type="button" key={key} className={section === key ? "active" : ""} onClick={() => onNavigate({ page: "strm", section: key === "emby" ? undefined : key })}><Icon size={18} />{label}</button>)}</nav>
    {error && <p className="workspace-message">{error}</p>}
    {!data ? <div className="workspace-loading"><CircleNotch className="spin" />正在读取媒体库状态</div> : <>
      {section === "emby" && <EmbyConnectionPage config={data.config} onChanged={refresh} />}
      {section === "p115" && <DriveStrmPage provider="p115" config={data.config} onChanged={refresh} />}
      {section === "quark" && <DriveStrmPage provider="quark" config={data.config} onChanged={refresh} />}
    </>}
  </section>;
}

function EmbyConnectionPage({ config, onChanged }: { config: ConfigStatus; onChanged: () => Promise<void> }) {
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [playbackBaseUrl, setPlaybackBaseUrl] = useState(config.strm_playback_base_url || "");
  const [embyRefreshEnabled, setEmbyRefreshEnabled] = useState(config.emby_library_refresh_enabled);
  const [busy, setBusy] = useState<"save" | "test" | "">("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const configured = Boolean(config.emby_base_url && config.has_emby_api_key);
  async function savePage() {
    setBusy("save"); setResult(null);
    try {
      const payload: Record<string, string | number | boolean> = { emby_library_refresh_enabled: embyRefreshEnabled, strm_playback_base_url: playbackBaseUrl.trim() };
      if (url.trim()) payload.emby_base_url = url.trim();
      if (apiKey.trim()) payload.emby_api_key = apiKey.trim();
      await api.saveConfig(payload);
      setUrl(""); setApiKey(""); await onChanged();
      setResult({ ok: true, message: "Emby 连接与入库刷新规则已保存。" });
    } catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "Emby 设置保存失败" }); }
    finally { setBusy(""); }
  }
  async function test() {
    setBusy("test"); setResult(null);
    try { setResult(await api.testEmby()); }
    catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "Emby 连接测试失败" }); }
    finally { setBusy(""); }
  }
  const hasEmbyUrl = Boolean(url.trim() || config.emby_base_url);
  const dirty = Boolean(url.trim() || apiKey.trim() || playbackBaseUrl.trim() !== (config.strm_playback_base_url || "") || embyRefreshEnabled !== config.emby_library_refresh_enabled);
  const configuredPlaybackAddress = playbackBaseUrl.trim() || config.strm_playback_base_url || "未配置（宿主机端口不是 8097 时必须填写）";
  return <section className="workspace-section strm-config-page">
    <header className="portal-section-head"><div><h2>STRM 通用设置</h2><p>统一管理 302 的内外网入口、STRM 写入地址和 Emby 自动入库。</p></div><span className={`connection-pill ${configured ? "connected" : ""}`}>{configured ? <CheckCircle weight="fill" /> : <WarningCircle />}{configured ? "Emby 已连接" : "Emby 未连接"}</span></header>
    <div className="strm-accordion-list">
      <details open><summary><span>302 播放地址</span><small>容器监听端口与 STRM 实际播放入口</small></summary><div className="accordion-content settings-stack">
        <label className="settings-field"><span>容器内部监听端口</span><input value="8097" disabled aria-label="容器内部监听端口" /><small className="settings-field-help">固定为 8097。NAS 播放端口只在 Compose 的 ports 左侧设置，例如 28947:8097；MediaIndex 不读取也不修改宿主机端口。</small></label>
        <SettingsInput label="STRM 播放地址" name="strm_playback_base_url" value={playbackBaseUrl} saved={Boolean(config.strm_playback_base_url)} placeholder="https://tvb302.example.com:666" onChange={(_name, value) => setPlaybackBaseUrl(value)} helpTooltip="写入 STRM 文件的完整播放入口。宿主机端口不是 8097 时必须填写，可使用反向代理域名。" />
        <div className="strm-playback-examples"><div><span>Compose 端口映射示例</span><code>28947:8097</code></div><div><span>STRM 实际写入地址</span><code>{configuredPlaybackAddress}</code></div></div>
      </div></details>
      <details open><summary><span>Emby 服务器</span><small>连接、媒体库刷新与入库规则</small></summary><div className="accordion-content settings-stack">
        <SettingsInput label="Emby 内网地址（必填）" name="emby_base_url" value={url} saved={Boolean(config.emby_base_url)} placeholder={config.emby_base_url || "http://192.168.1.100:8096"} showSavedValue onChange={(_name, value) => setUrl(value)} helpTooltip="MediaIndex 与 302 服务连接真实 Emby 的内网地址。" />
        <SettingsInput label="Emby API Key" name="emby_api_key" value={apiKey} saved={config.has_emby_api_key} secret onChange={(_name, value) => setApiKey(value)} />
        <SettingsToggle label="STRM 完成后刷新 Emby 媒体库" help="启用后，STRM 新增或更新会调用 Emby 刷新；媒体资料匹配由 Emby 处理。" value={embyRefreshEnabled} onChange={setEmbyRefreshEnabled} trueLabel="已开启" falseLabel="已关闭" />
        <div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy !== "" || !configured} onClick={() => void test()}>{busy === "test" ? <CircleNotch className="spin" /> : <ShieldCheck />}测试连接</button></div>
      </div></details>
    </div>
    {result && <div className="strm-page-actions"><span className={result.ok ? "success-text" : "error-text"}>{result.message}</span></div>}
    <div className="settings-footer"><span>{!hasEmbyUrl ? "请先填写 Emby 内网地址" : dirty ? "当前有尚未保存的 Emby 设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || !dirty || !hasEmbyUrl} onClick={() => void savePage()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
  </section>;
}

function DriveStrmPage({ provider, config, onChanged }: { provider: "p115" | "quark"; config: ConfigStatus; onChanged: () => Promise<void> }) {
  const label = provider === "p115" ? "115" : "夸克";
  const connected = provider === "p115" ? config.has_p115_cookie : config.has_quark_cookie;
  const [root, setRoot] = useState(provider === "p115" ? config.p115_strm_source_root : config.quark_strm_source_root);
  const [includedDirectories, setIncludedDirectories] = useState<string[]>(() => (provider === "p115" ? config.p115_strm_included_directories : config.quark_strm_included_directories) || []);
  const [sourceDirectories, setSourceDirectories] = useState<{ name: string; path: string }[]>([]);
  const [sourceDirectoriesLoaded, setSourceDirectoriesLoaded] = useState(false);
  const [sourceDirectoriesBusy, setSourceDirectoriesBusy] = useState(false);
  const [outputRoot, setOutputRoot] = useState(config.strm_output_root || "");
  const [enabled, setEnabled] = useState(provider === "p115" ? config.p115_strm_enabled : config.quark_strm_enabled);
  const [extensions, setExtensions] = useState(config.strm_video_extensions.join(", "));
  const [excludedTokens, setExcludedTokens] = useState(config.strm_excluded_name_tokens.join(", "));
  const [minSizeMb, setMinSizeMb] = useState(String(config.strm_min_file_size_mb));
  const [incrementalCron, setIncrementalCron] = useState(provider === "p115" ? config.p115_strm_incremental_cron : config.quark_strm_incremental_cron);
  const [lifeMonitorEnabled, setLifeMonitorEnabled] = useState(provider === "p115" ? config.p115_strm_life_monitor_enabled : false);
  const [lifeMonitorPath, setLifeMonitorPath] = useState(provider === "p115" ? config.p115_strm_life_monitor_path : "");
  const [lifeMonitorInterval, setLifeMonitorInterval] = useState(String(provider === "p115" ? config.p115_strm_life_monitor_interval_seconds : 60));
  const [pickerOpen, setPickerOpen] = useState(false);
  const [lifeMonitorPickerOpen, setLifeMonitorPickerOpen] = useState(false);
  const [outputPickerOpen, setOutputPickerOpen] = useState(false);
  const [busy, setBusy] = useState<"incremental" | "full" | "save" | "">("");
  const [message, setMessage] = useState("");
  async function reconcile(mode: "incremental" | "full") {
    setBusy(mode); setMessage("");
    try {
      if (!includedDirectories.length) throw new Error("请先勾选至少一个扫描子目录，MediaIndex 不会默认扫描整个网盘");
      await saveSettings();
      const result = await api.startStrmJob({
        provider,
        mode,
        root_path: root.trim(),
        output_root: outputRoot.trim(),
        include_directories: includedDirectories,
        playback_base_url: config.strm_playback_base_url || undefined,
      });
      setMessage(`扫描已开始（任务 #${result.job_id}），请到右上角日志窗口查看详情。`);
      window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) { setMessage(error instanceof Error ? error.message : "STRM 生成失败"); }
    finally { setBusy(""); }
  }
  function rangePayload() {
    return {
      strm_video_extensions: extensions.split(",").map((value) => value.trim()).filter(Boolean),
      strm_excluded_name_tokens: excludedTokens.split(",").map((value) => value.trim()).filter(Boolean),
      strm_min_file_size_mb: Number(minSizeMb || "0"),
    };
  }
  async function saveSettings() {
    await api.saveConfig({
      [provider === "p115" ? "p115_strm_source_root" : "quark_strm_source_root"]: root.trim(), strm_output_root: outputRoot.trim(),
      [provider === "p115" ? "p115_strm_included_directories" : "quark_strm_included_directories"]: includedDirectories,
      [`${provider}_strm_incremental_cron`]: incrementalCron.trim(),
      [`${provider}_strm_enabled`]: enabled, ...rangePayload(),
      ...(provider === "p115" ? { p115_strm_life_monitor_enabled: lifeMonitorEnabled, p115_strm_life_monitor_path: lifeMonitorPath.trim(), p115_strm_life_monitor_interval_seconds: Number(lifeMonitorInterval || "60") } : {}),
    });
  }
  function changeRoot(value: string) {
    setRoot(value);
    setIncludedDirectories([]);
    setSourceDirectories([]);
    setSourceDirectoriesLoaded(false);
  }
  async function loadSourceDirectories() {
    if (!root.trim()) return;
    setSourceDirectoriesBusy(true);
    try {
      const result = await api.browseProviderPath(provider, root.trim());
      const base = result.path === "/" ? "" : result.path.replace(/\/$/, "");
      setSourceDirectories(result.directories.filter((item) => item.is_dir).map((item) => ({ name: item.name, path: `${base}/${item.name}` })));
      setSourceDirectoriesLoaded(true);
    } catch (error) { setMessage(error instanceof Error ? error.message : "读取来源子目录失败"); }
    finally { setSourceDirectoriesBusy(false); }
  }
  function toggleIncludedDirectory(path: string, checked: boolean) {
    setIncludedDirectories((current) => checked ? [...current, path] : current.filter((value) => value !== path));
  }
  async function savePage() {
    setBusy("save"); setMessage("");
    try {
      await saveSettings();
      setMessage(`${label} STRM 来源、自动生成与文件范围已保存。`);
      await onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "STRM 规则保存失败"); }
    finally { setBusy(""); }
  }
  const savedRoot = provider === "p115" ? config.p115_strm_source_root : config.quark_strm_source_root;
  const savedIncludedDirectories = (provider === "p115" ? config.p115_strm_included_directories : config.quark_strm_included_directories) || [];
  const savedEnabled = provider === "p115" ? config.p115_strm_enabled : config.quark_strm_enabled;
  const savedCron = provider === "p115" ? config.p115_strm_incremental_cron : config.quark_strm_incremental_cron;
  const dirty = root.trim() !== (savedRoot || "") || JSON.stringify([...includedDirectories].sort()) !== JSON.stringify([...(savedIncludedDirectories || [])].sort()) || outputRoot.trim() !== (config.strm_output_root || "") || enabled !== savedEnabled || incrementalCron.trim() !== (savedCron || "") || extensions !== config.strm_video_extensions.join(", ") || excludedTokens !== config.strm_excluded_name_tokens.join(", ") || minSizeMb !== String(config.strm_min_file_size_mb) || (provider === "p115" && (lifeMonitorEnabled !== config.p115_strm_life_monitor_enabled || lifeMonitorPath.trim() !== (config.p115_strm_life_monitor_path || "") || lifeMonitorInterval !== String(config.p115_strm_life_monitor_interval_seconds)));
  return <section className="workspace-section strm-config-page">
    <header className="portal-section-head"><div><h2>{label} STRM</h2><p>管理 {label} 来源目录、全量/增量扫描和 STRM 文件范围。</p></div><span className={`connection-pill ${connected ? "connected" : ""}`}>{connected ? <CheckCircle weight="fill" /> : <WarningCircle />}{connected ? `${label} 已连接` : `${label} 未连接`}</span></header>
    {message && <div className="notice page-notice">{message}</div>}
    <div className="strm-accordion-list">
      <details open><summary><span>来源目录</span><small>独立于网盘工作台的转存保存规则</small></summary><div className="accordion-content settings-stack"><SettingsInput label={`${label} STRM 来源目录`} name={`${provider}_strm_source_root`} value={root} saved={Boolean(savedRoot)} placeholder="/媒体库" onChange={(_name, value) => changeRoot(value)} showSavedValue action={<button type="button" className="ghost compact-action" disabled={busy !== "" || !connected} onClick={() => setPickerOpen(true)}><FolderOpen />浏览</button>} /><div className="strm-source-folder-selection"><div className="strm-source-folder-selection-head"><div><strong>选择扫描子目录</strong><small>只扫描明确勾选并保存的目录，115 与夸克规则一致。</small></div><button type="button" className="ghost compact-action" disabled={busy !== "" || !connected || !root.trim() || sourceDirectoriesBusy} onClick={() => void loadSourceDirectories()}>{sourceDirectoriesBusy ? <CircleNotch className="spin" /> : <ArrowClockwise />}读取子目录</button></div>{includedDirectories.length > 0 && <div className="strm-selected-folder-list" aria-label="已保存的扫描目录">{includedDirectories.map((path) => <span key={path}><CheckCircle weight="fill" />{path}</span>)}</div>}{sourceDirectoriesLoaded && <div className="strm-source-folder-list">{sourceDirectories.length ? sourceDirectories.map((directory) => <label key={directory.path}><input type="checkbox" checked={includedDirectories.includes(directory.path)} onChange={(event) => toggleIncludedDirectory(directory.path, event.target.checked)} /><FolderOpen size={17} /><span>{directory.name}</span></label>) : <small>当前来源目录没有可选择的子目录。</small>}</div>}<p className="settings-help">未勾选时不会执行扫描；勾选并保存后仅递归读取所选目录，根目录散落文件和其他目录不会读取。</p></div><p className="settings-help">这里只决定读取哪些网盘文件来生成本地 STRM，不会改变“网盘工作台 → 转存和整理规则”的保存路径。</p></div></details>
      <details open><summary><span>STRM 生成</span><small>自动生成、输出目录和手动扫描</small></summary><div className="accordion-content settings-stack"><SettingsToggle label={`自动生成 ${label} STRM`} help="开启后，成功转存到该网盘会扫描本页已勾选的来源子目录并生成 STRM。" value={enabled} onChange={setEnabled} trueLabel="已开启" falseLabel="已关闭" /><SettingsInput label="STRM 输出目录" name="strm_output_root" value={outputRoot} saved={Boolean(config.strm_output_root)} placeholder="/strm" onChange={(_name, value) => setOutputRoot(value)} action={<button type="button" className="ghost compact-action" disabled={busy !== ""} onClick={() => setOutputPickerOpen(true)}><FolderOpen />浏览</button>} /><SettingsInput label="定时增量扫描（Cron）" name={`${provider}_strm_incremental_cron`} value={incrementalCron} saved={Boolean(savedCron)} placeholder="例如 0 */6 * * *" onChange={(_name, value) => setIncrementalCron(value)} help="标准 5 段 Cron：分 时 日 月 周；留空即关闭。定时任务只执行增量扫描。" /><div className="settings-action-strip"><button type="button" className="primary compact-action" disabled={busy !== "" || !connected || !root.trim() || !outputRoot.trim() || !includedDirectories.length} onClick={() => void reconcile("full")}>{busy === "full" ? <CircleNotch className="spin" /> : <ArrowClockwise />}全量扫描更新</button><button type="button" className="ghost compact-action" disabled={busy !== "" || !connected || !root.trim() || !outputRoot.trim() || !includedDirectories.length} onClick={() => void reconcile("incremental")}>{busy === "incremental" ? <CircleNotch className="spin" /> : <FileVideo />}增量扫描</button></div><p className="settings-help">全量扫描与增量扫描都只读取网盘目录元数据，不创建、移动或删除网盘文件；全量扫描仅清理 MediaIndex 自己生成的本地 STRM 映射。</p></div></details>
      {provider === "p115" && <details open><summary><span>115 生活事件监控</span><small>其他 Docker 写入后触发增量 STRM</small></summary><div className="accordion-content settings-stack"><SettingsToggle label="启用生活事件监控" help="只读取 115 最近操作事件；发现新变化后只扫描指定子目录。" value={lifeMonitorEnabled} onChange={setLifeMonitorEnabled} trueLabel="已开启" falseLabel="已关闭" /><SettingsInput label="监控的 115 子目录" name="p115_strm_life_monitor_path" value={lifeMonitorPath} saved={Boolean(config.p115_strm_life_monitor_path)} placeholder={`${root.replace(/\/$/, "")}/外部整理`} onChange={(_name, value) => setLifeMonitorPath(value)} showSavedValue action={<button type="button" className="ghost compact-action" disabled={!connected} onClick={() => setLifeMonitorPickerOpen(true)}><FolderOpen />选择</button>} /><SettingsInput label="事件检查间隔（秒）" name="p115_strm_life_monitor_interval_seconds" value={lifeMonitorInterval} saved onChange={(_name, value) => setLifeMonitorInterval(value.replace(/[^0-9]/g, ""))} help="30-3600 秒；首次启动只建立基线，不会重复扫描历史事件。" /><p className="settings-help">监控只作为变化信号，真正生成时仍使用 MediaIndex 的分页增量扫描和文件范围规则。</p></div></details>}
      <details open><summary><span>生成文件范围</span><small>可手动设置正片识别和过滤规则</small></summary><div className="accordion-content settings-stack"><SettingsInput label="视频扩展名（逗号分隔）" name="strm_video_extensions" value={extensions} saved={Boolean(config.strm_video_extensions.length)} onChange={(_name, value) => setExtensions(value)} /><SettingsInput label="排除关键词（逗号分隔）" name="strm_excluded_name_tokens" value={excludedTokens} saved onChange={(_name, value) => setExcludedTokens(value)} /><SettingsInput label="最小文件大小（MiB，0 为不限制）" name="strm_min_file_size_mb" value={minSizeMb} saved onChange={(_name, value) => setMinSizeMb(value.replace(/[^0-9]/g, ""))} /></div></details>
    </div>
    {pickerOpen && <ProviderDirectoryPicker provider={provider} label={`${label} STRM 来源目录`} startPath={root || "/"} onClose={() => setPickerOpen(false)} onSelect={(path) => { changeRoot(path); setPickerOpen(false); }} />}
    {lifeMonitorPickerOpen && <ProviderDirectoryPicker provider="p115" label="115 生活事件监控目录" startPath={lifeMonitorPath || root || "/"} onClose={() => setLifeMonitorPickerOpen(false)} onSelect={(path) => { setLifeMonitorPath(path); setLifeMonitorPickerOpen(false); }} />}
    {outputPickerOpen && <LocalDirectoryPicker label="STRM 输出目录" startPath={outputRoot} onClose={() => setOutputPickerOpen(false)} onSelect={(path) => { setOutputRoot(path); setOutputPickerOpen(false); }} />}
    <div className="settings-footer"><span>{enabled && !includedDirectories.length ? "请先勾选至少一个扫描子目录" : dirty ? `当前有尚未保存的 ${label} STRM 设置` : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || !dirty || !root.trim() || (enabled && (!outputRoot.trim() || !includedDirectories.length))} onClick={() => void savePage()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
    <DeletionSyncPage provider={provider} config={config} onChanged={onChanged} />
  </section>;
}

function DeletionSyncPage({ provider, config, onChanged }: { provider: "p115" | "quark"; config: ConfigStatus; onChanged: () => Promise<void> }) {
  const [token, setToken] = useState("");
  const [savedToken, setSavedToken] = useState("");
  const [embyLibraryRoot, setEmbyLibraryRoot] = useState(config.emby_strm_library_root || config.strm_output_root || "");
  const [autoConfirm, setAutoConfirm] = useState(config.emby_deletion_auto_confirm);
  const [webhookVisible, setWebhookVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const dirty = Boolean(token.trim() && token.trim() !== savedToken) || embyLibraryRoot.trim() !== (config.emby_strm_library_root || config.strm_output_root || "") || autoConfirm !== config.emby_deletion_auto_confirm;
  const webhookBaseUrl = `${window.location.origin}/api/integrations/emby/strm-deleted`;
  const webhookUrl = token.trim() ? `${webhookBaseUrl}?token=${encodeURIComponent(token.trim())}` : "填写或生成新密钥并保存后显示";
  async function savePage() {
    setBusy(true); setMessage("");
    try {
      await api.saveConfig({ emby_deletion_webhook_token: token, emby_strm_library_root: embyLibraryRoot.trim(), emby_deletion_auto_confirm: autoConfirm, emby_deletion_mode: "trash" });
      setSavedToken(token.trim()); await onChanged(); setMessage("删除同步规则已保存。请复制下方完整 Webhook URL 到 Emby。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "删除同步设置保存失败"); }
    finally { setBusy(false); }
  }
  if (provider === "quark") return <section className="workspace-section strm-config-page"><header className="portal-section-head"><div><h2>夸克删除同步</h2><p>已预留独立入口和资产映射，当前版本暂未开放网盘删除执行。</p></div><span className="connection-pill"><Trash />暂未支持</span></header><div className="notice page-notice">夸克目录、文件 ID 与 STRM 映射会独立登记；待删除接口完成安全验证后在此启用，不会借用 115 的路径或规则。</div></section>;
  return <section className="workspace-section strm-config-page"><header className="portal-section-head"><div><h2>115 删除同步</h2><p>只处理 115 STRM 的精确资产标识，不按名称猜测，也不与夸克共用网盘路径。</p></div><span className={`connection-pill ${config.has_emby_deletion_webhook_token ? "connected" : ""}`}><Trash />{config.has_emby_deletion_webhook_token ? "Webhook 已配置" : "未配置"}</span></header>{message && <div className="notice page-notice">{message}</div>}
    <div className="strm-accordion-list"><details open><summary><span>Emby 删除事件</span><small>Webhook 认证与自动执行规则</small></summary><div className="accordion-content settings-stack">
      <SettingsInput label="Webhook 密钥" name="emby_deletion_webhook_token" value={token} saved={config.has_emby_deletion_webhook_token} secret onChange={(_name, value) => setToken(value)} onReveal={(value) => { setToken(value); setSavedToken(value); }} action={<button type="button" className="ghost compact-action" onClick={() => { setToken(generateWebhookToken()); setWebhookVisible(true); }}>生成新密钥</button>} help="用于验证 Emby 发来的删除事件。生成新密钥会使旧 Webhook URL 失效。" />
      <SettingsInput label="Emby 中的 STRM 媒体库根目录" name="emby_strm_library_root" value={embyLibraryRoot} saved={Boolean(config.emby_strm_library_root)} placeholder="例如 /media/strm 或 D:/媒体库/STRM" showSavedValue onChange={(_name, value) => setEmbyLibraryRoot(value)} help="填写 Emby 删除事件里看到的路径根目录；它可能与 MediaIndex 容器内的 STRM 输出目录不同。神医助手 Pro 与 Emby 分处不同容器时必须按 Emby 的路径填写。" />
      <div className="settings-field compact-select-field"><span>源文件删除方式</span><select value="trash" disabled aria-label="源文件删除方式"><option value="trash">移入 115 回收站</option></select><small>仅对当前 115 STRM 映射生效；彻底删除未开放。</small></div>
      <SettingsToggle label="收到 Emby 删除事件后自动执行" help="必须开启才会实际移入 115 回收站；关闭时只创建删除意图。" value={autoConfirm} onChange={setAutoConfirm} trueLabel="自动执行" falseLabel="仅记录" />
      <div className="webhook-setup-values"><span>完整 Webhook URL</span><code>{webhookVisible && token.trim() ? webhookUrl : token.trim() ? `${webhookBaseUrl}?token=••••••••` : webhookUrl}</code><span>内容类型（推荐）</span><code>multipart/form-data</code></div>
      <div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={!token.trim()} onClick={() => setWebhookVisible((current) => !current)}>{webhookVisible ? "隐藏完整 URL" : "显示完整 URL"}</button><button type="button" className="ghost compact-action" disabled={!token.trim()} onClick={() => void copyWebhookUrl(webhookUrl, setMessage)}>复制完整 URL</button></div>
      <p className="settings-help">神医助手 Pro 中启用删除媒体通知，把完整 URL 填入 Webhook“网址”，内容类型选择 multipart/form-data（也兼容 application/json），并确保发送 ItemRemoved / item.deleted 一类删除事件。这里使用 MediaIndex 管理端口，不使用 302 播放端口。</p>
    </div></details></div>
    <div className="settings-footer"><span>{dirty ? "当前有尚未保存的删除同步设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy || !dirty} onClick={() => void savePage()}>{busy && <CircleNotch className="spin" />}{busy ? "保存中" : "保存本页设置"}</button></div>
  </section>;
}

function generateWebhookToken() {
  const bytes = new Uint8Array(32);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

async function copyWebhookUrl(url: string, setMessage: (message: string) => void) {
  try {
    await navigator.clipboard.writeText(url);
    setMessage("完整 Webhook URL 已复制，请粘贴到 Emby 的网址栏。");
  } catch {
    window.prompt("复制完整 Webhook URL", url);
  }
}
