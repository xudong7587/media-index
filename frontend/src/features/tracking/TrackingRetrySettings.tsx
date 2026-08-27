import { useEffect, useState } from "react";
import { FloppyDisk } from "@phosphor-icons/react";
import { api } from "../../lib/api";
import "./tracking-surfaces.css";

const MIN_RETRY_INTERVAL_MINUTES = 1;
const MAX_RETRY_INTERVAL_MINUTES = 1440;
const MIN_RETRY_COUNT = 1;
const MAX_RETRY_COUNT = 20;

function formatInterval(minutes: number) {
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours} 小时 ${remainingMinutes} 分钟` : `${hours} 小时`;
}

export function TrackingRetrySettings() {
  const [retryInterval, setRetryInterval] = useState("");
  const [maxRetries, setMaxRetries] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    let active = true;
    api.config()
      .then((config) => {
        if (!active) return;
        setRetryInterval(String(config.tracking_retry_interval_minutes));
        setMaxRetries(String(config.tracking_max_retries));
      })
      .catch(() => {
        if (active) setMessage({ kind: "error", text: "追更重试设置读取失败" });
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  function update(key: string, value: string) {
    if (key === "tracking_retry_interval_minutes") setRetryInterval(value);
    if (key === "tracking_max_retries") setMaxRetries(value);
    setMessage(null);
  }

  async function save() {
    const interval = Number(retryInterval);
    const retries = Number(maxRetries);
    if (!Number.isInteger(interval) || interval < MIN_RETRY_INTERVAL_MINUTES || interval > MAX_RETRY_INTERVAL_MINUTES) {
      setMessage({ kind: "error", text: `重试间隔请填 ${MIN_RETRY_INTERVAL_MINUTES}-${MAX_RETRY_INTERVAL_MINUTES} 之间的整数分钟` });
      return;
    }
    if (!Number.isInteger(retries) || retries < MIN_RETRY_COUNT || retries > MAX_RETRY_COUNT) {
      setMessage({ kind: "error", text: `最大重试次数请填 ${MIN_RETRY_COUNT}-${MAX_RETRY_COUNT} 之间的整数` });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await api.saveConfig({
        tracking_retry_interval_minutes: interval,
        tracking_max_retries: retries,
      });
      setMessage({ kind: "success", text: "失败重试策略已保存" });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "失败重试策略保存失败" });
    } finally {
      setSaving(false);
    }
  }

  const intervalMinutes = Number(retryInterval);
  const intervalHelp = Number.isFinite(intervalMinutes) && intervalMinutes >= MIN_RETRY_INTERVAL_MINUTES
    ? `当前重试间隔：${formatInterval(intervalMinutes)}`
    : "设置资源暂未发布或未搜到时的重试间隔";

  return (
    <section className="tracking-retry-settings" aria-labelledby="tracking-retry-settings-title">
      <div className="tracking-retry-settings-copy">
        <strong id="tracking-retry-settings-title">失败重试</strong>
        <span>{intervalHelp}；未发布或未搜到会继续静默检查，执行失败累计达到上限后转为待确认。</span>
      </div>
      <div className="tracking-retry-settings-fields">
        <label className="settings-field">
          <span>失败后重试间隔（分钟）</span>
          <input
            type="number"
            inputMode="numeric"
            name="tracking_retry_interval_minutes"
            value={retryInterval}
            placeholder="120"
            min={MIN_RETRY_INTERVAL_MINUTES}
            max={MAX_RETRY_INTERVAL_MINUTES}
            onChange={(event) => update(event.target.name, event.target.value)}
          />
        </label>
        <label className="settings-field">
          <span>最大重试次数</span>
          <input
            type="number"
            inputMode="numeric"
            name="tracking_max_retries"
            value={maxRetries}
            placeholder="5"
            min={MIN_RETRY_COUNT}
            max={MAX_RETRY_COUNT}
            onChange={(event) => update(event.target.name, event.target.value)}
          />
        </label>
        <button type="button" className="primary compact-action" onClick={() => void save()} disabled={loading || saving || !retryInterval || !maxRetries}>
          {saving ? <span className="spinner" aria-hidden="true" /> : <FloppyDisk size={16} />}
          {saving ? "保存中" : "保存策略"}
        </button>
      </div>
      {message && <div className={`settings-inline-result ${message.kind}`}>{message.text}</div>}
    </section>
  );
}
