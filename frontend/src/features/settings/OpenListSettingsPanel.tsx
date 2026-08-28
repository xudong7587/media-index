import { CircleNotch, FloppyDisk } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api, ApiError, type ConfigStatus } from "../../lib/api";
import { buildConfigPayload, SettingsInput, SettingsToggle } from "./SettingsFormParts";
import { OpenListDirectoryPicker, SettingsSection } from "./SettingsUi";


export function OpenListSettingsPanel({
  config,
  onSaved,
}: {
  config: ConfigStatus;
  onSaved: (config: ConfigStatus) => void;
}) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [message, setMessage] = useState("");
  const [picker, setPicker] = useState<{ key: string; label: string } | null>(null);

  useEffect(() => {
    if (!Object.keys(form).length) return undefined;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [form]);

  function update(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!Object.keys(form).length) return;
    setSaving(true);
    setMessage("");
    try {
      await api.saveConfig({
        ...buildConfigPayload(form),
        // Automatic OpenList work is a compensation path, never a reverse
        // synchronization strategy. Manual selection remains explicit below.
        openlist_auto_sync_direction: "qas_to_p115",
      });
      const next = await api.config();
      onSaved(next);
      setForm({});
      setMessage("OpenList 设置已保存");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "OpenList 设置保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function testConnection() {
    if (Object.keys(form).length) {
      setResult({ ok: false, message: "请先保存当前修改，再测试服务端实际连接。" });
      return;
    }
    setTesting(true);
    setResult(null);
    try {
      const response = await api.testOpenList();
      setResult({ ok: response.ok, message: response.message });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError ? error.message : "OpenList 连接失败" });
    } finally {
      setTesting(false);
    }
  }

  const enabled = form.openlist_enabled === undefined ? config.openlist_enabled : form.openlist_enabled === "true";
  const autoCompensation = form.openlist_auto_sync === undefined ? config.openlist_auto_sync : form.openlist_auto_sync === "true";

  return <form className="settings-form openlist-settings-form" onSubmit={(event) => void save(event)}>
    <SettingsSection
      title="OpenList 连接与补偿规则"
      body="独立网盘转存完成后，OpenList 只在明确启用的任务中用夸克结果补齐 115；不会介入发现页的基础转存。"
    >
      <SettingsToggle label="启用 OpenList" value={enabled} onChange={(value) => update("openlist_enabled", String(value))} trueLabel="启用" falseLabel="停用" />
      <SettingsToggle
        label="允许夸克 → 115 自动补偿"
        help="这是智能追更按季启用 OpenList 补齐的总开关。只有夸克已成功、115 仍缺失时才会执行。"
        value={autoCompensation}
        onChange={(value) => update("openlist_auto_sync", String(value))}
        trueLabel="允许"
        falseLabel="仅手动"
      />
      <SettingsInput label="OpenList 地址" name="openlist_url" saved={Boolean(config.openlist_url)} value={form.openlist_url || ""} onChange={update} placeholder={config.openlist_url || "http://openlist:5244"} showSavedValue />
      <SettingsInput label="OpenList Token" name="openlist_token" saved={config.has_openlist_token} value={form.openlist_token || ""} onChange={update} secret />
      <SettingsInput
        label="夸克媒体库目录"
        help="OpenList 中的夸克挂载路径，不是本地文件系统路径。"
        name="openlist_qas_library_path"
        saved={Boolean(config.openlist_qas_library_path)}
        value={form.openlist_qas_library_path || ""}
        onChange={update}
        placeholder={config.openlist_qas_library_path || "/夸克/媒体库"}
        showSavedValue
        action={<button type="button" className="ghost compact-action" onClick={() => setPicker({ key: "openlist_qas_library_path", label: "夸克媒体库目录" })} disabled={!config.has_openlist_token}>选择目录</button>}
      />
      <SettingsInput
        label="115 媒体库目录"
        help="OpenList 中的 115 挂载路径，不是本地文件系统路径。"
        name="openlist_p115_library_path"
        saved={Boolean(config.openlist_p115_library_path)}
        value={form.openlist_p115_library_path || ""}
        onChange={update}
        placeholder={config.openlist_p115_library_path || "/115/媒体库"}
        showSavedValue
        action={<button type="button" className="ghost compact-action" onClick={() => setPicker({ key: "openlist_p115_library_path", label: "115 媒体库目录" })} disabled={!config.has_openlist_token}>选择目录</button>}
      />
      <div className="settings-action-strip">
        <button type="button" className="ghost compact-action" onClick={() => void testConnection()} disabled={testing || saving || !config.openlist_enabled}>
          {testing && <CircleNotch className="spin" />}{testing ? "测试中" : "测试连接"}
        </button>
        {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
      </div>
    </SettingsSection>
    <div className="settings-footer">
      <span>{saving ? "正在保存" : Object.keys(form).length ? "当前有尚未保存的 OpenList 修改" : "OpenList 设置已与服务端同步"}</span>
      <button type="submit" className="primary compact-action" disabled={saving || !Object.keys(form).length}>
        {saving ? <CircleNotch className="spin" /> : <FloppyDisk size={16} />}{saving ? "保存中" : "保存 OpenList 设置"}
      </button>
    </div>
    {message && <div className="notice">{message}</div>}
    {picker && <OpenListDirectoryPicker
      label={picker.label}
      onClose={() => setPicker(null)}
      onSelect={(path) => { update(picker.key, path); setPicker(null); }}
    />}
  </form>;
}
