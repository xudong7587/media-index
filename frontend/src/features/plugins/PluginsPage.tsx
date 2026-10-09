import { useEffect, useState } from "react";
import { api, ApiError, type PluginInfo } from "../../lib/api";
import { SettingsSection } from "../../components/settings/SettingsUi";

export function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { let active = true; api.plugins().then(result => { if (active) setPlugins(result.plugins); }).catch(() => { if (active) setMessage("转码服务读取失败，请重新打开页面重试"); }); return () => { active = false; }; }, []);
  async function toggle(plugin: PluginInfo) {
    setBusy(true); setMessage("");
    try { setPlugins((await api.setPluginState(plugin.id, !plugin.enabled)).plugins); }
    catch (error) { setMessage(error instanceof ApiError ? error.message : "转码服务状态保存失败"); }
    finally { setBusy(false); }
  }
  return <section className="workspace-section">
    <header className="portal-section-head"><div><h2>转码服务</h2><p>MediaIndex 管理播放会话，配套转码容器输出 HLS 视频流。</p></div></header>
    {message && <p role="alert" className="settings-inline-result error">{message}</p>}
    {!plugins && !message && <p role="status">正在读取转码服务…</p>}
    {plugins?.filter(plugin => plugin.id === "playback-optimizer").map(plugin => <SettingsSection key={plugin.id} title="播放优化" body="双容器部署，开启后可选择分辨率和码率进行流式转码。原画继续走 302；关闭服务会阻止新转码会话，已有会话自然结束。">
      <div className="settings-action-strip"><button type="button" className="primary compact-action" role="switch" aria-checked={plugin.enabled} disabled={busy} onClick={() => void toggle(plugin)}>{plugin.enabled ? "已启用 · 点击停用" : "已停用 · 点击启用"}</button></div>
      <p className="settings-help">当前能力：{plugin.features.join("、")}</p>
      <p className="settings-help">开发中：{plugin.plannedFeatures.join("、")}</p>
      {plugin.configurationRequired && <p role="status">尚未配置独立转码容器；启用开关不会自动安装或启动容器。</p>}
    </SettingsSection>)}
  </section>;
}
