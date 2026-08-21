import { CheckCircle, CircleNotch, Cloud, HardDrives, QrCode, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import QRCode from "qrcode";

import { api, ApiError, ConfigStatus } from "../../lib/api";
import { buildConfigPayload, CategoryPathSettings, QualityPrioritySettings, SettingsInput } from "../settings/SettingsFormParts";
import { QuarkReadOnlySettings } from "../settings/QuarkReadOnlySettings";
import { SettingsSection } from "../settings/SettingsUi";

type Result = { ok: boolean; message: string } | null;

export function CloudConnectionsPage() {
  const [provider, setProvider] = useState<"quark" | "p115">("quark");
  return (
    <section className="workspace-section">
      <header className="portal-section-head">
        <div><h2>网盘连接</h2><p>登录、更新凭据并验证账号是否可用。这里不执行转存、整理或分享验真。</p></div>
      </header>
      <div className="portal-tabs" role="tablist" aria-label="选择网盘">
        <button type="button" role="tab" aria-selected={provider === "quark"} className={provider === "quark" ? "active" : ""} onClick={() => setProvider("quark")}><Cloud size={17} />夸克网盘</button>
        <button type="button" role="tab" aria-selected={provider === "p115"} className={provider === "p115" ? "active" : ""} onClick={() => setProvider("p115")}><HardDrives size={17} />115 网盘</button>
      </div>
      {provider === "quark" ? <QuarkReadOnlySettings /> : <P115ConnectionSettings />}
    </section>
  );
}

function P115ConnectionSettings() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [method, setMethod] = useState<"open" | "cookie">("open");
  const [cookie, setCookie] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [qrSessionId, setQrSessionId] = useState("");
  const [qrImage, setQrImage] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | "qr" | "switch" | "">("");
  const [result, setResult] = useState<Result>(null);
  const [connectionState, setConnectionState] = useState<"connected" | "failed" | null>(null);

  async function refresh() {
    const next = await api.config();
    setConfig(next);
    setMethod(next.has_p115_open ? next.p115_auth_mode : next.has_p115_cookie ? "cookie" : "open");
  }
  useEffect(() => { void refresh().catch(() => setResult({ ok: false, message: "115 配置读取失败" })); }, []);

  useEffect(() => {
    if (!qrSessionId) return;
    const timer = window.setInterval(() => {
      void api.pollP115OpenQrLogin(qrSessionId).then(async (state) => {
        setResult({ ok: state.ok, message: state.message });
        if (state.status === "success") {
          setQrSessionId(""); setQrImage(""); await refresh(); setConnectionState(null);
        } else if (state.status === "expired" || state.status === "failed") {
          setQrSessionId(""); setQrImage("");
        }
      }).catch((error) => {
        setResult({ ok: false, message: error instanceof ApiError ? error.message : "115 扫码状态读取失败" });
        setQrSessionId(""); setQrImage("");
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [qrSessionId]);

  async function saveCookie() {
    if (!cookie.trim()) return;
    setBusy("save"); setResult(null);
    try {
      await api.saveConfig({ p115_cookie: cookie.trim() });
      setCookie("");
      await refresh();
      setConnectionState(null);
      setResult({ ok: true, message: "115 Cookie 已保存在本机服务端。" });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError ? error.message : "115 Cookie 保存失败" });
    } finally { setBusy(""); }
  }

  async function saveOpenTokens() {
    if (!accessToken.trim() || !refreshToken.trim()) return;
    setBusy("save"); setResult(null);
    try {
      await api.saveConfig({ p115_open_access_token: accessToken.trim(), p115_open_refresh_token: refreshToken.trim(), p115_auth_mode: "open" });
      setAccessToken(""); setRefreshToken(""); await refresh(); setConnectionState(null);
      setResult({ ok: true, message: "115 文件接口授权已保存在本机服务端。" });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError ? error.message : "115 文件接口授权保存失败" });
    } finally { setBusy(""); }
  }

  async function startOpenLogin() {
    setBusy("qr"); setResult(null);
    try {
      const response = await api.startP115OpenQrLogin();
      if (!response.ok || !response.session_id || !response.qr_url) throw new Error(response.message || "115 未返回扫码会话");
      setQrImage(await QRCode.toDataURL(response.qr_url, { width: 248, margin: 2, errorCorrectionLevel: "M" }));
      setQrSessionId(response.session_id);
      setResult({ ok: true, message: "请使用 115 App 扫码并确认文件接口授权。" });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError || error instanceof Error ? error.message : "115 扫码会话创建失败" });
    } finally { setBusy(""); }
  }

  async function activate(next: "open" | "cookie") {
    if (!config || (next === "open" && !config.has_p115_open) || (next === "cookie" && !config.has_p115_cookie)) return;
    setBusy("switch"); setResult(null);
    try { await api.saveConfig({ p115_auth_mode: next }); await refresh(); setMethod(next); setConnectionState(null); setResult({ ok: true, message: `已切换为 ${next === "open" ? "115 文件接口" : "Cookie 兼容"}模式。` }); }
    catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "115 模式切换失败" }); }
    finally { setBusy(""); }
  }

  async function testConnection() {
    setBusy("test"); setResult(null);
    try {
      const response = await api.testP115();
      setConnectionState(response.ok ? "connected" : "failed");
      setResult({ ok: response.ok, message: response.message });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError ? error.message : "115 连接验证失败" });
    } finally { setBusy(""); }
  }

  if (!config) return <div className="workspace-loading"><CircleNotch className="spin" />正在读取 115 连接状态</div>;
  const connected = config.has_p115_cookie || config.has_p115_open;
  const connectionLabel = connectionState === "connected"
    ? "115 已连接"
    : connectionState === "failed"
      ? "115 连接验证失败"
      : connected
        ? "115 凭据已保存，尚未验证"
        : "115 尚未连接";
  return (
    <div className="provider-module-grid connection-settings-grid p115-connection-settings">
      <SettingsSection title="115 连接方式" body="文件接口模式用于目录、上传、下载、整理和 302；Cookie 兼容模式继续用于分享链接读取。两份凭据可以同时保留。">
        <div className={`connection-summary ${connectionState === "connected" ? "connected" : connectionState === "failed" ? "error" : ""}`}>
          {connectionState === "connected" ? <CheckCircle size={21} weight="fill" /> : <WarningCircle size={21} />}
          <div><strong>{connectionLabel}</strong><span>当前执行模式：{config.p115_auth_mode === "open" ? "文件接口" : "Cookie 兼容"} · 文件接口 {config.has_p115_open ? "已授权" : "未授权"} · Cookie {config.has_p115_cookie ? "已保存" : "未保存"}</span></div>
        </div>
        <div className="connection-method-switch" role="tablist" aria-label="115 连接方式">
          <button type="button" role="tab" aria-selected={method === "open"} className={method === "open" ? "active" : ""} onClick={() => setMethod("open")}>文件接口（推荐）</button>
          <button type="button" role="tab" aria-selected={method === "cookie"} className={method === "cookie" ? "active" : ""} onClick={() => setMethod("cookie")}>Cookie 兼容</button>
        </div>
      </SettingsSection>

      {method === "open" && <SettingsSection title="115 文件接口授权" body="使用 115 官方 Open 设备码授权。授权令牌只保存到本机服务端，浏览器不会收到或回显令牌。">
        {qrImage && <div className="cloud-login-qr"><img src={qrImage} alt="115 文件接口授权二维码" /><strong>使用 115 App 扫码</strong><span>扫码后请在 App 中确认授权</span></div>}
        <div className="settings-action-strip">
          <button type="button" className="primary compact-action" disabled={busy !== "" || Boolean(qrSessionId)} onClick={() => void startOpenLogin()}>{busy === "qr" || qrSessionId ? <CircleNotch className="spin" /> : <QrCode />}{qrSessionId ? "等待扫码确认" : "扫码授权文件接口"}</button>
          {config.has_p115_open && config.p115_auth_mode !== "open" && <button type="button" className="ghost compact-action" disabled={busy !== ""} onClick={() => void activate("open")}>设为执行模式</button>}
        </div>
        <details className="manual-token-entry"><summary>已有令牌，手工填写</summary><div className="settings-stack">
          <SettingsInput label="Access Token" name="p115_open_access_token" value={accessToken} saved={config.has_p115_open} secret onChange={(_name, value) => setAccessToken(value)} />
          <SettingsInput label="Refresh Token" name="p115_open_refresh_token" value={refreshToken} saved={config.has_p115_open} secret onChange={(_name, value) => setRefreshToken(value)} />
          <button type="button" className="ghost compact-action" disabled={busy !== "" || !accessToken.trim() || !refreshToken.trim()} onClick={() => void saveOpenTokens()}>保存文件接口令牌</button>
        </div></details>
      </SettingsSection>}

      {method === "cookie" && <SettingsSection title="115 Cookie 兼容" body="手工 Cookie 用于 115 分享链接验真和兼容接口；保存 Cookie 不再删除已经存在的文件接口授权。">
        <SettingsInput label="115 Cookie" name="p115_cookie" value={cookie} saved={config.has_p115_cookie} secret onChange={(_name, value) => setCookie(value)} placeholder="UID=…; CID=…; SEID=…" />
        <div className="settings-action-strip">
          <button type="button" className="ghost compact-action" disabled={busy !== "" || !cookie.trim()} onClick={() => void saveCookie()}>{busy === "save" && <CircleNotch className="spin" />}保存 Cookie</button>
          {config.has_p115_cookie && config.p115_auth_mode !== "cookie" && <button type="button" className="ghost compact-action" disabled={busy !== ""} onClick={() => void activate("cookie")}>设为兼容模式</button>}
        </div>
      </SettingsSection>}

      <SettingsSection title="连接验证" body="按当前执行模式读取 115 根目录，不上传、不移动、不删除文件。">
        <div className="settings-action-strip"><button type="button" className="primary compact-action" disabled={busy !== "" || !connected} onClick={() => void testConnection()}>{busy === "test" ? <CircleNotch className="spin" /> : <ShieldCheck />}验证当前模式</button></div>
        {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
      </SettingsSection>
    </div>
  );
}

export function TransferRulesPage() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [provider, setProvider] = useState<"common" | "quark" | "p115">("common");
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<Result>(null);

  useEffect(() => { void api.config().then(setConfig).catch(() => setMessage({ ok: false, message: "整理规则读取失败" })); }, []);
  const update = (name: string, value: string) => setForm((current) => ({ ...current, [name]: value }));

  async function save() {
    setSaving(true); setMessage(null);
    try {
      await api.saveConfig(buildConfigPayload(form));
      setConfig(await api.config());
      setForm({});
      setMessage({ ok: true, message: "转存和整理规则已保存，新建任务会使用这份规则。" });
    } catch (error) {
      setMessage({ ok: false, message: error instanceof ApiError ? error.message : "规则保存失败" });
    } finally { setSaving(false); }
  }

  if (!config) return <div className="workspace-loading"><CircleNotch className="spin" />正在读取整理规则</div>;
  const rootName = provider === "p115" ? "p115_root_path" : "quark_root_path";
  const stagingName = provider === "p115" ? "p115_staging_path" : "quark_staging_path";
  const rootValue = provider === "p115" ? form[rootName] ?? config.p115_root_path : form[rootName] ?? config.quark_root_path;
  const stagingValue = provider === "p115" ? form[stagingName] ?? config.p115_staging_path : form[stagingName] ?? config.quark_staging_path;
  return (
    <section className="workspace-section">
      <header className="portal-section-head"><div><h2>转存和整理规则</h2><p>定义新任务保存到哪里、如何分类和命名。账号登录不在本页。</p></div></header>
      <div className="portal-tabs" role="tablist" aria-label="选择网盘规则">
        <button type="button" role="tab" aria-selected={provider === "common"} className={provider === "common" ? "active" : ""} onClick={() => setProvider("common")}>通用规则</button>
        <button type="button" role="tab" aria-selected={provider === "quark"} className={provider === "quark" ? "active" : ""} onClick={() => setProvider("quark")}>夸克规则</button>
        <button type="button" role="tab" aria-selected={provider === "p115"} className={provider === "p115" ? "active" : ""} onClick={() => setProvider("p115")}>115 规则</button>
      </div>
      {message && <div className={`settings-inline-result ${message.ok ? "success" : "error"}`}>{message.message}</div>}
      <div className="rules-layout">
        {provider === "common" && <>
        <SettingsSection title="分类路径" body="所有网盘共用一套媒体分类；单个网盘只负责选择自己的保存根目录。">
          <CategoryPathSettings config={config} form={form} onChange={setForm} provider="common" />
        </SettingsSection>
        <SettingsSection title="命名与版本" body="TMDB 核对完成后，所有转存和整理任务都使用这套模板生成目标名称。">
          <SettingsInput label="媒体目录模板" name="media_folder_naming_rule" value={form.media_folder_naming_rule ?? config.media_folder_naming_rule} saved placeholder="{title} ({year})" onChange={update} showSavedValue />
          <SettingsInput label="季目录模板" name="season_folder_naming_rule" value={form.season_folder_naming_rule ?? config.season_folder_naming_rule} saved placeholder="Season {season:02d}" onChange={update} showSavedValue />
          <SettingsInput label="电影文件模板" name="movie_naming_rule" value={form.movie_naming_rule ?? config.movie_naming_rule} saved placeholder="{title} ({year})" onChange={update} showSavedValue />
          <SettingsInput label="剧集文件模板" name="episode_naming_rule" value={form.episode_naming_rule ?? config.episode_naming_rule} saved placeholder="{title} - S{season:02d}E{episode:02d}" onChange={update} showSavedValue />
        </SettingsSection>
        <SettingsSection title="质量优先级" body="多个候选资源都通过验真时，按顺序选择更合适的版本。">
          <QualityPrioritySettings config={config} form={form} onChange={update} />
        </SettingsSection>
        </>}
        {provider !== "common" && <SettingsSection title={`${provider === "p115" ? "115" : "夸克"} 保存位置`} body="这里只设置该网盘的根目录和任务暂存区；分类、命名和质量规则继承通用规则。">
          <SettingsInput label="保存根目录" name={rootName} value={rootValue} saved placeholder="/strm" onChange={update} showSavedValue />
          <SettingsInput label="任务暂存目录" name={stagingName} value={stagingValue} saved placeholder="/.media-index-staging" onChange={update} showSavedValue />
          {provider === "p115" && <SettingsInput label="本地兼容目录" name="p115_local_path" value={form.p115_local_path ?? config.p115_local_path} saved placeholder="/downloads" onChange={update} showSavedValue helpTooltip="只供明确需要本地文件的旧兼容任务使用；流式跨盘任务不会在这里留下完整文件。" />}
        </SettingsSection>}
      </div>
      <div className="settings-footer workspace-rules-footer">
        <span>{Object.keys(form).length ? "当前有尚未保存的规则修改" : "规则已与服务端同步"}</span>
        <button type="button" className="primary compact-action" disabled={saving || Object.keys(form).length === 0} onClick={() => void save()}>
          {saving && <CircleNotch className="spin" />}
          {saving ? "保存中" : "保存规则"}
        </button>
      </div>
    </section>
  );
}
