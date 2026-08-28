import { CircleNotch, FloppyDisk } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api, ApiError, type ConfigStatus } from "../../lib/api";
import { MdcWebhookSettings } from "./MdcWebhookSettings";


function webhookPayload(form: Record<string, string>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  Object.entries(form).forEach(([key, value]) => {
    if (key === "mdc_webhook_enabled") payload[key] = value === "true";
    else if (key === "mdc_webhook_debounce_seconds" && value.trim()) payload[key] = Number(value);
    else if (key === "mdc_webhook_root_path" || key === "mdc_webhook_scan_path") payload[key] = value.trim();
    else if (value.trim()) payload[key] = value.trim();
  });
  return payload;
}


export function WebhookWorkspacePage() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => { void api.config().then(setConfig).catch((error: Error) => setMessage(error.message)); }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!Object.keys(form).length) return;
    setSaving(true);
    setMessage("");
    try {
      await api.saveConfig(webhookPayload(form));
      setConfig(await api.config());
      setForm({});
      setMessage("Webhook 设置已保存");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Webhook 设置保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (!config) return <div className="workspace-loading"><CircleNotch className="spin" />正在读取 Webhook 设置</div>;
  const publicBaseUrl = (config.public_base_url || window.location.origin).replace(/\/+$/, "");
  return <section>
    <header className="portal-section-head"><div><h2>Webhook 入口</h2><p>接收 MDC-NG 或其他容器的完成事件，对预先选择的媒体目录执行增量 STRM，再通知 Emby。</p></div></header>
    <form className="settings-form" onSubmit={(event) => void save(event)}>
      <MdcWebhookSettings config={config} form={form} onChange={(key, value) => setForm((current) => ({ ...current, [key]: value }))} publicBaseUrl={publicBaseUrl} />
      <div className="settings-footer">
        <span>{saving ? "正在保存 Webhook 设置" : Object.keys(form).length ? "当前有尚未保存的修改" : "Webhook 设置已与服务端同步"}</span>
        <button type="submit" className="primary compact-action" disabled={saving || !Object.keys(form).length}>{saving ? <CircleNotch className="spin" /> : <FloppyDisk size={16} />}{saving ? "保存中" : "保存 Webhook 设置"}</button>
      </div>
      {message && <div className="notice">{message}</div>}
    </form>
  </section>;
}
