import { useState } from "react";
import { api, type TrackingProviderState, type TrackingTask } from "../../lib/api";
import "./tracking-completion.css";

export function useTrackingArchiveView(items: TrackingTask[]) {
  const [archived, setArchived] = useState(false);
  const isArchived = trackingIsArchived;
  return {
    visibleTasks: items.filter((task) => isArchived(task) === archived),
    archiveControls: <><div className="tracking-archive-tabs" aria-label="追更状态筛选">
      {[false, true].map((value) => <button type="button" key={String(value)} className="ghost compact-action" aria-pressed={archived === value} onClick={() => setArchived(value)}>
        {value ? "已归档" : "追更任务"} · {items.filter((task) => isArchived(task) === value).length}
      </button>)}
    </div>{items.length > 0 && !items.some((task) => isArchived(task) === archived) && <p>{archived ? "暂无已归档任务" : "当前没有进行中的追更任务"}</p>}</>,
  };
}

export function TrackingCompletion({ state, onUpdated }: { state: TrackingProviderState; onUpdated: () => Promise<void> }) {
  const [draft, setDraft] = useState(String(state.final_episode_override ?? ""));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const label = state.status === "archived" ? "本季已收齐 · 已归档"
    : state.completion_state === "complete" ? "本季已收齐"
    : state.completion_state === "caught_up" ? "已播集已收齐 · 等待完结确认" : "本季尚未收齐";
  async function save(final: number | null) {
    if (busy || state.active_job) return;
    setBusy(true);
    setMessage("");
    try {
      await api.updateTrackingFinalEpisode(state.id, final);
      setDraft(String(final ?? ""));
      await onUpdated();
      setMessage(final === null ? "已恢复 TMDB 集数，收齐后自动归档" : `已将本季最终集号设为 E${final}，收齐后自动归档`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败，请重试");
    } finally { setBusy(false); }
  }
  return <details className="tracking-completion">
    <summary>{label}{state.final_episode_override ? ` · 最终 E${state.final_episode_override}` : ""}</summary>
    <p>TMDB 集数不准时，可指定本季最后一集；只影响此网盘追更，不删除文件或历史记录。</p>
    {state.auto_archive === false && <p>此任务已手动恢复，将保持追更；重新保存最终集数设置可启用自动归档。</p>}
    <form onSubmit={(event) => { event.preventDefault(); if (draft) void save(Number(draft)); }}>
      <label>本季最终集号<input type="number" min={1} max={9999} step={1} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="例如 24" disabled={busy || Boolean(state.active_job)} /></label>
      <button type="submit" className="secondary compact-action" disabled={!draft || busy || Boolean(state.active_job)}>{busy ? "保存中…" : "确认最终集数"}</button>
      <button type="button" className="ghost compact-action" onClick={() => void save(null)} disabled={busy || Boolean(state.active_job)}>使用 TMDB 集数</button>
    </form>
    {message && <p role="status">{message}</p>}
  </details>;
}

export function trackingStateLabel(state?: string) {
  const labels: Record<string, string> = {
    idle: "TMDB 暂无下一集播出日期",
    pending: "等待首次巡检",
    retry_wait: "等待下次换源重试",
    needs_review: "需要人工确认",
    awaiting_confirmation: "夸克任务已触发，等待结果确认",
    paused: "任务已暂停",
  };
  return labels[state || ""] || "暂无下一次巡检时间";
}

export function trackingIsArchived(task: TrackingTask) {
  return task.provider_states.length > 0 && task.provider_states.every((state) => state.status === "archived");
}

export function TrackingTaskStatus({ states }: { states: TrackingProviderState[] }) {
  const archived = states.length > 0 && states.every((state) => state.status === "archived");
  const paused = states.length > 0 && states.every((state) => state.status !== "active");
  return <span className={`status ${paused ? "paused" : "active"}`}>{archived ? "已归档" : paused ? "已暂停" : states.some((state) => state.active_job) ? "执行中" : "追更中"}</span>;
}
