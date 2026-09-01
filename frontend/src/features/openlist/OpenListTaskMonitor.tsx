import { CheckCircle, CircleNotch, Clock, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, OpenListCopyTask } from "../../lib/api";

export function OpenListTaskMonitor({ tasks, compact = false, emptyText = "OpenList 当前没有复制任务" }: {
  tasks: OpenListCopyTask[];
  compact?: boolean;
  emptyText?: string;
}) {
  if (!tasks.length) return <p className="openlist-task-empty">{emptyText}</p>;
  return <div className={`openlist-task-monitor ${compact ? "compact" : ""}`}>
    {tasks.map((task) => <article className={`openlist-task-row ${task.state}`} key={task.id || `${task.name}-${task.start_time}`}>
      <span className="openlist-task-state">{task.state === "running" ? <CircleNotch className="spin" /> : task.state === "done" ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}</span>
      <div className="openlist-task-body">
        <strong>{task.name}</strong>
        <small>{task.error || (task.state === "done" ? "OpenList 复制完成" : task.status || "OpenList 正在复制")}</small>
        <div className="openlist-task-progress" aria-label={`复制进度 ${Math.round(task.progress)}%`}><i style={{ width: `${task.progress}%` }} /></div>
      </div>
      <span className="openlist-task-percent">{task.state === "done" ? <CheckCircle size={14} /> : <Clock size={14} />}{Math.round(task.progress)}%</span>
    </article>)}
  </div>;
}

export function matchOpenListTasks(tasks: OpenListCopyTask[], title: string) {
  const normalized = title.trim().toLocaleLowerCase();
  if (!normalized) return [];
  return tasks.filter((task) => task.name.toLocaleLowerCase().includes(normalized));
}

export function OpenListTaskPanel({ limit = 20 }: { limit?: number }) {
  const [tasks, setTasks] = useState<OpenListCopyTask[]>([]);
  const [message, setMessage] = useState("正在读取 OpenList 复制队列");
  useEffect(() => {
    let active = true;
    let loading = false;
    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const result = await api.openListTasks();
        if (active) { setTasks(result.tasks); setMessage(result.message); }
      } catch (error) {
        if (active) { setTasks([]); setMessage(error instanceof Error ? error.message : "OpenList 复制队列读取失败"); }
      } finally { loading = false; }
    };
    refresh();
    const timer = window.setInterval(refresh, 2_500);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return <section className="openlist-live-tasks"><header><div><h2>OpenList 复制进度</h2><p>{message}</p></div><span>{tasks.filter((task) => task.state === "running").length} 个进行中</span></header><OpenListTaskMonitor tasks={tasks.slice(0, limit)} /></section>;
}
