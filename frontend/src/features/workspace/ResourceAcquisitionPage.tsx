import { Broadcast, CheckCircle, CircleNotch, MagnifyingGlass, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ApiError, ConfigStatus } from "../../lib/api";
import { SettingsInput } from "../settings/SettingsFormParts";
import { SettingsSection } from "../settings/SettingsUi";
import { ChannelWorkspace } from "../cloud/ChannelWorkspace";

export function ResourceAcquisitionPage() {
  const [source, setSource] = useState<"pansou" | "telegram">("pansou");
  return <section className="workspace-section resource-acquisition-page">
    <header className="portal-section-head"><div><h2>资源获取</h2><p>PanSou 负责聚合搜索，TG 负责持续追踪频道；两套来源和过滤规则完全独立。</p></div></header>
    <div className="resource-source-tabs" role="tablist" aria-label="资源获取来源">
      <button type="button" role="tab" aria-selected={source === "pansou"} className={source === "pansou" ? "active" : ""} onClick={() => setSource("pansou")}><span><MagnifyingGlass weight="duotone" /></span><span><strong>PanSou 聚合搜索</strong><small>为发现、愿望单和追更提供候选</small></span></button>
      <button type="button" role="tab" aria-selected={source === "telegram"} className={source === "telegram" ? "active" : ""} onClick={() => setSource("telegram")}><span><Broadcast weight="duotone" /></span><span><strong>TG 频道追踪</strong><small>按频道独立过滤并转存到云下载</small></span></button>
    </div>
    <div role="tabpanel">{source === "pansou" ? <PansouSourceSettings /> : <ChannelWorkspace />}</div>
  </section>;
}

function PansouSourceSettings() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [url, setUrl] = useState("");
  const [excludeKeywords, setExcludeKeywords] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | "">("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  async function refresh() {
    const next = await api.config();
    setConfig(next);
    setUrl(next.pansou_url || "");
    setExcludeKeywords(next.pansou_exclude_keywords || "");
  }
  useEffect(() => { void refresh().catch(() => setResult({ ok: false, message: "PanSou 配置读取失败" })); }, []);

  async function save() {
    setBusy("save"); setResult(null);
    try { await api.saveConfig({ pansou_url: url.trim(), pansou_exclude_keywords: excludeKeywords.trim() }); await refresh(); setResult({ ok: true, message: "PanSou 地址与独立反向关键词已保存。" }); }
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
      <SettingsInput label="资源反向关键词" name="pansou_exclude_keywords" value={excludeKeywords} saved={Boolean(config.pansou_exclude_keywords)} placeholder={config.pansou_exclude_keywords || "预告, 花絮, 低清"} onChange={(_name, value) => setExcludeKeywords(value)} helpTooltip="仅过滤 PanSou 搜索结果，多个关键词用逗号分隔；与 TG 频道规则完全独立。" />
      {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
    </SettingsSection>
    <div className="settings-footer"><span>{url.trim() || excludeKeywords.trim() ? "当前有尚未保存的资源来源设置" : "本页设置已与服务端同步"}</span><button type="button" className="primary compact-action" disabled={busy !== "" || (!url.trim() && !excludeKeywords.trim())} onClick={() => void save()}>{busy === "save" && <CircleNotch className="spin" />}{busy === "save" ? "保存中" : "保存本页设置"}</button></div>
  </div>;
}
