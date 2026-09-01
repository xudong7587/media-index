import { useEffect, useState } from "react";
import { Copy, ShieldCheck, WarningCircle } from "@phosphor-icons/react";

import { api, ApiError, type DiagnosticSupportStatus } from "../../lib/api";
import { SettingsToggle } from "./SettingsFormParts";
import { SettingsSection } from "./SettingsUi";


export function DeveloperSettings() {
  const [status, setStatus] = useState<DiagnosticSupportStatus | null>(null);
  const [ttl, setTtl] = useState(30);
  const [token, setToken] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  async function refresh() {
    const next = await api.diagnosticSupportStatus();
    setStatus(next);
  }

  useEffect(() => {
    void refresh().catch(() => setMessage("开发者设置加载失败"));
  }, []);

  async function toggle(enabled: boolean) {
    setBusy("toggle");
    setMessage("");
    try {
      await api.saveConfig({ developer_remote_diagnostics_enabled: enabled });
      if (!enabled) {
        setToken("");
        setExpiresAt("");
      }
      await refresh();
      setMessage(enabled ? "远程只读诊断已启用；尚未创建任何令牌" : "远程诊断已关闭，现有令牌已撤销");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "保存失败");
    } finally {
      setBusy("");
    }
  }

  async function createToken() {
    setBusy("create");
    setMessage("");
    try {
      const result = await api.createDiagnosticSupportToken(ttl);
      setToken(result.token);
      setExpiresAt(result.expires_at);
      await refresh();
      setMessage("令牌已创建。它只显示这一次，请复制后妥善保管。");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "创建令牌失败");
    } finally {
      setBusy("");
    }
  }

  async function revoke() {
    setBusy("revoke");
    setMessage("");
    try {
      const result = await api.revokeDiagnosticSupportTokens();
      setToken("");
      setExpiresAt("");
      await refresh();
      setMessage(`已撤销 ${result.revoked} 个有效令牌`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "撤销令牌失败");
    } finally {
      setBusy("");
    }
  }

  async function copyToken() {
    if (!token) return;
    await navigator.clipboard.writeText(token);
    setMessage("令牌已复制");
  }

  const base = window.location.origin.replace(/\/$/, "");

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>开发者选项</h1>
          <p>为远程排障提供最小权限、短时有效的只读诊断入口。</p>
        </div>
      </div>
      {!status && <div className="list-skeleton" />}
      {status && (
        <div className="settings-form">
          <SettingsSection title="远程只读诊断" body="默认关闭。仅允许读取已经脱敏的诊断事件和指定任务时间线。">
            <SettingsToggle
              label="允许短时远程诊断"
              help="不开放原始日志、系统配置、网盘凭据、写入操作或命令执行。关闭时会立即撤销全部令牌。"
              value={status.enabled}
              onChange={(enabled) => void toggle(enabled)}
              trueLabel="已启用"
              falseLabel="已关闭"
              disabled={Boolean(busy)}
              busy={busy === "toggle"}
            />
            <div className="settings-inline-result warning"><WarningCircle />只在 HTTPS 反代地址上使用；不要把后台用户名、密码、Cookie 或永久 Token 发给任何人。</div>
          </SettingsSection>

          <SettingsSection title="临时支持令牌" body="固定权限 diagnostics:read；5–120 分钟后自动失效，服务端只保存令牌摘要。">
            <label className="settings-field">
              <span>有效期（分钟）</span>
              <input type="number" min={5} max={120} value={ttl} onChange={(event) => setTtl(Math.max(5, Math.min(120, Number(event.target.value) || 5)))} />
            </label>
            <div className="settings-action-strip">
              <button type="button" className="primary compact-action" disabled={!status.enabled || Boolean(busy)} onClick={() => void createToken()}><ShieldCheck />创建一次性显示令牌</button>
              <button type="button" className="ghost compact-action" disabled={!status.active_token_count || Boolean(busy)} onClick={() => void revoke()}>撤销全部令牌</button>
              <span className="settings-help">当前有效：{status.active_token_count} 个{status.next_expiry ? `；最近到期 ${status.next_expiry} UTC` : ""}</span>
            </div>
            {token && (
              <div className="settings-field">
                <span>新令牌（刷新页面后不再显示）</span>
                <div className="settings-action-strip">
                  <code className="developer-token-value">{token}</code>
                  <button type="button" className="ghost compact-action" onClick={() => void copyToken()}><Copy />复制</button>
                </div>
                <small className="settings-help">到期时间：{expiresAt}</small>
              </div>
            )}
          </SettingsSection>

          <SettingsSection title="只读接口" body="请求时使用 Authorization: Bearer &lt;临时令牌&gt;。">
            <div className="settings-field"><span>增量事件</span><code>{base}/api/diagnostics/support/events?after_id=0&amp;limit=200</code></div>
            <div className="settings-field"><span>单任务时间线</span><code>{base}/api/diagnostics/support/tasks/任务ID/timeline</code></div>
            <p className="settings-help">接口有每令牌、每来源地址每分钟 60 次的限流；所有返回均禁止浏览器缓存。</p>
          </SettingsSection>
          {message && <div className="settings-inline-result">{message}</div>}
        </div>
      )}
    </section>
  );
}
