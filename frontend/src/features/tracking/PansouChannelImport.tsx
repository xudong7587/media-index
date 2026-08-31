import { ArrowClockwise, Broadcast, CheckCircle, CircleNotch, DownloadSimple, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { api, ApiError, PansouChannelCandidate } from "../../lib/api";

const statusLabels: Record<PansouChannelCandidate["status"], string> = {
  importable: "可导入",
  existing: "已存在",
  unrecognized: "无法识别",
};

export function PansouChannelImport({ onImported }: { onImported?: () => void }) {
  const [candidates, setCandidates] = useState<PansouChannelCandidate[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState<"discover" | "import" | "">("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const importable = useMemo(() => candidates.filter((item) => item.status === "importable"), [candidates]);

  async function loadChannels() {
    setBusy("discover");
    setMessage(null);
    try {
      const result = await api.pansouChannels();
      setCandidates(result.candidates);
      setSelected(result.candidates.filter((item) => item.status === "importable").map((item) => item.channel_id));
      setMessage({ ok: true, text: result.message });
    } catch (error) {
      setCandidates([]);
      setSelected([]);
      setMessage({ ok: false, text: error instanceof ApiError ? error.message : "PanSou 频道发现失败" });
    } finally {
      setBusy("");
    }
  }

  useEffect(() => { void loadChannels(); }, []);

  async function importChannels(channelIds: string[]) {
    if (!channelIds.length) return;
    setBusy("import");
    setMessage(null);
    try {
      const result = await api.importPansouChannels(channelIds);
      const imported = new Set(result.imported.map((item) => item.channel_id.toLocaleLowerCase()));
      setCandidates((current) => current.map((item) => imported.has(item.channel_id.toLocaleLowerCase()) ? { ...item, status: "existing", reason: "本次已导入；安全默认值为启用来源、关闭自动转存" } : item));
      setSelected([]);
      setMessage({ ok: true, text: `${result.message} 只复制到 MediaIndex Bot 追踪列表，不会修改 PanSou 频道配置。` });
      onImported?.();
    } catch (error) {
      setMessage({ ok: false, text: error instanceof ApiError ? error.message : "TG 频道导入失败" });
    } finally {
      setBusy("");
    }
  }

  function toggle(channelId: string, checked: boolean) {
    setSelected((current) => checked ? [...new Set([...current, channelId])] : current.filter((item) => item !== channelId));
  }

  return <section className="pansou-channel-import">
    <div className="workspace-section-heading">
      <div>
        <p className="eyebrow">PANSOU → TELEGRAM SOURCES</p>
        <h3>从 PanSou 导入 TG 频道</h3>
        <p>读取 PanSou 已配置的公开频道名单，勾选后复制到 MediaIndex。导入后还需把 Telegram Bot 加入相应频道，才能实时接收新帖。</p>
      </div>
      <button type="button" className="ghost compact-action" disabled={busy !== ""} onClick={() => void loadChannels()}>{busy === "discover" ? <CircleNotch className="spin" /> : <ArrowClockwise />}读取 PanSou 频道</button>
    </div>
    <p className="settings-field-help">数据来自 PanSou <code>/api/health</code> 返回的 <code>channels</code> 配置；导入或从 MediaIndex 删除都不会反向修改 PanSou 的勾选。</p>
    {message && <div className={`settings-inline-result ${message.ok ? "success" : "error"}`}>{message.text}</div>}
    {candidates.length > 0 && <>
      <div className="pansou-channel-summary">
        {(["importable", "existing", "unrecognized"] as const).map((status) => <span key={status} className={`channel-candidate-count status-${status}`}>{statusLabels[status]} {candidates.filter((item) => item.status === status).length}</span>)}
      </div>
      {importable.length > 0 && <label className="pansou-channel-select-all"><input type="checkbox" checked={selected.length === importable.length} onChange={(event) => setSelected(event.target.checked ? importable.map((item) => item.channel_id) : [])} />全选可导入频道（{importable.length}）</label>}
      <div className="pansou-channel-candidate-list">
        {candidates.map((item, index) => <article className={`pansou-channel-candidate status-${item.status}`} key={`${item.status}-${item.channel_id || item.raw_value}-${index}`}>
          {item.status === "importable" ? <input type="checkbox" checked={selected.includes(item.channel_id)} onChange={(event) => toggle(item.channel_id, event.target.checked)} aria-label={`选择 ${item.channel_id}`} /> : item.status === "existing" ? <CheckCircle weight="fill" /> : <WarningCircle />}
          <div><strong>{item.channel_id || item.raw_value}</strong><small>{statusLabels[item.status]} · {item.reason}</small><code>{item.evidence_field}</code></div>
        </article>)}
      </div>
      <div className="settings-action-strip">
        <button type="button" className="ghost compact-action" disabled={busy !== "" || !selected.length} onClick={() => void importChannels(selected)}><DownloadSimple />导入已勾选（{selected.length}）</button>
        <button type="button" className="primary compact-action" disabled={busy !== "" || !importable.length} onClick={() => void importChannels(importable.map((item) => item.channel_id))}>{busy === "import" ? <CircleNotch className="spin" /> : <Broadcast />}一键导入全部可识别频道</button>
      </div>
    </>}
  </section>;
}
