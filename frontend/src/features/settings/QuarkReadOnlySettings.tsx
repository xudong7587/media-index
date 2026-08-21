import { CheckCircle, CircleNotch, QrCode, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import QRCode from "qrcode";

import { api, ApiError, ConfigStatus } from "../../lib/api";
import { SettingsInput } from "./SettingsFormParts";
import { SettingsSection } from "./SettingsUi";

type Result = { ok: boolean; message: string } | null;
type ShareResult = { ok: boolean; message: string; title?: string; file_count?: number; directory_count?: number; video_count?: number; truncated?: boolean; files?: { name: string; size: number; is_dir: boolean; is_video: boolean }[] } | null;

export function QuarkReadOnlySettings({ mode = "connection", onChanged }: { mode?: "connection" | "verification"; onChanged?: () => void }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [cookie, setCookie] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const [qrSessionId, setQrSessionId] = useState("");
  const [qrImage, setQrImage] = useState("");
  const [qrBusy, setQrBusy] = useState(false);
  const [qrMessage, setQrMessage] = useState("");
  const [qrExpiresAt, setQrExpiresAt] = useState(0);
  const [qrSecondsLeft, setQrSecondsLeft] = useState(0);
  const [qrExpired, setQrExpired] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const [shareBusy, setShareBusy] = useState(false);
  const [shareResult, setShareResult] = useState<ShareResult>(null);

  async function refresh() {
    setConfig(await api.config());
    onChanged?.();
  }

  useEffect(() => {
    void refresh().catch(() => setResult({ ok: false, message: "夸克配置读取失败" }));
  }, []);

  useEffect(() => {
    if (!qrSessionId) return;
    const timer = window.setInterval(() => {
      void api.pollQuarkQrLogin(qrSessionId).then(async (state) => {
        setQrMessage(state.message);
        if (state.status === "success") {
          setQrSessionId("");
          setQrImage("");
          setQrExpiresAt(0);
          setQrSecondsLeft(0);
          await refresh();
        } else if (state.status === "expired") {
          setQrSessionId("");
          setQrExpired(true);
        }
      }).catch((error) => {
        setQrMessage(error instanceof ApiError ? error.message : "扫码状态读取失败");
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [qrSessionId]);

  useEffect(() => {
    if (!qrExpiresAt || !qrSessionId) return;
    const updateCountdown = () => {
      const remaining = Math.max(0, Math.ceil((qrExpiresAt - Date.now()) / 1000));
      setQrSecondsLeft(remaining);
      if (remaining === 0) {
        setQrSessionId("");
        setQrExpired(true);
        setQrMessage("二维码已过期，请重新获取");
      }
    };
    updateCountdown();
    const timer = window.setInterval(updateCountdown, 1000);
    return () => window.clearInterval(timer);
  }, [qrExpiresAt, qrSessionId]);

  async function saveCookie() {
    if (!cookie.trim()) {
      setResult({ ok: false, message: "请先粘贴夸克 Cookie" });
      return;
    }
    setSaving(true);
    setResult(null);
    try {
      await api.saveConfig({ quark_cookie: cookie.trim() });
      setCookie("");
      await refresh();
      setResult({ ok: true, message: "Cookie 已安全保存，可以验证当前连接。" });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError ? error.message : "Cookie 保存失败" });
    } finally {
      setSaving(false);
    }
  }

  async function testConnection() {
    setTesting(true);
    setResult(null);
    try {
      const response = await api.testQuark();
      setResult({ ok: response.ok, message: response.message });
    } catch (error) {
      setResult({ ok: false, message: error instanceof ApiError ? error.message : "夸克读取验证失败" });
    } finally {
      setTesting(false);
    }
  }

  async function startQrLogin() {
    setQrBusy(true);
    setQrMessage("");
    setQrExpired(false);
    setQrImage("");
    setQrExpiresAt(0);
    setQrSecondsLeft(0);
    try {
      const response = await api.startQuarkQrLogin();
      if (!response.ok || !response.session_id || !response.qr_url) {
        throw new Error(response.message || "夸克未返回扫码会话");
      }
      setQrImage(await QRCode.toDataURL(response.qr_url, { width: 248, margin: 2, errorCorrectionLevel: "M" }));
      setQrSessionId(response.session_id);
      const lifetime = Math.max(30, response.expires_in_seconds ?? 300);
      setQrExpiresAt(Date.now() + lifetime * 1000);
      setQrSecondsLeft(lifetime);
      setQrMessage("请使用夸克 App 扫描二维码并确认，本页会自动保存授权结果。" );
    } catch (error) {
      setQrMessage(error instanceof ApiError || error instanceof Error ? error.message : "扫码会话创建失败");
    } finally {
      setQrBusy(false);
    }
  }

  async function inspectShare() {
    if (!shareUrl.trim()) {
      setShareResult({ ok: false, message: "请先粘贴夸克分享链接" });
      return;
    }
    setShareBusy(true);
    setShareResult(null);
    try {
      const response = await api.inspectQuarkShare(shareUrl.trim());
      setShareResult(response);
    } catch (error) {
      setShareResult({ ok: false, message: error instanceof ApiError ? error.message : "分享链接验证失败" });
    } finally {
      setShareBusy(false);
    }
  }

  const connected = Boolean(config?.has_quark_cookie);
  return (
    <div className="provider-module-grid quark-readonly-settings">
      {mode === "connection" && <SettingsSection title="夸克登录凭证" body="支持扫码和手工 Cookie，两种方式都会保存到本机服务端。连接验证只读取账号与根目录，不修改网盘文件。">
        <div className="quark-connection-state">
          {connected ? <CheckCircle size={19} weight="fill" /> : <WarningCircle size={19} />}
          <span>{connected ? "夸克凭据已保存，可以验证当前连接。" : "尚未连接夸克账号。"}</span>
        </div>
      </SettingsSection>}

      {mode === "connection" && <SettingsSection title="方式一：扫码连接" body="MediaIndex 在当前页面显示夸克一次性二维码；确认后自动保存授权结果，不会把 Cookie 返回浏览器。">
        {qrImage && <div className={`cloud-login-qr${qrExpired ? " is-expired" : ""}`}>
          <div className="cloud-login-qr-image"><img src={qrImage} alt="夸克登录二维码" />{qrExpired && <span>已过期</span>}</div>
          <strong>{qrExpired ? "请重新获取二维码" : "使用夸克 App 扫码"}</strong>
          <span>{qrExpired ? "旧二维码已保留，方便确认刚才的会话状态" : `剩余 ${Math.floor(qrSecondsLeft / 60)}:${String(qrSecondsLeft % 60).padStart(2, "0")}`}</span>
        </div>}
        <div className="settings-action-strip">
          <button type="button" className="primary compact-action" onClick={() => void startQrLogin()} disabled={qrBusy || Boolean(qrSessionId)}>
            {qrBusy || qrSessionId ? <CircleNotch className="spin" /> : <QrCode />}
            {qrBusy ? "正在生成二维码" : qrSessionId ? "等待扫码确认" : qrExpired ? "重新获取二维码" : "显示登录二维码"}
          </button>
          {qrMessage && <div className={`settings-inline-result ${qrSessionId || qrMessage.includes("已保存") ? "success" : "error"}`}>{qrMessage}</div>}
        </div>
      </SettingsSection>}

      {mode === "connection" && <SettingsSection title="方式二：手工 Cookie" body="从已登录的夸克网页复制 Cookie 后粘贴。仅保存在本机服务端；保存后输入框会清空，页面不会再次显示 Cookie。">
        <SettingsInput label="夸克 Cookie" name="quark_cookie" saved={connected} value={cookie} onChange={(_name, value) => setCookie(value)} secret />
        <div className="settings-action-strip">
          <button type="button" className="ghost compact-action" onClick={() => void saveCookie()} disabled={saving || !cookie.trim()}>
            {saving && <CircleNotch className="spin" />}保存 Cookie
          </button>
        </div>
      </SettingsSection>}

      {mode === "connection" && <SettingsSection title="连接验证" body="验证会读取账号资料和根目录前 50 项。连接成功后，夸克自动进入统一检索、验真与转存流程。">
        <div className="settings-action-strip">
          <button type="button" className="primary compact-action" onClick={() => void testConnection()} disabled={!connected || testing}>
            {testing ? <CircleNotch className="spin" /> : <ShieldCheck />} {testing ? "验证中" : "验证连接"}
          </button>
          {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
        </div>
      </SettingsSection>}

      {mode === "verification" && <SettingsSection title="夸克分享链接验真" body="粘贴夸克分享链接后，系统只读取真实文件树，标出视频文件数量；不会转存、重命名或生成任何文件。">
        <SettingsInput label="夸克分享链接" name="quark_share_url" saved={false} value={shareUrl} onChange={(_name, value) => setShareUrl(value)} placeholder="https://pan.quark.cn/s/…" />
        <div className="settings-action-strip">
          <button type="button" className="primary compact-action" onClick={() => void inspectShare()} disabled={!connected || shareBusy || !shareUrl.trim()}>
            {shareBusy && <CircleNotch className="spin" />}{shareBusy ? "读取文件中" : "验证分享链接"}
          </button>
          {shareResult && <div className={`settings-inline-result ${shareResult.ok ? "success" : "error"}`}>{shareResult.message}</div>}
        </div>
        {shareResult?.ok && (
          <div className="quark-share-summary">
            <strong>{shareResult.title || "已读取分享"}</strong>
            <span>共 {shareResult.file_count ?? 0} 项 · 视频 {shareResult.video_count ?? 0} 个 · 目录 {shareResult.directory_count ?? 0} 个</span>
            {shareResult.files && <ul>{shareResult.files.slice(0, 8).map((item) => <li key={`${item.name}-${item.size}`}><span>{item.is_dir ? "目录" : item.is_video ? "视频" : "文件"}</span>{item.name}</li>)}</ul>}
            {shareResult.truncated && <small>文件较多，仅显示前 200 项。</small>}
          </div>
        )}
      </SettingsSection>}
    </div>
  );
}
