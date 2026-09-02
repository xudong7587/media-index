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
  const quarkOrganizerReady = config.quark_cloud_download_organizer_enabled;
  const organizerRootsOverlap = config.quark_cloud_download_path === config.quark_root_path;

  return <form className="settings-form openlist-settings-form" onSubmit={(event) => void save(event)}>
    <SettingsSection
      title="OpenList 连接与补偿规则"
      body="这里的自动补齐只处理夸克到 115，不会反向复制。"
    >
      <div className="notice openlist-compensation-guide">
        <strong>自动补齐会在什么时候启动？</strong>
        <p>只有夸克文件已经按标准规则改名、建立媒体/季度目录并逐项核验正式落盘后，MediaIndex 才会检查 115。系统先查看 115 是否已有对应文件，再通过 PanSou 搜索并验真 115 分享；能原生转存时优先使用 115。</p>
        <p>只有 PanSou 没有安全匹配，或 115 只覆盖了部分文件时，OpenList 才会复制剩余的精确文件。补齐失败会单独记录，不会把已成功的夸克转存改成失败。</p>
        <p>TG、企微和网页“链接转存”以及互动搜索会先进入所选云下载目录，再由整理器完成标准落盘。若整理器未启用、未接管或需要复核，系统不会从原始云下载目录启动 115/OpenList。普通正式媒体库转存和愿望单则在自身标准落盘后调用；智能追更还需在对应季度单独开启。</p>
      </div>
      <SettingsToggle label="启用 OpenList" value={enabled} onChange={(value) => update("openlist_enabled", String(value))} trueLabel="启用" falseLabel="停用" />
      <SettingsToggle
        label="允许夸克 → 115 自动补偿"
        help="打开后，只有标准命名、媒体目录和精确目标均确认完成的夸克结果才会尝试补齐 115；云下载暂存内容绝不直接调用。"
        value={autoCompensation}
        onChange={(value) => update("openlist_auto_sync", String(value))}
        trueLabel="允许"
        falseLabel="仅手动"
      />
      {enabled && autoCompensation && (!quarkOrganizerReady || organizerRootsOverlap) && <div className="settings-inline-result error" role="alert">
        {!quarkOrganizerReady
          ? "互动链接暂时无法自动补齐：请到“网盘工作台 → 云下载整理”开启夸克整理。"
          : "互动链接暂时无法自动补齐：夸克云下载根与正式媒体库根相同，请分开设置，例如 /strm/download → /strm。"}
      </div>}
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
