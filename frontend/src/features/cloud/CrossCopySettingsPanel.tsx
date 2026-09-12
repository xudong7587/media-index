import { CircleNotch, FloppyDisk } from "@phosphor-icons/react";
import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type CrossCopyConfig } from "../../lib/api";
import { SettingsInput, SettingsToggle } from "../../components/settings/SettingsFields";
import { OpenListDirectoryPicker, SettingsSection } from "../../components/settings/SettingsUi";

export function CrossCopySettingsPanel({ config, onSaved }: {
  config: CrossCopyConfig; onSaved: (next: CrossCopyConfig) => void;
}) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [picker, setPicker] = useState<{ key: string; label: string } | null>(null);
  const dirty = Object.keys(form).length > 0;
  const route = (form.cross_copy_transport || config.cross_copy_transport) as "openlist" | "cd2";
  const label = route === "cd2" ? "CD2" : "OpenList";
  const saved = config as unknown as Record<string, string | boolean>;
  const update = (key: string, value: string) => {
    setMessage("");
    setForm(current => {
      const next = { ...current, [key]: value };
      if (value === String(saved[key] ?? "") || (key.endsWith("_token") && !value)) delete next[key];
      return next;
    });
  };
  const bool = (key: "openlist_enabled" | "openlist_auto_sync") => form[key] === undefined ? config[key] : form[key] === "true";
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const payload = Object.fromEntries(Object.entries(form).map(([key, value]) =>
        [key, ["openlist_enabled", "openlist_auto_sync"].includes(key) ? value === "true" : value]));
      onSaved(await api.saveCrossCopyConfig(payload));
      setForm({}); setMessage("跨盘设置已保存，只有所选通路生效");
    } catch (error) { setMessage(error instanceof ApiError ? error.message : "保存失败"); }
    finally { setBusy(false); }
  }

  async function test() {
    setBusy(true); setMessage("");
    try { setMessage((await api.testOpenList()).message); }
    catch (error) { setMessage(error instanceof ApiError ? error.message : "连接测试失败"); }
    finally { setBusy(false); }
  }

  return <form className="settings-form openlist-settings-form" onSubmit={event => void save(event)}>
    <SettingsSection title="跨盘通路与补齐规则" body="OpenList 与 CD2 二选一；两条通路共用缺失文件筛选、落盘核验和 STRM／Emby 入库流程。">
      <div className="notice openlist-compensation-guide">
        <strong>自动补齐会在什么时候启动？</strong>
        <p>夸克文件完成标准命名和正式落盘后，系统先检查 115 目标，再搜索并验真 115 原生分享。只有仍缺失的精确文件会交给所选跨盘通路。</p>
        <p>云下载暂存内容须先由整理器完成正式落盘。智能追更还需在对应季度开启自动补齐。复制失败会单独记录，保留夸克已有的成功结果。</p>
      </div>
      <label className="settings-field"><span>复制通路</span>
        <select aria-label="复制通路" value={route} disabled={busy} onChange={event => update("cross_copy_transport", event.target.value)}>
          <option value="openlist">OpenList</option><option value="cd2">CD2（CloudDrive2）</option>
        </select>
      </label>
      <p className="muted">已有复制或待落盘任务时，需处理完成后再切换。保存后所选通路立即生效。</p>
      <SettingsToggle label="启用跨盘复制" value={bool("openlist_enabled")} onChange={value => update("openlist_enabled", String(value))} disabled={busy} />
      <SettingsToggle label="允许夸克 → 115 自动补齐" value={bool("openlist_auto_sync")} onChange={value => update("openlist_auto_sync", String(value))} disabled={busy} trueLabel="允许" falseLabel="仅手动" />
      <SettingsInput label={`${label} 地址`} name={`${route}_url`} saved={Boolean(saved[`${route}_url`])} value={form[`${route}_url`] ?? ""} onChange={update} placeholder={String(saved[`${route}_url`] || (route === "cd2" ? "http://clouddrive:19798" : "http://openlist:5244"))} showSavedValue />
      <SettingsInput label={`${label} ${route === "cd2" ? "API " : ""}Token`} name={`${route}_token`} saved={Boolean(saved[`has_${route}_token`])} value={form[`${route}_token`] ?? ""} onChange={update} secret />
      {route === "cd2" && <p className="muted">使用 CD2 原生 gRPC 服务地址及 API Token。Token 需允许浏览、复制、创建目录和查询复制任务；清除完成记录还需对应任务管理权限。</p>}
      {(["qas", "p115"] as const).map(provider => {
        const key = `${route}_${provider}_library_path`;
        const fieldLabel = provider === "qas" ? "夸克媒体库目录" : "115 媒体库目录";
        return <SettingsInput key={key} label={fieldLabel} help={`${label} 中的完整云端挂载路径。`} name={key} saved={Boolean(saved[key])} value={form[key] ?? ""} onChange={update} placeholder={String(saved[key] || "")} showSavedValue
          action={<button type="button" className="ghost compact-action" disabled={busy || dirty || !saved[`has_${route}_token`]} onClick={() => setPicker({ key, label: fieldLabel })}>选择目录</button>} />;
      })}
      <button type="button" className="ghost compact-action" disabled={busy || dirty || !config.openlist_enabled} onClick={() => void test()}>测试已保存的连接</button>
    </SettingsSection>
    <div className="settings-footer"><span>{dirty ? "有尚未保存的修改；选目录和测试前请先保存连接" : "设置已与服务端同步"}</span>
      <button type="submit" className="primary compact-action" disabled={busy || !dirty}>{busy ? <CircleNotch className="spin" /> : <FloppyDisk size={16} />}保存跨盘设置</button>
    </div>
    {message && <div className="notice" role="status">{message}</div>}
    {picker && <OpenListDirectoryPicker label={picker.label} onClose={() => setPicker(null)} onSelect={path => { update(picker.key, path); setPicker(null); }} />}
  </form>;
}
