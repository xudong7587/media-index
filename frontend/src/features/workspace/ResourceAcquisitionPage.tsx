import { Broadcast, CheckCircle, CircleNotch, MagnifyingGlass, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ApiError, ConfigStatus } from "../../lib/api";
import { ChannelWorkspace } from "../cloud/ChannelWorkspace";
import { SettingsInput, SettingsToggle } from "../settings/SettingsFormParts";
import { SettingsSection } from "../settings/SettingsUi";
import { PansouChannelImport } from "./PansouChannelImport";

export function ResourceAcquisitionPage() {
  const [source, setSource] = useState<"pansou" | "telegram">("pansou");
  return <section className="workspace-section resource-acquisition-page">
    <header className="portal-section-head"><div><h2>资源获取</h2><p>管理候选资源从哪里来；是否转存仍由发现、愿望单、智能追更与统一规则决定。</p></div></header>
    <div className="portal-tabs" role="tablist" aria-label="资源来源">
      <button type="button" role="tab" aria-selected={source === "pansou"} className={source === "pansou" ? "active" : ""} onClick={() => setSource("pansou")}><MagnifyingGlass />PanSou 聚合搜索</button>
      <button type="button" role="tab" aria-selected={source === "telegram"} className={source === "telegram" ? "active" : ""} onClick={() => setSource("telegram")}><Broadcast />TG 频道源</button>
    </div>
    {source === "pansou" ? <PansouSourceSettings /> : <TelegramSourceSettings />}
  </section>;
}

function TelegramSourceSettings() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [token, setToken] = useState("");
  const [apiHost, setApiHost] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  async function refresh() {
    const next = await api.config();
    setConfig(next); setEnabled(next.telegram_channel_source_enabled);
  }
  useEffect(() => { void refresh().catch(() => setResult({ ok: false, message: "Telegram 来源配置读取失败" })); }, []);

  async function save() {
    setBusy(true); setResult(null);
    try {
      const payload: Record<string, string | boolean> = { telegram_channel_source_enabled: enabled };
      if (token.trim()) payload.telegram_bot_token = token.trim();
      if (apiHost.trim()) payload.telegram_api_host = apiHost.trim();
      await api.saveConfig(payload); setToken(""); setApiHost(""); await refresh();
      setResult({ ok: true, message: "Telegram Bot 连接已保存；公开频道拉取不依赖 Bot。" });
    } catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "Telegram 来源保存失败" }); }
    finally { setBusy(false); }
  }
  async function testBot() {
    setBusy(true); setResult(null);
    try { setResult(await api.testTelegramBot()); }
    catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "Telegram Bot 连接失败" }); }
    finally { setBusy(false); }
  }

  if (!config) return <div className="workspace-loading"><CircleNotch className="spin" />正在读取 Telegram 来源</div>;
  const ready = config.telegram_channel_source_enabled && config.has_telegram_token;
  return <div className="telegram-source-stack">
    <SettingsSection title="Telegram Bot 连接（私有频道 / 交互）" body="公开频道会在发现、愿望单或追更实际搜索资源时按需更新；Bot 只用于接收私有频道新消息以及 Telegram 交互。">
      <div className={`connection-summary ${ready ? "connected" : ""}`}>{ready ? <CheckCircle weight="fill" /> : <WarningCircle />}<div><strong>{ready ? "TG 频道接收已启用" : "TG 频道接收未就绪"}</strong><span>{config.has_telegram_token ? "Bot Token 已保存" : "请保存 Bot Token"} · {config.telegram_api_host || "https://api.telegram.org"}</span></div></div>
      <SettingsInput label="Bot Token" name="telegram_bot_token" value={token} saved={config.has_telegram_token} secret onChange={(_name, value) => setToken(value)} />
      <details className="settings-advanced-fields">
        <summary>高级连接设置</summary>
        <p className="settings-field-help">一般无需修改。这里填写 Telegram API 服务地址，不是 Bot 编号；默认使用 https://api.telegram.org。</p>
        <SettingsInput label="Telegram API 服务地址" name="telegram_api_host" value={apiHost} saved={Boolean(config.telegram_api_host)} placeholder={config.telegram_api_host || "https://api.telegram.org"} showSavedValue onChange={(_name, value) => setApiHost(value)} />
      </details>
      <SettingsToggle label="接收频道消息" value={enabled} onChange={setEnabled} trueLabel="已启用" falseLabel="已停用" />
      <div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy || !config.has_telegram_token} onClick={() => void testBot()}><ShieldCheck />测试 Bot</button></div>
      {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
    </SettingsSection>
    <ChannelWorkspace />
    <div className="settings-footer"><span>{token.trim() || apiHost.trim() || enabled !== config.telegram_channel_source_enabled ? "当前有尚未保存的 Telegram 来源设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy || (!token.trim() && !config.has_telegram_token) || (!token.trim() && !apiHost.trim() && enabled === config.telegram_channel_source_enabled)} onClick={() => void save()}>{busy && <CircleNotch className="spin" />}{busy ? "保存中" : "保存本页设置"}</button></div>
  </div>;
}

function PansouSourceSettings() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | "">("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  async function refresh() {
    setConfig(await api.config());
  }
  useEffect(() => { void refresh().catch(() => setResult({ ok: false, message: "PanSou 配置读取失败" })); }, []);

  async function save() {
    setBusy("save"); setResult(null);
    try { await api.saveConfig({ pansou_url: url.trim() }); setUrl(""); await refresh(); setResult({ ok: true, message: "PanSou 地址已保存。" }); }
    catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "PanSou 保存失败" }); }
    finally { setBusy(""); }
  }
  async function test() {
    setBusy("test"); setResult(null);
    try { const response = await api.testPansou(); setResult({ ok: response.ok, message: response.message }); }
    catch (error) { setResult({ ok: false, message: error instanceof ApiError ? error.message : "PanSou 连接失败" }); }
    finally { setBusy(""); }
  }
  if (!config) return <div className="workspace-loading"><CircleNotch className="spin" />正在读取 PanSou 来源</div>;
  return <div className="provider-module-grid connection-settings-grid single-source-settings">
    <SettingsSection title="PanSou 聚合搜索" body="发现详情、愿望单和追更任务使用这项服务检索候选分享；搜索只提供候选，不直接写入网盘。">
      <div className={`connection-summary ${config.has_pansou ? "connected" : ""}`}>{config.has_pansou ? <CheckCircle weight="fill" /> : <WarningCircle />}<div><strong>{config.has_pansou ? "PanSou 已配置" : "PanSou 尚未配置"}</strong><span>{config.pansou_url || "请填写服务地址"}</span></div></div>
      <SettingsInput label="PanSou 地址" name="pansou_url" value={url} saved={Boolean(config.pansou_url)} placeholder={config.pansou_url || "http://pansou-host:port"} onChange={(_name, value) => setUrl(value)} showSavedValue />
      <div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy !== "" || !config.has_pansou} onClick={() => void test()}>{busy === "test" ? <CircleNotch className="spin" /> : <ShieldCheck />}测试搜索</button></div>
      {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
    </SettingsSection>
    <PansouChannelImport />
    <div className="settings-footer"><span>{url.trim() ? "当前有尚未保存的 PanSou 来源设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || !url.trim()} onClick={() => void save()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
  </div>;
}
