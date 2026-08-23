import { ArrowClockwise, CheckCircle, CircleNotch, Cloud, FileVideo, HardDrives, PlayCircle, ShieldCheck, Trash, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { AppRoute } from "../../app/routes";
import { api, ApiError, ConfigStatus } from "../../lib/api";
import { SettingsInput, SettingsToggle } from "../settings/SettingsFormParts";
import { ProviderDirectoryPicker } from "../openlist/OpenListSettingsTools";

const sections = [
  { key: "emby", label: "STRM 通用设置", icon: PlayCircle },
  { key: "p115", label: "115 STRM", icon: HardDrives },
  { key: "quark", label: "夸克 STRM", icon: Cloud },
  { key: "deletion", label: "删除同步", icon: Trash },
] as const;

type RefreshData = { config: ConfigStatus };

export function StrmPortal({ route, onNavigate }: { route: AppRoute; onNavigate: (route: AppRoute) => void }) {
  const [data, setData] = useState<RefreshData | null>(null);
  const [error, setError] = useState("");
  const section = route.section || "emby";
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
      {section === "deletion" && <DeletionSyncPage config={data.config} onChanged={refresh} />}
    </>}
  </section>;
}

function EmbyConnectionPage({ config, onChanged }: { config: ConfigStatus; onChanged: () => Promise<void> }) {
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [playbackBaseUrl, setPlaybackBaseUrl] = useState(config.strm_playback_base_url || "");
  const [embyLibraryId, setEmbyLibraryId] = useState(config.emby_library_id || "");
  const [embyRefreshEnabled, setEmbyRefreshEnabled] = useState(config.emby_library_refresh_enabled);
  const [busy, setBusy] = useState<"save" | "test" | "">("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  async function savePage() {
    setBusy("save"); setResult(null);
    try {
      const payload: Record<string, string | number | boolean> = { emby_library_id: embyLibraryId.trim(), emby_library_refresh_enabled: embyRefreshEnabled, strm_playback_base_url: playbackBaseUrl.trim() };
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
  const dirty = Boolean(url.trim() || apiKey.trim() || playbackBaseUrl.trim() !== (config.strm_playback_base_url || "") || embyLibraryId.trim() !== (config.emby_library_id || "") || embyRefreshEnabled !== config.emby_library_refresh_enabled);
  const configuredPlaybackAddress = playbackBaseUrl.trim() || config.strm_playback_base_url || "未配置（宿主机端口不是 8097 时必须填写）";
  return <section className="workspace-section strm-config-page">
    <header className="portal-section-head"><div><h2>STRM 通用设置</h2><p>统一管理 302 的内外网入口、STRM 写入地址和 Emby 自动入库。</p></div><span className={`connection-pill ${configured ? "connected" : ""}`}>{configured ? <CheckCircle weight="fill" /> : <WarningCircle />}{configured ? "Emby 已连接" : "Emby 未连接"}</span></header>
    <div className="strm-accordion-list">
      <details open><summary><span>302 播放地址</span><small>容器监听端口与 STRM 实际播放入口</small></summary><div className="accordion-content settings-stack">
        <label className="settings-field"><span>容器内部监听端口</span><input value="8097" disabled aria-label="容器内部监听端口" /><small className="settings-field-help">固定为 8097。NAS 播放端口只在 Compose 的 ports 左侧设置，例如 38013:8097；MediaIndex 不读取也不修改宿主机端口。</small></label>
        <SettingsInput label="STRM 播放地址" name="strm_playback_base_url" value={playbackBaseUrl} saved={Boolean(config.strm_playback_base_url)} placeholder="https://tvb302.example.com:666" onChange={(_name, value) => setPlaybackBaseUrl(value)} helpTooltip="写入 STRM 文件的完整播放入口。宿主机端口不是 8097 时必须填写，可使用反向代理域名。" />
        <div className="strm-playback-examples"><div><span>Compose 端口映射示例</span><code>38013:8097</code></div><div><span>STRM 实际写入地址</span><code>{configuredPlaybackAddress}</code></div></div>
      </div></details>
      <details open><summary><span>Emby 服务器</span><small>连接、媒体库刷新与入库规则</small></summary><div className="accordion-content settings-stack">
        <SettingsInput label="Emby 内网地址（必填）" name="emby_base_url" value={url} saved={Boolean(config.emby_base_url)} placeholder="http://192.168.1.100:8096" onChange={(_name, value) => setUrl(value)} helpTooltip="MediaIndex 与 302 服务连接真实 Emby 的内网地址。" />
        <SettingsInput label="Emby API Key" name="emby_api_key" value={apiKey} saved={config.has_emby_api_key} secret onChange={(_name, value) => setApiKey(value)} />
        <SettingsInput label="Emby 媒体库 ID" name="emby_library_id" value={embyLibraryId} saved={Boolean(config.emby_library_id)} placeholder="从 Emby 媒体库信息中获取" onChange={(_name, value) => setEmbyLibraryId(value)} />
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
  const connected = provider === "p115" ? config.has_p115_cookie || config.has_p115_open : config.has_quark_cookie;
  const [root, setRoot] = useState(provider === "p115" ? config.p115_root_path : config.quark_root_path);
  const [outputRoot, setOutputRoot] = useState(config.strm_output_root || "");
  const [enabled, setEnabled] = useState(provider === "p115" ? config.p115_strm_enabled : config.quark_strm_enabled);
  const [extensions, setExtensions] = useState(config.strm_video_extensions.join(", "));
  const [excludedTokens, setExcludedTokens] = useState(config.strm_excluded_name_tokens.join(", "));
  const [minSizeMb, setMinSizeMb] = useState(String(config.strm_min_file_size_mb));
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState<"incremental" | "full" | "save" | "">("");
  const [message, setMessage] = useState("");
  async function reconcile(mode: "incremental" | "full") {
    setBusy(mode); setMessage("");
    try {
      await saveSettings();
      const result = await api.startStrmJob({
        provider,
        mode,
        root_path: root.trim(),
        output_root: outputRoot.trim(),
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
  const savedRoot = provider === "p115" ? config.p115_root_path : config.quark_root_path;
  const savedEnabled = provider === "p115" ? config.p115_strm_enabled : config.quark_strm_enabled;
  const dirty = root.trim() !== (savedRoot || "") || outputRoot.trim() !== (config.strm_output_root || "") || enabled !== savedEnabled || extensions !== config.strm_video_extensions.join(", ") || excludedTokens !== config.strm_excluded_name_tokens.join(", ") || minSizeMb !== String(config.strm_min_file_size_mb);
  return <section className="workspace-section strm-config-page">
    <header className="portal-section-head"><div><h2>{label} STRM</h2><p>管理 {label} 来源目录、全量/增量扫描和 STRM 文件范围。</p></div><span className={`connection-pill ${connected ? "connected" : ""}`}>{connected ? <CheckCircle weight="fill" /> : <WarningCircle />}{connected ? `${label} 已连接` : `${label} 未连接`}</span></header>
    {message && <div className="notice page-notice">{message}</div>}
    <div className="strm-accordion-list">
      <details open><summary><span>来源目录</span><small>选择要生成 STRM 的网盘根目录</small></summary><div className="accordion-content settings-stack"><SettingsInput label={`${label} 来源目录`} name={`${provider}_root_path`} value={root} saved placeholder="/媒体库" onChange={(_name, value) => setRoot(value)} showSavedValue action={provider === "p115" ? <button type="button" className="ghost compact-action" disabled={busy !== "" || !connected} onClick={() => setPickerOpen(true)}>浏览</button> : undefined} /></div></details>
      <details open><summary><span>STRM 生成</span><small>自动生成、输出目录和手动扫描</small></summary><div className="accordion-content settings-stack"><SettingsToggle label={`自动生成 ${label} STRM`} help="开启后，成功转存到该网盘会自动执行增量扫描并生成 STRM。" value={enabled} onChange={setEnabled} trueLabel="已开启" falseLabel="已关闭" /><SettingsInput label="STRM 输出目录" name="strm_output_root" value={outputRoot} saved={Boolean(config.strm_output_root)} placeholder="/strm" onChange={(_name, value) => setOutputRoot(value)} /><div className="settings-action-strip"><button type="button" className="primary compact-action" disabled={busy !== "" || !connected || !root.trim() || !outputRoot.trim()} onClick={() => void reconcile("full")}>{busy === "full" ? <CircleNotch className="spin" /> : <ArrowClockwise />}全量扫描更新</button><button type="button" className="ghost compact-action" disabled={busy !== "" || !connected || !root.trim() || !outputRoot.trim()} onClick={() => void reconcile("incremental")}>{busy === "incremental" ? <CircleNotch className="spin" /> : <FileVideo />}增量扫描</button></div><p className="settings-help">全量扫描会核对新增、变化和已删除文件；增量扫描只登记当前可见变化，不清理旧记录。两种模式都只读取目录和文件元数据，不下载媒体内容。</p></div></details>
      <details open><summary><span>生成文件范围</span><small>可手动设置正片识别和过滤规则</small></summary><div className="accordion-content settings-stack"><SettingsInput label="视频扩展名（逗号分隔）" name="strm_video_extensions" value={extensions} saved={Boolean(config.strm_video_extensions.length)} onChange={(_name, value) => setExtensions(value)} /><SettingsInput label="排除关键词（逗号分隔）" name="strm_excluded_name_tokens" value={excludedTokens} saved onChange={(_name, value) => setExcludedTokens(value)} /><SettingsInput label="最小文件大小（MiB，0 为不限制）" name="strm_min_file_size_mb" value={minSizeMb} saved onChange={(_name, value) => setMinSizeMb(value.replace(/[^0-9]/g, ""))} /></div></details>
    </div>
    {pickerOpen && <ProviderDirectoryPicker provider="p115" label="115 STRM 来源目录" startPath={root || "/"} onClose={() => setPickerOpen(false)} onSelect={(path) => { setRoot(path); setPickerOpen(false); }} />}
    <div className="settings-footer"><span>{dirty ? `当前有尚未保存的 ${label} STRM 设置` : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || !dirty || !root.trim() || (enabled && !outputRoot.trim())} onClick={() => void savePage()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
  </section>;
}

function DeletionSyncPage({ config, onChanged }: { config: ConfigStatus; onChanged: () => Promise<void> }) {
  const [token, setToken] = useState("");
  const [autoConfirm, setAutoConfirm] = useState(config.emby_deletion_auto_confirm);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const dirty = Boolean(token.trim()) || autoConfirm !== config.emby_deletion_auto_confirm;
  const webhookUrl = `${window.location.origin}/api/integrations/emby/strm-deleted`;
  async function savePage() {
    setBusy(true); setMessage("");
    try {
      await api.saveConfig({ emby_deletion_webhook_token: token, emby_deletion_auto_confirm: autoConfirm, emby_deletion_mode: "trash" });
      setToken(""); await onChanged(); setMessage("删除同步规则已保存。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "删除同步设置保存失败"); }
    finally { setBusy(false); }
  }
  return <section className="workspace-section strm-config-page"><header className="portal-section-head"><div><h2>删除同步</h2><p>根据 STRM 中的精确资产标识联动处理源文件，不按名称猜测。</p></div><span className={`connection-pill ${config.has_emby_deletion_webhook_token ? "connected" : ""}`}><Trash />{config.has_emby_deletion_webhook_token ? "Webhook 已配置" : "未配置"}</span></header>{message && <div className="notice page-notice">{message}</div>}
    <div className="strm-accordion-list"><details open><summary><span>Emby 删除事件</span><small>Webhook 认证与自动执行规则</small></summary><div className="accordion-content settings-stack">
      <SettingsInput label="Webhook 密钥" name="emby_deletion_webhook_token" value={token} saved={config.has_emby_deletion_webhook_token} secret onChange={(_name, value) => setToken(value)} />
      <div className="settings-field compact-select-field"><span>源文件删除方式</span><select value="trash" disabled aria-label="源文件删除方式"><option value="trash">移入 115 回收站</option></select><small>115 当前已验证支持移入回收站；彻底删除未开放。夸克客户端暂未提供经过验证的删除接口。</small></div>
      <SettingsToggle label="收到 Emby 删除事件后自动执行" help="关闭时只创建删除意图；开启后按精确文件 ID 自动移入 115 回收站。建议先关闭完成一次人工联调。" value={autoConfirm} onChange={setAutoConfirm} trueLabel="自动执行" falseLabel="仅记录" />
      <div className="webhook-setup-values"><span>网址</span><code>{webhookUrl}</code><span>内容类型</span><code>application/json</code><span>请求头</span><code>X-MediaIndex-Webhook: 本页保存的密钥</code></div>
      <p className="settings-help">在 Emby 中只勾选媒体删除事件。这里使用 MediaIndex 管理端口，不使用 302 播放端口。</p>
    </div></details></div>
    <div className="settings-footer"><span>{dirty ? "当前有尚未保存的删除同步设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy || !dirty} onClick={() => void savePage()}>{busy && <CircleNotch className="spin" />}{busy ? "保存中" : "保存本页设置"}</button></div>
  </section>;
}
