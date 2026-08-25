import { Copy, Key, PaperPlaneTilt, WebhooksLogo } from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import { api, ApiError, type ConfigStatus } from "../../lib/api";
import { SettingsInput, SettingsNumberInput, SettingsToggle } from "../settings/SettingsFormParts";
import { SettingsSection } from "../settings/SettingsUi";


const WEBHOOK_PATH = "/api/webhooks/strm-incremental";
const WEBHOOK_FORM_KEYS = [
  "mdc_webhook_enabled",
  "mdc_webhook_provider",
  "mdc_webhook_debounce_seconds",
  "mdc_webhook_token",
];

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
  const [savedToken, setSavedToken] = useState("");
  const [tokenVisible, setTokenVisible] = useState(false);
  const [copied, setCopied] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const provider = (form.mdc_webhook_provider || config.mdc_webhook_provider || "p115") as "p115" | "quark";
  const sourceRoot = provider === "p115" ? config.p115_strm_source_root : config.quark_strm_source_root;
  const includedDirectories = provider === "p115" ? config.p115_strm_included_directories : config.quark_strm_included_directories;
  const draftToken = form.mdc_webhook_token || "";
  const effectiveToken = draftToken || savedToken;
  const hasUnsavedChanges = WEBHOOK_FORM_KEYS.some((key) => Object.prototype.hasOwnProperty.call(form, key));
  const enabled = form.mdc_webhook_enabled === undefined
    ? config.mdc_webhook_enabled
    : form.mdc_webhook_enabled === "true";
  const savedAndEnabled = config.mdc_webhook_enabled && config.has_mdc_webhook_token && !hasUnsavedChanges;
  const endpoint = useMemo(
    () => `${publicBaseUrl}${WEBHOOK_PATH}?token=${tokenVisible && effectiveToken ? encodeURIComponent(effectiveToken) : "••••••••"}`,
    [effectiveToken, publicBaseUrl, tokenVisible],
  );
  const dockerEndpoint = `http://media-index:8000${WEBHOOK_PATH}?token=${tokenVisible && effectiveToken ? encodeURIComponent(effectiveToken) : "••••••••"}`;
  const curlPreview = `curl -i -X POST '${endpoint}' -H 'Content-Type: application/json' -d '{"event":"finished"}'`;

  function generateToken() {
    const bytes = new Uint8Array(32);
    window.crypto.getRandomValues(bytes);
    onChange("mdc_webhook_token", Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(""));
    onChange("mdc_webhook_enabled", "true");
    setSavedToken("");
    setTokenVisible(false);
    setTestResult({ ok: false, message: "新密钥和启用状态尚未生效，请先保存本页设置。" });
  }

  async function resolveSavedToken() {
    if (hasUnsavedChanges) throw new Error("当前 Webhook 设置尚未保存，请先点击“保存并启用”");
    if (!config.mdc_webhook_enabled) throw new Error("Webhook 尚未启用，请开启后保存本页设置");
    if (!config.has_mdc_webhook_token) throw new Error("Webhook 密钥尚未保存，请先生成密钥并保存");
    if (savedToken) return savedToken;
    const result = await api.configSecret("mdc_webhook_token");
    setSavedToken(result.value);
    return result.value;
  }

  async function copyText(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      window.setTimeout(() => setCopied(""), 1800);
    } catch {
      window.prompt(`复制${label}`, value);
    }
  }

  async function revealEndpoint() {
    if (tokenVisible) {
      setTokenVisible(false);
      return;
    }
    try {
      await resolveSavedToken();
      setTokenVisible(true);
      setTestResult(null);
    } catch (error) {
      setTestResult({ ok: false, message: error instanceof Error ? error.message : "完整 URL 读取失败" });
    }
  }

  async function copyEndpoint() {
    try {
      const token = await resolveSavedToken();
      const value = `${publicBaseUrl}${WEBHOOK_PATH}?token=${encodeURIComponent(token)}`;
      setTokenVisible(true);
      await copyText(value, "URL");
      setTestResult(null);
    } catch (error) {
      setTestResult({ ok: false, message: error instanceof Error ? error.message : "URL 复制失败" });
    }
  }

  async function copyCurlCommand() {
    try {
      const token = await resolveSavedToken();
      const url = `${publicBaseUrl}${WEBHOOK_PATH}?token=${encodeURIComponent(token)}`;
      await copyText(`curl -i -X POST '${url}' -H 'Content-Type: application/json' -d '{"event":"finished"}'`, "curl 命令");
      setTestResult(null);
    } catch (error) {
      setTestResult({ ok: false, message: error instanceof Error ? error.message : "curl 命令复制失败" });
    }
  }

  async function testEndpoint() {
    setTesting(true);
    setTestResult(null);
    try {
      const token = await resolveSavedToken();
      const response = await fetch(`${WEBHOOK_PATH}?token=${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: "finished", source: "mediaindex-settings-test" }),
      });
      const result = await response.json().catch(() => ({})) as { detail?: string; message?: string; job_id?: number };
      if (!response.ok) throw new ApiError(response.status, result.detail || `HTTP ${response.status}`);
      setTestResult({ ok: true, message: `${result.message || "连接成功并已安排增量同步"}${result.job_id ? `（任务 #${result.job_id}）` : ""}` });
    } catch (error) {
      setTestResult({ ok: false, message: error instanceof Error ? error.message : "Webhook 测试失败" });
    } finally {
      setTesting(false);
    }
  }

  return <>
    <SettingsSection title="增量同步 Webhook" body="接收任意刮削器、整理器或其他容器的完成事件，并按本页保存的范围执行一次只增不删的 STRM 增量同步。">
      <div className="notification-channel-flat primary-channel">
        <div className="channel-heading">
          <div><strong>外部完成事件 → STRM 增量同步</strong><span>连续完成事件会在等待窗口内合并，避免一个批次重复扫描。</span></div>
          <WebhooksLogo size={28} aria-hidden />
        </div>
        <div className={`webhook-state ${savedAndEnabled ? "ready" : hasUnsavedChanges ? "pending" : "disabled"}`}>
          {savedAndEnabled ? "已启用并保存，可以接收请求" : hasUnsavedChanges ? "有未保存的 Webhook 修改" : "当前未启用"}
        </div>
        <SettingsToggle label="启用增量同步 Webhook" value={enabled} onChange={(value) => onChange("mdc_webhook_enabled", String(value))} trueLabel="启用" falseLabel="关闭" />
        <div className="settings-field compact-select-field">
          <span>增量同步网盘</span>
          <select value={provider} onChange={(event) => onChange("mdc_webhook_provider", event.target.value)} aria-label="Webhook 增量同步网盘">
            <option value="p115">115</option><option value="quark">夸克</option>
          </select>
          <small>网盘与扫描范围只读本页已保存配置，不采用外部请求 Body 传来的路径。</small>
        </div>
        <div className="settings-field webhook-saved-scope">
          <span>已保存的 STRM 扫描范围</span>
          <strong>{sourceRoot || "尚未配置来源目录"}</strong>
          <small>{includedDirectories.length ? `仅扫描：${includedDirectories.join("、")}` : "尚未勾选扫描子目录；Webhook 不会回退为整盘扫描。"}</small>
        </div>
        <SettingsNumberInput label="同批事件合并等待（秒）" name="mdc_webhook_debounce_seconds" value={form.mdc_webhook_debounce_seconds || ""} placeholder={String(config.mdc_webhook_debounce_seconds || 30)} min={5} max={600} onChange={onChange} />
        <SettingsInput
          label="Webhook 密钥"
          name="mdc_webhook_token"
          saved={config.has_mdc_webhook_token}
          value={draftToken}
          secret
          onChange={onChange}
          onReveal={(value) => { setSavedToken(value); setTokenVisible(true); }}
          action={<button type="button" className="ghost compact-action" onClick={generateToken}><Key size={16} />生成新密钥</button>}
          help="完整 URL 中包含密钥，只提供给可信的外部服务，不要公开分享。"
        />
        <div className="webhook-setup-values"><span>外部访问 URL</span><code>{endpoint}</code><span>同网络容器</span><code>{dockerEndpoint}</code></div>
        <p className="settings-help">同一 Docker 网络可使用服务名 <code>media-index:8000</code>；不在同一网络时，把外部访问 URL 的主机和端口改为其他容器能够访问的 NAS 地址。容器内不要使用 <code>localhost</code> 或 <code>127.0.0.1</code>。</p>
        <div className="settings-action-strip webhook-actions">
          {hasUnsavedChanges && <button type="submit" className="primary compact-action">{enabled ? "保存并启用" : "保存并关闭"}</button>}
          <button type="button" className="ghost compact-action" onClick={() => void revealEndpoint()}>{tokenVisible ? "隐藏完整 URL" : "显示完整 URL"}</button>
          <button type="button" className="ghost compact-action" onClick={() => void copyEndpoint()}><Copy size={16} />{copied === "URL" ? "已复制" : "复制完整 URL"}</button>
          <button type="button" className="primary compact-action" disabled={testing} onClick={() => void testEndpoint()}><PaperPlaneTilt size={16} />{testing ? "正在测试" : "测试并触发一次增量"}</button>
        </div>
        {testResult && <div className={`settings-inline-result ${testResult.ok ? "success" : "error"}`}>{testResult.message}</div>}
      </div>
    </SettingsSection>
    <SettingsSection title="外部服务配置与命令" body="外部服务只需在任务成功完成时向完整 URL 发送一个 POST 请求，不依赖特定软件或模板变量。">
      <ol className="webhook-guide">
        <li><strong>先在上方生成密钥、开启开关并保存</strong><span>状态显示“已启用并保存”后，再复制完整 URL；未保存的开关不会在服务端生效。</span></li>
        <li><strong>外部服务新增一个 Webhook Endpoint</strong><span>请求方式选 POST，URL 粘贴完整地址，Headers 留空。</span></li>
        <li><strong>只绑定成功或完成事件</strong><span>例如 finished、completed 或 success；不要绑定 failed。连续事件会自动合并。</span></li>
        <li><strong>Body 可以留空</strong><span>如外部服务要求 JSON，可填写 <code>{`{"event":"finished"}`}</code>。MediaIndex 不采信 Body 中的网盘和路径。</span></li>
      </ol>
      <div className="webhook-command-block">
        <div><strong>从外部容器测试</strong><button type="button" className="ghost compact-action" onClick={() => void copyCurlCommand()}><Copy size={15} />{copied === "curl 命令" ? "已复制" : "复制命令"}</button></div>
        <pre><code>{curlPreview}</code></pre>
        <p>返回 <code>HTTP 202</code>、<code>state: scheduled</code> 或 <code>coalesced</code> 即表示连接成功；随后在“运行日志 → 计划任务”查看增量任务。</p>
      </div>
      <div className="notice page-notice">安全规则：该入口始终使用 MediaIndex 已保存的网盘与来源目录，只触发增量扫描；不会把本轮未发现的历史 STRM 标记删除，也不会修改或删除网盘文件。</div>
    </SettingsSection>
  </>;
}
