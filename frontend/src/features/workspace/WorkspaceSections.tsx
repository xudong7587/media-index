import { CheckCircle, CircleNotch, Cloud, HardDrives, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ApiError, ConfigStatus } from "../../lib/api";
import { buildConfigPayload, CategoryPathSettings, QualityPrioritySettings, SettingsInput, SettingsToggle } from "../settings/SettingsFormParts";
import { QuarkReadOnlySettings } from "../settings/QuarkReadOnlySettings";
import { SettingsSection } from "../settings/SettingsUi";
import { ProviderDirectoryPicker } from "../openlist/OpenListSettingsTools";

type Result = { ok: boolean; message: string } | null;

export function CloudConnectionsPage() {
  const [provider, setProvider] = useState<"quark" | "p115">("quark");
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [busy, setBusy] = useState<"quark" | "p115" | "">("");
  const [activationResult, setActivationResult] = useState<Result>(null);

  async function refreshProviders() {
    setConfig(await api.config());
  }

  useEffect(() => { void refreshProviders().catch(() => setActivationResult({ ok: false, message: "网盘启用状态读取失败" })); }, []);

  async function toggleProvider(target: "quark" | "p115") {
    if (!config) return;
    const current = (["quark", "p115"] as const).filter((item) => config.enabled_providers.includes(item));
    const enabled = current.includes(target);
    const next = enabled ? current.filter((item) => item !== target) : [...current, target];
    if (!next.length) {
      setActivationResult({ ok: false, message: "至少保留一个网盘作为执行端" });
      return;
    }
    setBusy(target); setActivationResult(null);
    try {
      await api.saveConfig({
        enabled_providers: next,
        default_provider: next.includes(config.default_provider as "quark" | "p115") ? config.default_provider : next[0],
      });
      await refreshProviders();
      window.dispatchEvent(new Event("mediaindex:providers-changed"));
      setActivationResult({ ok: true, message: `${target === "p115" ? "115" : "夸克"}已${enabled ? "停用" : "启用"}；发现、愿望单和追更将立即按新状态执行。` });
    } catch (error) {
      setActivationResult({ ok: false, message: error instanceof ApiError ? error.message : "网盘启用状态保存失败" });
    } finally { setBusy(""); }
  }

  return (
    <section className="workspace-section">
      <header className="portal-section-head">
        <div><h2>网盘连接</h2><p>登录、更新凭据并验证账号是否可用。这里不执行转存、整理或分享验真。</p></div>
      </header>
      <section className="provider-activation-panel" aria-label="网盘执行开关">
        <div><strong>网盘执行开关</strong><p>关闭后不会参与发现转存、愿望单或智能追更；连接凭据和历史任务不会删除。</p></div>
        <div className="provider-activation-actions">
          {(["quark", "p115"] as const).map((item) => {
            const active = Boolean(config?.enabled_providers.includes(item));
            return <button type="button" role="switch" aria-checked={active} className={active ? "active" : ""} disabled={!config || Boolean(busy)} onClick={() => void toggleProvider(item)} key={item}>
              {busy === item ? <CircleNotch className="spin" /> : item === "quark" ? <Cloud /> : <HardDrives />}
              <span>{item === "quark" ? "夸克" : "115"}</span><em>{active ? "已启用" : "已停用"}</em>
            </button>;
          })}
        </div>
      </section>
      {activationResult && <div className={`settings-inline-result ${activationResult.ok ? "success" : "error"}`}>{activationResult.message}</div>}
      <div className="portal-tabs" role="tablist" aria-label="选择网盘">
        <button type="button" role="tab" aria-selected={provider === "quark"} className={provider === "quark" ? "active" : ""} onClick={() => setProvider("quark")}><Cloud size={17} />夸克网盘</button>
        <button type="button" role="tab" aria-selected={provider === "p115"} className={provider === "p115" ? "active" : ""} onClick={() => setProvider("p115")}><HardDrives size={17} />115 网盘</button>
      </div>
      {provider === "quark" ? <QuarkReadOnlySettings onChanged={() => void refreshProviders()} /> : <P115ConnectionSettings onChanged={() => void refreshProviders()} />}
    </section>
  );
}

function P115ConnectionSettings({ onChanged }: { onChanged?: () => void }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [cookie, setCookie] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | "">("");
  const [result, setResult] = useState<Result>(null);
  const [connectionState, setConnectionState] = useState<"connected" | "failed" | null>(null);

  async function refresh() {
    const next = await api.config();
    setConfig(next);
    onChanged?.();
  }
  useEffect(() => { void refresh().catch(() => setResult({ ok: false, message: "115 配置读取失败" })); }, []);

  async function saveCookie() {
    if (!cookie.trim()) return;
    setBusy("save"); setResult(null);
    try {
      await api.saveConfig({ p115_cookie: cookie.trim(), p115_auth_mode: "cookie" });
      setCookie("");
      await refresh();
      setConnectionState(null);
      setResult({ ok: true, message: "115 Cookie 已保存在本机服务端。" });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError ? error.message : "115 Cookie 保存失败" });
    } finally { setBusy(""); }
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
  const connected = config.has_p115_cookie;
  const connectionLabel = connectionState === "connected"
    ? "115 已连接"
    : connectionState === "failed"
      ? "115 Cookie 验证失败"
      : connected
        ? "115 凭据已保存，尚未验证"
        : "115 尚未连接";
  return (
    <div className="provider-module-grid connection-settings-grid p115-connection-settings">
      <SettingsSection title="115 连接" body="MediaIndex 原生 115 统一使用 Cookie 读取目录、验真和执行操作。">
        <div className={`connection-summary ${connectionState === "connected" ? "connected" : connectionState === "failed" ? "error" : ""}`}>
          {connectionState === "connected" ? <CheckCircle size={21} weight="fill" /> : <WarningCircle size={21} />}
          <div><strong>{connectionLabel}</strong><span>当前执行模式：Cookie · Cookie {config.has_p115_cookie ? "已保存" : "未保存"}</span></div>
        </div>
      </SettingsSection>
      <SettingsSection title="115 Cookie" body="Cookie 用于目录读取、分享链接验真和 115 操作。">
        <SettingsInput label="115 Cookie" name="p115_cookie" value={cookie} saved={config.has_p115_cookie} secret onChange={(_name, value) => setCookie(value)} placeholder="UID=…; CID=…; SEID=…" action={<button type="button" className="ghost compact-action" disabled={busy !== "" || !cookie.trim()} onClick={() => void saveCookie()}>{busy === "save" && <CircleNotch className="spin" />}保存 Cookie</button>} />
      </SettingsSection>

      <SettingsSection title="连接验证" body="使用 Cookie 读取 115 根目录，不上传、不移动、不删除文件。">
        <div className="settings-action-strip"><button type="button" className="primary compact-action" disabled={busy !== "" || !connected} onClick={() => void testConnection()}>{busy === "test" ? <CircleNotch className="spin" /> : <ShieldCheck />}验证 Cookie</button></div>
        {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
      </SettingsSection>
    </div>
  );
}

export function TransferRulesPage({ initialProvider = "common" }: { initialProvider?: "common" | "quark" | "p115" }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [provider, setProvider] = useState<"common" | "quark" | "p115">(initialProvider);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<Result>(null);
  const [directoryPickerOpen, setDirectoryPickerOpen] = useState(false);

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
  const cloudDownloadName = provider === "p115" ? "p115_cloud_download_path" : "quark_cloud_download_path";
  const cloudDownloadValue = provider === "p115"
    ? form[cloudDownloadName] ?? config.p115_cloud_download_path
    : form[cloudDownloadName] ?? config.quark_cloud_download_path;
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
          <SettingsToggle label="剧集按季分目录" value={(form.season_subdirectory_enabled ?? String(config.season_subdirectory_enabled)) === "true"} onChange={(value) => update("season_subdirectory_enabled", String(value))} trueLabel="分季" falseLabel="不分季" />
        </SettingsSection>
        <SettingsSection title="质量优先级" body="多个候选资源都通过验真时，按顺序选择更合适的版本。">
          <QualityPrioritySettings config={config} form={form} onChange={update} />
          <SettingsInput
            label="排除关键词"
            name="resource_excluded_keywords"
            value={form.resource_excluded_keywords ?? config.resource_excluded_keywords.join(", ")}
            saved
            placeholder="TC, TS, CAM, 抢先, 预览版, 480p"
            onChange={update}
            showSavedValue
            help="候选标题或实际视频文件名命中任一关键词时直接排除。支持中英文逗号或换行，可自行增删 480p 等版本字段。"
          />
        </SettingsSection>
        </>}
        {provider !== "common" && <SettingsSection title={`${provider === "p115" ? "115" : "夸克"} 保存位置`} body="这里只设置该网盘的根目录和任务暂存区；分类、命名和质量规则继承通用规则。">
          <SettingsInput label="保存根目录" name={rootName} value={rootValue} saved placeholder="/strm" onChange={update} showSavedValue />
          <SettingsInput label="任务暂存目录" name={stagingName} value={stagingValue} saved placeholder="/.media-index-staging" onChange={update} showSavedValue />
          <SettingsInput label="云下载目录" name={cloudDownloadName} value={cloudDownloadValue} saved placeholder={`${rootValue}/云下载`} onChange={update} showSavedValue help="交互渠道和发现页直接粘贴的链接会保存到这里。夸克链接使用夸克目录，115、磁力、电驴及普通下载链接使用 115 目录。" action={<button type="button" className="ghost compact-action" onClick={() => setDirectoryPickerOpen(true)}>选择目录</button>} />
          {provider === "p115" && <SettingsInput label="本地兼容目录" name="p115_local_path" value={form.p115_local_path ?? config.p115_local_path} saved placeholder="/downloads" onChange={update} showSavedValue helpTooltip="只供明确需要本地文件的旧兼容任务使用；流式跨盘任务不会在这里留下完整文件。" />}
        </SettingsSection>}
      </div>
      {directoryPickerOpen && provider !== "common" && <ProviderDirectoryPicker provider={provider} label={`${provider === "p115" ? "115" : "夸克"}云下载目录`} startPath={cloudDownloadValue || rootValue || "/"} onClose={() => setDirectoryPickerOpen(false)} onSelect={(path) => { update(cloudDownloadName, path); setDirectoryPickerOpen(false); }} />}
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
