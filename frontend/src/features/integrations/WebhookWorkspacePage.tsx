import { CircleNotch, FloppyDisk } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { api, ApiError, type ConfigStatus } from "../../lib/api";
import { MdcWebhookSettings } from "./MdcWebhookSettings";
import { WebhookConnectionManager } from "./WebhookConnectionManager";


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
  const mdcSection = useRef<HTMLDivElement | null>(null);
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
    <header className="portal-section-head"><div><h2>Webhook 连接</h2><p>用统一入口接收外部消息，或将 MediaIndex 的业务事件安全推送给其他系统。</p></div></header>
    <WebhookConnectionManager publicBaseUrl={publicBaseUrl} onOpenMdc={() => mdcSection.current?.scrollIntoView({ behavior: "smooth", block: "start" })} />
    <div ref={mdcSection} style={{ scrollMarginTop: 20 }}>
      <header className="portal-section-head" style={{ marginTop: 28 }}><div><h2>MDC-NG 内置适配器</h2><p>保留已验证的专用接收端、目录授权与增量 STRM 行为；通用连接不会改变这条链路。</p></div></header>
      <form className="settings-form" onSubmit={(event) => void save(event)}>
        <MdcWebhookSettings config={config} form={form} onChange={(key, value) => setForm((current) => ({ ...current, [key]: value }))} publicBaseUrl={publicBaseUrl} />
        <div className="settings-footer">
          <span>{saving ? "正在保存 Webhook 设置" : Object.keys(form).length ? "当前有尚未保存的修改" : "Webhook 设置已与服务端同步"}</span>
          <button type="submit" className="primary compact-action" disabled={saving || !Object.keys(form).length}>{saving ? <CircleNotch className="spin" /> : <FloppyDisk size={16} />}{saving ? "保存中" : "保存 MDC-NG 设置"}</button>
        </div>
        {message && <div className="notice">{message}</div>}
      </form>
    </div>
  </section>;
}
