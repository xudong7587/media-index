import { CircleNotch, QrCode, SealCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ApiError } from "../../lib/api";

const LOGIN_APPS: { value: string; label: string; scanner: string }[] = [
  { value: "alipaymini", label: "支付宝小程序（推荐）", scanner: "支付宝" },
  { value: "wechatmini", label: "微信小程序", scanner: "微信" },
  { value: "web", label: "网页版", scanner: "115 App" },
  { value: "android", label: "Android 版", scanner: "115 App" },
  { value: "ios", label: "iOS 版", scanner: "115 App" },
  { value: "tv", label: "TV 版", scanner: "115 App" },
  { value: "qandroid", label: "Android TV 版", scanner: "115 App" },
];

const POLL_INTERVAL_MS = 2000;

export function P115CookieQrLogin({ disabled, onSaved }: { disabled?: boolean; onSaved?: () => void }) {
  const [app, setApp] = useState("alipaymini");
  const [sessionId, setSessionId] = useState("");
  const [qrImage, setQrImage] = useState("");
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [starting, setStarting] = useState(false);
  const [expiresAt, setExpiresAt] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [maskedCookie, setMaskedCookie] = useState("");
  const [finished, setFinished] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let timer = 0;
    // Sequential polling: a slow 115 status answer must not stack up requests.
    const tick = async () => {
      try {
        const state = await api.pollP115CookieQrLogin(sessionId);
        if (cancelled) return;
        setMessage(state.message);
        setIsError(!state.ok);
        if (state.status === "done") {
          setSessionId("");
          setExpiresAt(0);
          setSecondsLeft(0);
          setFinished(true);
          setMaskedCookie(state.cookie_masked || "Cookie 已保存");
          onSaved?.();
        } else if (state.status === "expired" || state.status === "canceled") {
          setSessionId("");
          setExpiresAt(0);
          setSecondsLeft(0);
        }
      } catch (error) {
        if (cancelled) return;
        setMessage(error instanceof ApiError ? error.message : "115 扫码状态读取失败");
        setIsError(true);
      }
      if (!cancelled) timer = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
    };
    timer = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [sessionId]);

  useEffect(() => {
    if (!expiresAt || !sessionId) return;
    const updateCountdown = () => {
      const remaining = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
      setSecondsLeft(remaining);
      if (remaining === 0) {
        setSessionId("");
        setMessage("二维码已过期，请重新获取");
        setIsError(true);
      }
    };
    updateCountdown();
    const timer = window.setInterval(updateCountdown, 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt, sessionId]);

  async function startLogin() {
    setStarting(true);
    setMessage("");
    setIsError(false);
    setMaskedCookie("");
    setFinished(false);
    setQrImage("");
    try {
      const response = await api.startP115CookieQrLogin(app);
      if (!response.ok || !response.session_id || !response.qr_image) {
        throw new Error(response.message || "115 未返回扫码会话");
      }
      setQrImage(response.qr_image);
      if (response.app) setApp(response.app);
      setSessionId(response.session_id);
      const lifetime = Math.max(30, response.expires_in_seconds ?? 300);
      setExpiresAt(Date.now() + lifetime * 1000);
      setSecondsLeft(lifetime);
      setMessage(`请使用 ${LOGIN_APPS.find((item) => item.value === (response.app || app))?.scanner || "115 App"} 扫码并在手机上确认，本页会自动保存登录结果。`);
    } catch (error) {
      setMessage(error instanceof ApiError || error instanceof Error ? error.message : "115 扫码会话创建失败");
      setIsError(true);
    } finally {
      setStarting(false);
    }
  }

  const running = Boolean(sessionId);
  const selectedApp = LOGIN_APPS.find((item) => item.value === app) || LOGIN_APPS[0];
  return (
    <div className="p115-qr-login">
      <p className="settings-help">
        请选择要获取的 Cookie 会话类型；同类型已登录会话可能被踢下线。建议用不常用的支付宝或微信小程序通道。登录结果只保存在服务端，页面仅显示掩码。
      </p>
      <label className="settings-field">
        <span>Cookie 会话类型</span>
        <select aria-label="115 扫码会话类型" value={app} disabled={running || starting || disabled} onChange={(event) => setApp(event.target.value)}>
          {LOGIN_APPS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </label>
      {qrImage && (
        <div className="cloud-login-qr">
          <div className="cloud-login-qr-image"><img src={qrImage} alt="115 登录二维码" /></div>
          <strong>{running ? `使用 ${selectedApp.scanner} 扫码` : finished ? "扫码登录已完成" : "二维码已停止轮询"}</strong>
          <span>{running ? `剩余 ${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, "0")}` : "可重新获取二维码"}</span>
        </div>
      )}
      <div className="settings-action-strip">
        <button type="button" className="primary compact-action" onClick={() => void startLogin()} disabled={disabled || starting || running}>
          {starting || running ? <CircleNotch className="spin" /> : <QrCode />}
          {starting ? "正在生成二维码" : running ? "等待扫码确认" : finished ? "重新扫码登录" : "扫码登录"}
        </button>
        {message && <div className={`settings-inline-result ${isError ? "error" : "success"}`}>{message}</div>}
      </div>
      {finished && maskedCookie && (
        <div className="connection-summary connected">
          <SealCheck size={21} weight="fill" />
          <div><strong>115 扫码登录已保存</strong><span>{maskedCookie}</span></div>
        </div>
      )}
    </div>
  );
}
