import { CheckCircle, CircleNotch, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ApiError, ConfigStatus } from "../../lib/api";
import { SettingsInput } from "../settings/SettingsFormParts";
import { SettingsSection } from "../settings/SettingsUi";

export function ResourceAcquisitionPage() {
  return <section className="workspace-section resource-acquisition-page">
    <header className="portal-section-head"><div><h2>资源获取</h2><p>管理候选资源从哪里来；是否转存仍由发现、愿望单、智能追更与统一规则决定。</p></div></header>
    <PansouSourceSettings />
  </section>;
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
      <SettingsInput label="PanSou 地址" name="pansou_url" value={url} saved={Boolean(config.pansou_url)} placeholder={config.pansou_url || "http://pansou-host:port"} onChange={(_name, value) => setUrl(value)} showSavedValue action={<button type="button" className="ghost compact-action" disabled={busy !== "" || !config.has_pansou} onClick={() => void test()}>{busy === "test" ? <CircleNotch className="spin" /> : <ShieldCheck />}测试搜索</button>} />
      {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
    </SettingsSection>
    <div className="settings-footer"><span>{url.trim() ? "当前有尚未保存的 PanSou 来源设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || !url.trim()} onClick={() => void save()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
  </div>;
}
