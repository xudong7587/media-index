import { ArrowClockwise, CheckCircle, CircleNotch, Cloud, FileVideo, HardDrives, PlayCircle, ShieldCheck, Trash, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { AppRoute } from "../../app/routes";
import { api, ApiError, ConfigStatus, DeletionIntent, MediaAsset, StrmEntry } from "../../lib/api";
import { SettingsInput, SettingsToggle } from "../settings/SettingsFormParts";
import { ProviderDirectoryPicker } from "../openlist/OpenListSettingsTools";

const sections = [
  { key: "emby", label: "Emby 连接", icon: PlayCircle },
  { key: "p115", label: "115 STRM", icon: HardDrives },
  { key: "quark", label: "夸克 STRM", icon: Cloud },
  { key: "deletion", label: "删除同步", icon: Trash },
] as const;

type RefreshData = { config: ConfigStatus; assets: MediaAsset[]; entries: StrmEntry[]; intents: DeletionIntent[] };

export function StrmPortal({ route, onNavigate }: { route: AppRoute; onNavigate: (route: AppRoute) => void }) {
  const [data, setData] = useState<RefreshData | null>(null);
  const [error, setError] = useState("");
  const section = route.section || "emby";
  async function refresh() {
    const [config, assets, entries, intents] = await Promise.all([api.config(), api.mediaAssets(), api.strmEntries(), api.deletionIntents()]);
    setData({ config, assets, entries, intents });
  }
  useEffect(() => { void refresh().catch((reason: Error) => setError(reason.message || "STRM 配置读取失败")); }, []);

  return <section className="strm-portal">
    <div className="page-head workspace-portal-head"><div><p className="eyebrow">LIBRARY PLAYBACK</p><h1>STRM 与 302</h1><p>每个网盘独立完成索引、整理和 STRM 校正；Emby 连接与删除联动单独管理。</p></div></div>
    <nav className="portal-subnav" aria-label="STRM 与 302 模块">{sections.map(({ key, label, icon: Icon }) => <button type="button" key={key} className={section === key ? "active" : ""} onClick={() => onNavigate({ page: "strm", section: key === "emby" ? undefined : key })}><Icon size={18} />{label}</button>)}</nav>
    {error && <p className="workspace-message">{error}</p>}
    {!data ? <div className="workspace-loading"><CircleNotch className="spin" />正在读取媒体库状态</div> : <>
      {section === "emby" && <EmbyConnectionPage config={data.config} onChanged={refresh} />}
      {section === "p115" && <DriveStrmPage provider="p115" data={data} onChanged={refresh} />}
      {section === "quark" && <DriveStrmPage provider="quark" data={data} onChanged={refresh} />}
      {section === "deletion" && <DeletionSyncPage data={data} onChanged={refresh} />}
    </>}
  </section>;
}

function EmbyConnectionPage({ config, onChanged }: { config: ConfigStatus; onChanged: () => Promise<void> }) {
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [playbackPort, setPlaybackPort] = useState(String(config.emby_proxy_port || 8097));
  const [playbackBaseUrl, setPlaybackBaseUrl] = useState(config.strm_playback_base_url || "");
  const [embyLibraryId, setEmbyLibraryId] = useState(config.emby_library_id || "");
  const [embyRefreshEnabled, setEmbyRefreshEnabled] = useState(config.emby_library_refresh_enabled);
  const [busy, setBusy] = useState<"save" | "test" | "">("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  async function savePage() {
    setBusy("save"); setResult(null);
    try {
      const payload: Record<string, string | number | boolean> = { emby_library_id: embyLibraryId.trim(), emby_library_refresh_enabled: embyRefreshEnabled, emby_proxy_port: Number(playbackPort), strm_playback_base_url: playbackBaseUrl.trim() };
      if (url.trim()) payload.emby_base_url = url.trim();
      if (apiKey.trim()) payload.emby_api_key = apiKey.trim();
      await api.saveConfig(payload);
      setUrl(""); setApiKey(""); await onChanged(); setResult({ ok: true, message: "Emby 连接与入库刷新规则已保存。" });
    } catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "Emby 设置保存失败" }); }
    finally { setBusy(""); }
  }
  async function test() {
    setBusy("test"); setResult(null);
    try { setResult(await api.testEmby()); }
    catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "Emby 连接测试失败" }); }
    finally { setBusy(""); }
  }
  const configured = Boolean(config.emby_base_url && config.has_emby_api_key);
  const hasEmbyUrl = Boolean(url.trim() || config.emby_base_url);
  const dirty = Boolean(url.trim() || apiKey.trim() || playbackPort !== String(config.emby_proxy_port || 8097) || playbackBaseUrl.trim() !== (config.strm_playback_base_url || "") || embyLibraryId.trim() !== (config.emby_library_id || "") || embyRefreshEnabled !== config.emby_library_refresh_enabled);
  return <section className="workspace-section strm-config-page">
    <header className="portal-section-head"><div><h2>Emby 连接</h2><p>配置 MediaIndex 连接 Emby 的地址、密钥和生成后刷新媒体库的规则。</p></div><span className={`connection-pill ${configured ? "connected" : ""}`}>{configured ? <CheckCircle weight="fill" /> : <WarningCircle />}{configured ? "已配置" : "未配置"}</span></header>
    <div className="strm-accordion-list">
      <details open><summary><span>Emby 服务器</span><small>地址、API Key 与连接测试</small></summary><div className="accordion-content settings-stack">
        <SettingsInput label="Emby 内网地址（必填）" name="emby_base_url" value={url} saved={Boolean(config.emby_base_url)} placeholder="http://192.168.1.100:8096" onChange={(_name, value) => setUrl(value)} helpTooltip="302 端口会将 Emby 页面、API、WebSocket 和媒体请求转发到这个内网地址。" />
        <SettingsInput label="Emby API Key" name="emby_api_key" value={apiKey} saved={config.has_emby_api_key} secret onChange={(_name, value) => setApiKey(value)} />
        <SettingsInput label="302 内网端口" name="emby_proxy_port" value={playbackPort} saved onChange={(_name, value) => setPlaybackPort(value.replace(/[^0-9]/g, ""))} helpTooltip="Compose 中专用播放服务的主机端口，例如 38013:8000 中的 38013。" />
        <SettingsInput label="STRM 播放地址（可选）" name="strm_playback_base_url" value={playbackBaseUrl} saved={Boolean(config.strm_playback_base_url)} placeholder="https://tvb302.example.com:666" onChange={(_name, value) => setPlaybackBaseUrl(value)} helpTooltip="STRM 文件中写入的可访问地址。使用反向代理时填外网地址；留空则用 Emby 主机和 302 内网端口自动生成。" />
        <div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy !== "" || !configured} onClick={() => void test()}>{busy === "test" ? <CircleNotch className="spin" /> : <ShieldCheck />}测试连接</button></div>
      </div></details>
      <details><summary><span>Emby 自动入库</span><small>生成完成后通知 Emby 扫描对应媒体库</small></summary><div className="accordion-content settings-stack"><SettingsInput label="Emby 媒体库 ID" name="emby_library_id" value={embyLibraryId} saved={Boolean(config.emby_library_id)} placeholder="从 Emby 媒体库信息中获取" onChange={(_name, value) => setEmbyLibraryId(value)} /><SettingsToggle label="STRM 完成后刷新 Emby 媒体库" help="启用后，STRM 任务新增或更新文件会调用 Emby 刷新；媒体资料匹配由 Emby 此媒体库的元数据设置执行。" value={embyRefreshEnabled} onChange={setEmbyRefreshEnabled} trueLabel="已开启" falseLabel="已关闭" /></div></details>
    </div>
    {result && <div className="strm-page-actions"><span className={result.ok ? "success-text" : "error-text"}>{result.message}</span></div>}
    <div className="settings-footer"><span>{!hasEmbyUrl ? "请先填写 Emby 内网地址" : dirty ? "当前有尚未保存的 Emby 设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || !dirty || !hasEmbyUrl} onClick={() => void savePage()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
  </section>;
}

function DriveStrmPage({ provider, data, onChanged }: { provider: "p115" | "quark"; data: RefreshData; onChanged: () => Promise<void> }) {
  const label = provider === "p115" ? "115" : "夸克";
  const connected = provider === "p115" ? data.config.has_p115_cookie || data.config.has_p115_open : data.config.has_quark_cookie;
  const [root, setRoot] = useState(provider === "p115" ? data.config.p115_root_path : data.config.quark_root_path);
  const [outputRoot, setOutputRoot] = useState(data.config.strm_output_root || "");
  const [enabled, setEnabled] = useState(provider === "p115" ? data.config.p115_strm_enabled : data.config.quark_strm_enabled);
  const [extensions, setExtensions] = useState(data.config.strm_video_extensions.join(", "));
  const [excludedTokens, setExcludedTokens] = useState(data.config.strm_excluded_name_tokens.join(", "));
  const [minSizeMb, setMinSizeMb] = useState(String(data.config.strm_min_file_size_mb));
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState<"scan" | "incremental" | "full" | "save" | "">("");
  const [message, setMessage] = useState("");
  const assets = useMemo(() => data.assets.filter((asset) => asset.provider === provider), [data.assets, provider]);
  const entries = useMemo(() => data.entries.filter((entry) => entry.provider === provider || assets.some((asset) => asset.id === entry.asset_id)), [data.entries, assets, provider]);
  async function scan() {
    setBusy("scan"); setMessage("");
    try {
      if (enabled) {
        setMessage("已开启自动生成；请使用“全量扫描并校正”，这样完整 STRM 过程会记录到任务中心和运行日志。若只想索引，请先关闭自动生成并保存设置。");
        return;
      }
      const result = provider === "p115" ? await api.scanP115Inventory(root) : await api.scanQuarkInventory(root);
      const autoText = result.auto_strm?.ok
        ? `；自动 STRM：新增 ${result.auto_strm.created || 0}，替换 ${result.auto_strm.replaced || 0}`
        : result.auto_strm ? `；${result.auto_strm.message || "STRM 自动校正失败，请手动重试"}` : "";
      setMessage(`索引完成：${result.files_indexed} 个文件，${result.directories_scanned} 个目录${result.truncated ? "，已达到本次上限" : ""}${autoText}。`);
      await onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : "索引失败"); }
    finally { setBusy(""); }
  }
  async function reconcile(mode: "incremental" | "full") {
    setBusy(mode); setMessage("");
    try {
      await saveSettings();
      const result = await api.startStrmJob({ provider, mode, root_path: root.trim(), output_root: outputRoot.trim() });
      setMessage(`已创建 STRM 任务 #${result.job_id}；可在任务中心和右上角运行日志查看进度与结果。`);
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
      [provider === "p115" ? "p115_root_path" : "quark_root_path"]: root.trim(), strm_output_root: outputRoot.trim(),
      [`${provider}_strm_enabled`]: enabled, ...rangePayload(),
    });
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
  const savedRoot = provider === "p115" ? data.config.p115_root_path : data.config.quark_root_path;
  const savedEnabled = provider === "p115" ? data.config.p115_strm_enabled : data.config.quark_strm_enabled;
  const dirty = root.trim() !== (savedRoot || "") || outputRoot.trim() !== (data.config.strm_output_root || "") || enabled !== savedEnabled || extensions !== data.config.strm_video_extensions.join(", ") || excludedTokens !== data.config.strm_excluded_name_tokens.join(", ") || minSizeMb !== String(data.config.strm_min_file_size_mb);
  return <section className="workspace-section strm-config-page">
    <header className="portal-section-head"><div><h2>{label} STRM</h2><p>{label} 的索引、全量校正、过滤、替换和记录都在本页完成。</p></div><span className={`connection-pill ${connected ? "connected" : ""}`}>{connected ? <CheckCircle weight="fill" /> : <WarningCircle />}{connected ? `${label} 已连接` : `${label} 未连接`}</span></header>
    {message && <div className="notice page-notice">{message}</div>}
    <div className="strm-metrics"><span><strong>{assets.length}</strong>已登记资产</span><span><strong>{entries.length}</strong>STRM 映射</span><span><strong>{assets.filter((item) => item.status === "needs_review").length}</strong>待核对资产</span></div>
    <div className="strm-accordion-list">
      <details open><summary><span>同步与扫描</span><small>来源目录、只读索引和手动执行</small></summary><div className="accordion-content settings-stack"><SettingsInput label={`${label} 来源目录`} name={`${provider}_root_path`} value={root} saved placeholder="/strm" onChange={(_name, value) => setRoot(value)} showSavedValue />{provider === "p115" && <div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy !== "" || !connected} onClick={() => setPickerOpen(true)}>浏览并选择 115 目录</button></div>}<div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy !== "" || !connected || !root.trim()} onClick={() => void scan()}>{busy === "scan" ? <CircleNotch className="spin" /> : <ArrowClockwise />}仅扫描网盘变化</button></div></div></details>
      <details open><summary><span>STRM 生成与校正</span><small>自动生成、输出目录和全量校正</small></summary><div className="accordion-content settings-stack"><SettingsToggle label={`自动生成 ${label} STRM`} help="开启后，每次网盘索引完成会自动增量校正；关闭后仍可手动生成。" value={enabled} onChange={setEnabled} trueLabel="已开启" falseLabel="已关闭" /><SettingsInput label="STRM 输出目录" name="strm_output_root" value={outputRoot} saved={Boolean(data.config.strm_output_root)} placeholder="D:\\Media\\strm" onChange={(_name, value) => setOutputRoot(value)} /><div className="strm-runtime-fact"><ShieldCheck /><div><strong>媒体资料由影视服务器处理</strong><span>MediaIndex 只生成 STRM 播放入口，不生成 NFO、海报或背景图；刮削交给 Emby 等影视服务器。</span></div></div><div className="strm-runtime-fact"><ShieldCheck /><div><strong>STRM 播放地址</strong><span>优先使用 Emby 连接页保存的“STRM 播放地址”；留空时才使用 Emby 主机与 302 内网端口自动生成。</span></div></div><div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy !== "" || !outputRoot.trim()} onClick={() => void reconcile("incremental")}>{busy === "incremental" ? <CircleNotch className="spin" /> : <FileVideo />}增量生成</button><button type="button" className="primary compact-action" disabled={busy !== "" || !connected || !root.trim() || !outputRoot.trim()} onClick={() => void reconcile("full")}>{busy === "full" ? <CircleNotch className="spin" /> : <ArrowClockwise />}全量扫描并校正</button></div></div></details>
      <details><summary><span>生成文件范围</span><small>可手动设置正片识别和过滤规则</small></summary><div className="accordion-content settings-stack"><SettingsInput label="视频扩展名（逗号分隔）" name="strm_video_extensions" value={extensions} saved={Boolean(data.config.strm_video_extensions.length)} onChange={(_name, value) => setExtensions(value)} /><SettingsInput label="排除关键词（逗号分隔）" name="strm_excluded_name_tokens" value={excludedTokens} saved onChange={(_name, value) => setExcludedTokens(value)} /><SettingsInput label="最小文件大小（MiB，0 为不限制）" name="strm_min_file_size_mb" value={minSizeMb} saved onChange={(_name, value) => setMinSizeMb(value.replace(/[^0-9]/g, ""))} /></div></details>
      <details><summary><span>最近资产与 STRM</span><small>核对生成结果和异常</small></summary><div className="accordion-content asset-record-list">{assets.length === 0 ? <p className="workspace-empty">还没有登记 {label} 资产，请先扫描来源目录。</p> : assets.slice(0, 30).map((asset) => <article key={asset.id}><FileVideo /><div><strong>{asset.name}</strong><small>文件 ID {asset.file_id} · {formatBytes(asset.size)}</small></div><span className={`task-status ${asset.status}`}>{asset.status === "ready" ? "可生成" : asset.status === "needs_review" ? "待确认" : asset.status}</span></article>)}</div></details>
    </div>
    {pickerOpen && <ProviderDirectoryPicker provider="p115" label="115 STRM 来源目录" startPath={root || "/"} onClose={() => setPickerOpen(false)} onSelect={(path) => { setRoot(path); setPickerOpen(false); }} />}
    <div className="settings-footer"><span>{dirty ? `当前有尚未保存的 ${label} STRM 设置` : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || !dirty || !root.trim() || (enabled && !outputRoot.trim())} onClick={() => void savePage()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
  </section>;
}

function DeletionSyncPage({ data, onChanged }: { data: RefreshData; onChanged: () => Promise<void> }) {
  const [token, setToken] = useState(""); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  async function saveToken() { setBusy(true); try { await api.saveConfig({ emby_deletion_webhook_token: token }); setToken(""); setMessage("删除同步密钥已保存。Emby 事件只会创建待确认的精确回收意图。"); await onChanged(); } catch (error) { setMessage(error instanceof Error ? error.message : "密钥保存失败"); } finally { setBusy(false); } }
  async function create(assetId: number) { setBusy(true); try { const intent = await api.createDeletionIntent(assetId); setMessage(`已创建回收意图 #${intent.id}，尚未删除网盘文件。`); await onChanged(); } catch (error) { setMessage(error instanceof Error ? error.message : "回收意图创建失败"); } finally { setBusy(false); } }
  async function confirm(intentId: number) { setBusy(true); try { const intent = await api.confirmDeletionIntent(intentId); setMessage(`回收意图 #${intent.id} 已执行，文件已移入 115 回收站。`); await onChanged(); } catch (error) { setMessage(error instanceof Error ? error.message : "回收失败"); } finally { setBusy(false); } }
  const requested = data.intents.filter((intent) => intent.state === "requested");
  const ready115 = data.assets.filter((asset) => asset.provider === "p115" && asset.status === "ready");
  return <section className="workspace-section strm-config-page"><header className="portal-section-head"><div><h2>删除同步</h2><p>Emby 或神医助手删除 STRM 后，MediaIndex 通过精确资产映射创建回收意图；确认后才移动网盘文件。</p></div><span className="connection-pill"><Trash />{requested.length} 个待确认</span></header>{message && <div className="notice page-notice">{message}</div>}
    <div className="strm-accordion-list"><details open><summary><span>Emby 删除事件</span><small>Webhook 认证与行为边界</small></summary><div className="accordion-content settings-stack"><SettingsInput label="Webhook 密钥" name="emby_deletion_webhook_token" value={token} saved={data.config.has_emby_deletion_webhook_token} secret onChange={(_name, value) => setToken(value)} /><code className="endpoint-code">POST /api/integrations/emby/strm-deleted · Header: X-MediaIndex-Webhook</code></div></details>
      <details open><summary><span>待确认回收</span><small>逐条核对并移入回收站</small></summary><div className="accordion-content deletion-record-list">{requested.length === 0 ? <p className="workspace-empty">没有待确认的删除事件。</p> : requested.map((intent) => <article key={intent.id}><Trash /><div><strong>{intent.asset_name}</strong><small>文件 ID {intent.file_id} · {intent.trigger_source} · {intent.message_safe}</small></div><button type="button" className="ghost compact-action danger-action" disabled={busy} onClick={() => void confirm(intent.id)}>确认移入回收站</button></article>)}</div></details>
      <details><summary><span>已登记的 115 资产</span><small>手动发起精确回收意图</small></summary><div className="accordion-content asset-record-list">{ready115.length === 0 ? <p className="workspace-empty">没有可回收的 115 资产。</p> : ready115.map((asset) => <article key={asset.id}><FileVideo /><div><strong>{asset.name}</strong><small>文件 ID {asset.file_id}</small></div><button type="button" className="ghost compact-action danger-action" disabled={busy} onClick={() => void create(asset.id)}>创建回收意图</button></article>)}</div></details>
    </div>
    <div className="settings-footer"><span>{token.trim() ? "当前有尚未保存的删除同步设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy || !token.trim()} onClick={() => void saveToken()}>{busy && <CircleNotch className="spin" />}{busy ? "保存中" : "保存本页设置"}</button></div>
  </section>;
}

function formatBytes(value: number) { if (value < 1024) return `${value} B`; const units = ["KiB", "MiB", "GiB", "TiB"]; let size = value / 1024; let index = 0; while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; } return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[index]}`; }
