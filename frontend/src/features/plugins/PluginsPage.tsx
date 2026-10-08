import { useEffect, useState } from "react";
import { api, ApiError, type PluginInfo } from "../../lib/api";
import { SettingsSection } from "../../components/settings/SettingsUi";

export function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { let active = true; api.plugins().then(result => { if (active) setPlugins(result.plugins); }).catch(() => { if (active) setMessage("插件列表读取失败，请重新打开页面重试"); }); return () => { active = false; }; }, []);
  async function toggle(plugin: PluginInfo) {
    setBusy(true); setMessage("");
    try { setPlugins((await api.setPluginState(plugin.id, !plugin.enabled)).plugins); }
    catch (error) { setMessage(error instanceof ApiError ? error.message : "插件状态保存失败"); }
    finally { setBusy(false); }
  }
  return <section className="workspace-section">
    <header className="portal-section-head"><div><h2>插件</h2><p>按需启用扩展能力。播放优化的计算任务由独立容器承担。</p></div></header>
    {message && <p role="alert" className="settings-inline-result error">{message}</p>}
    {!plugins && !message && <p role="status">正在读取插件…</p>}
    {plugins?.map(plugin => <SettingsSection key={plugin.id} title={plugin.name} body={plugin.description}>
      <div className="settings-action-strip"><button type="button" className="primary compact-action" role="switch" aria-checked={plugin.enabled} disabled={busy} onClick={() => void toggle(plugin)}>{plugin.enabled ? "已启用 · 点击停用" : "已停用 · 点击启用"}</button></div>
      <p className="settings-help">当前能力：{plugin.features.join("、")}</p>
      <p className="settings-help">开发中：{plugin.plannedFeatures.join("、")}</p>
      {plugin.configurationRequired && <p role="status">尚未配置独立转码容器；启用开关不会自动安装或启动容器。</p>}
    </SettingsSection>)}
  </section>;
}
