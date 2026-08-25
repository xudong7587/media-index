import { Copy, Key, WebhooksLogo } from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import type { ConfigStatus } from "../../lib/api";
import { SettingsInput, SettingsNumberInput, SettingsToggle } from "../settings/SettingsFormParts";
import { SettingsSection } from "../settings/SettingsUi";
import { ProviderDirectoryPicker } from "../openlist/OpenListSettingsTools";


export function MdcWebhookSettings({
  config,
  form,
  onChange,
  publicBaseUrl,
}: {
  config: ConfigStatus;
  form: Record<string, string>;
  onChange: (key: string, value: string) => void;
  publicBaseUrl: string;
}) {
  const [tokenVisible, setTokenVisible] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const provider = (form.mdc_webhook_provider || config.mdc_webhook_provider || "p115") as "p115" | "quark";
  const rootPath = form.mdc_webhook_root_path ?? config.mdc_webhook_root_path ?? "";
  const token = form.mdc_webhook_token || "";
  const endpoint = useMemo(
    () => `${publicBaseUrl}/api/webhooks/mdc-ng${token ? `?token=${encodeURIComponent(token)}` : "?token=••••••••"}`,
    [publicBaseUrl, token],
  );
  const enabled = form.mdc_webhook_enabled === undefined
    ? config.mdc_webhook_enabled
    : form.mdc_webhook_enabled === "true";

  function generateToken() {
    const bytes = new Uint8Array(32);
    window.crypto.getRandomValues(bytes);
    onChange("mdc_webhook_token", Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(""));
    setTokenVisible(true);
  }

  async function copyEndpoint() {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(endpoint);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      window.prompt("复制 MDC-NG Webhook URL", endpoint);
    }
  }

  return <>
    <SettingsSection title="MDC-NG Webhook" body="MDC-NG 刮削成功后通知 MediaIndex，以现有高效清单方式执行一次只增不删的 STRM 增量同步。">
      <div className="notification-channel-flat primary-channel">
        <div className="channel-heading">
          <div><strong>刮削完成 → STRM 增量同步</strong><span>连续完成事件会在等待窗口内合并，避免一个刮削批次重复扫描。</span></div>
          <WebhooksLogo size={28} aria-hidden />
        </div>
        <SettingsToggle label="启用 MDC-NG Webhook" value={enabled} onChange={(value) => onChange("mdc_webhook_enabled", String(value))} trueLabel="启用" falseLabel="关闭" />
        <div className="settings-field compact-select-field">
          <span>增量同步网盘</span>
          <select value={provider} onChange={(event) => onChange("mdc_webhook_provider", event.target.value)} aria-label="MDC-NG 增量同步网盘">
            <option value="p115">115</option><option value="quark">夸克</option>
          </select>
          <small>网盘与扫描范围只读本页已保存配置，不采用 Webhook Body 传来的路径。</small>
        </div>
        <SettingsInput
          label="增量同步来源目录"
          name="mdc_webhook_root_path"
          saved={Boolean(config.mdc_webhook_root_path)}
          value={rootPath}
          onChange={onChange}
          placeholder={provider === "p115" ? config.p115_strm_source_root : config.quark_strm_source_root}
          showSavedValue
          action={<button type="button" className="ghost compact-action" onClick={() => setPickerOpen(true)}>选择目录</button>}
          help="留空时使用对应网盘 STRM 页面中的来源目录。"
        />
        <SettingsNumberInput label="同批事件合并等待（秒）" name="mdc_webhook_debounce_seconds" value={form.mdc_webhook_debounce_seconds || ""} placeholder={String(config.mdc_webhook_debounce_seconds || 30)} min={5} max={600} onChange={onChange} />
        <SettingsInput
          label="Webhook 密钥"
          name="mdc_webhook_token"
          saved={config.has_mdc_webhook_token}
          value={token}
          secret
          onChange={onChange}
          onReveal={(value) => { onChange("mdc_webhook_token", value); setTokenVisible(true); }}
          action={<button type="button" className="ghost compact-action" onClick={generateToken}><Key size={16} />生成新密钥</button>}
          help="完整 URL 中包含密钥，请只填写到自己的 MDC-NG，不要公开分享。"
        />
        <div className="webhook-setup-values"><span>MDC-NG Endpoint URL</span><code>{tokenVisible && token ? endpoint : `${publicBaseUrl}/api/webhooks/mdc-ng?token=••••••••`}</code></div>
        <div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={!token} onClick={() => setTokenVisible((current) => !current)}>{tokenVisible ? "隐藏完整 URL" : "显示完整 URL"}</button><button type="button" className="primary compact-action" disabled={!token} onClick={() => void copyEndpoint()}><Copy size={16} />{copied ? "已复制" : "复制完整 URL"}</button></div>
      </div>
    </SettingsSection>
    <SettingsSection title="MDC-NG 设置步骤" body="按 MDC-NG 的 Webhook 页面从上到下配置；不需要编写复杂模板。">
      <ol className="mdc-webhook-guide">
        <li><strong>先在本页生成密钥并保存</strong><span>保存后再复制上方完整 Endpoint URL。</span></li>
        <li><strong>MDC-NG → 设置 → Webhook，开启 Webhook</strong><span>新增一个 Endpoint，名称可填“MediaIndex 增量同步”。</span></li>
        <li><strong>请求方式选择 POST</strong><span>URL 粘贴本页生成的完整地址；Headers 不填写。</span></li>
        <li><strong>触发事件只勾“刮削成功（finished）”</strong><span>“刮削失败（failed）”不要勾；触发分类全部留空，表示所有分类。</span></li>
        <li><strong>Body 模板（JSON）留空即可</strong><span>MediaIndex 不依赖 MDC-NG 模板变量；如 MDC-NG 要求填写，可使用 <code>{`{"event":"{{ event }}","task_id":"{{ task_id }}"}`}</code>。</span></li>
      </ol>
      <div className="notice page-notice">安全规则：该入口只触发增量扫描，不会把“本轮没看到”的历史 STRM 标记删除，也不会修改或删除网盘文件。</div>
    </SettingsSection>
    {pickerOpen && <ProviderDirectoryPicker provider={provider} label="MDC-NG 增量同步来源目录" startPath={rootPath || (provider === "p115" ? config.p115_strm_source_root : config.quark_strm_source_root) || "/"} onClose={() => setPickerOpen(false)} onSelect={(path) => { onChange("mdc_webhook_root_path", path); setPickerOpen(false); }} />}
  </>;
}
