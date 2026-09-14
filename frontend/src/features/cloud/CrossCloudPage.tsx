import { useEffect, useState } from "react";
import { ArrowSquareOut, CaretDown, CaretUp, CircleNotch, HardDrives } from "@phosphor-icons/react";
import { api, type CrossCopyConfig, type OpenListCopyTask } from "../../lib/api";
import type { AppRoute } from "../../app/routes";
import { OpenListManualSync } from "../../components/cloud/CopyBrowser";
import { OpenListTaskMonitor } from "../../components/cloud/CopyTaskMonitor";
import { CrossCopySettingsPanel } from "./CrossCopySettingsPanel";

export function CrossCloudPage({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  const [config, setConfig] = useState<CrossCopyConfig | null>(null);
  const [message, setMessage] = useState("");
  const [taskError, setTaskError] = useState("");
  const [openListTasks, setOpenListTasks] = useState<OpenListCopyTask[]>([]);
  const [progressOpen, setProgressOpen] = useState(true);
  const [taskGroup, setTaskGroup] = useState<"running" | "completed">("running");

  useEffect(() => {
    void api.crossCopyConfig().then(setConfig).catch((error: Error) => setMessage(error.message));
    let active = true;
    let taskLoading = false;
    const refreshTasks = async () => {
      if (taskLoading) return;
      taskLoading = true;
      try { const result = await api.openListTasks(); if (active) { setOpenListTasks(result.tasks); setTaskError(""); } }
      catch (error) { if (active) { setOpenListTasks([]); setTaskError(error instanceof Error ? error.message : "复制队列读取失败"); } }
      finally { taskLoading = false; }
    };
    refreshTasks();
    const timer = window.setInterval(refreshTasks, 2_500);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const openListReady = Boolean(config?.ready);
  const transportLabel = config?.cross_copy_transport === "cd2" ? "CD2" : "OpenList";
  const runningOpenListTasks = openListTasks.filter((task) => task.state === "running");
  const completedOpenListTasks = openListTasks.filter((task) => task.state !== "running");
  const visibleOpenListTasks = taskGroup === "running" ? runningOpenListTasks : completedOpenListTasks;
  return (
    <section className="cross-cloud-page">
      <div className="page-head"><div><p className="eyebrow">CROSS-CLOUD COPY</p><h1>网盘跨盘补齐</h1><p>基础转存保持 115、夸克独立；这里只处理夸克已有而 115 缺失时的补偿与手工复制。</p></div></div>
      <section className="openlist-transfer-boundary">
        <div><HardDrives size={24} weight="fill" /><div><strong>补偿链路，不是发现入口</strong><p>先由两个网盘分别完成发现与转存；需要时再从夸克定向补齐 115。</p></div></div>
        <div className="settings-action-strip">
          <button type="button" className="ghost compact-action" onClick={() => onNavigate({ page: "workspace", section: "tasks" })}><ArrowSquareOut />查看任务中心</button>
        </div>
      </section>
      {message && <div className="settings-inline-result error">{message}</div>}
      {!config && !message && <div className="workspace-loading"><CircleNotch className="spin" />正在读取跨盘配置</div>}
      {config && <>
        <CrossCopySettingsPanel config={config} onSaved={setConfig} />
        {!openListReady && <div className="settings-inline-result error">所选通路尚未就绪。请在上方完成连接、Token 和两个挂载目录后再执行复制。</div>}
        <OpenListManualSync
          key={`${config.cross_copy_transport}:${config.source_mount}:${config.target_mount}`}
          qasPath={config.source_mount}
          p115Path={config.target_mount}
          enabled={openListReady}
          reverseCopyDisabled
          reverseCopyDisabledReason="暂不支持从 115 复制到夸克"
        />
        <section className={`openlist-live-tasks ${progressOpen ? "open" : "collapsed"}`}>
          <header><div><h2>{transportLabel} 复制进度</h2><p>读取所选通路的复制队列；完成落盘核验后进入 STRM／Emby 流程。</p></div><button type="button" className="ghost compact-action" onClick={() => setProgressOpen((value) => !value)}>{progressOpen ? <CaretUp /> : <CaretDown />}{progressOpen ? "折叠" : "打开"}</button></header>
          {progressOpen && <>
            {taskError && <div className="settings-inline-result error" role="alert">{taskError}</div>}
            <div className="openlist-task-tabs" role="tablist" aria-label="复制任务状态">
              <button type="button" role="tab" className={taskGroup === "running" ? "active" : ""} aria-selected={taskGroup === "running"} onClick={() => setTaskGroup("running")}>正在进行 <span>{runningOpenListTasks.length}</span></button>
              <button type="button" role="tab" className={taskGroup === "completed" ? "active" : ""} aria-selected={taskGroup === "completed"} onClick={() => setTaskGroup("completed")}>已完成 <span>{completedOpenListTasks.length}</span></button>
            </div>
            <OpenListTaskMonitor tasks={visibleOpenListTasks.slice(0, 30)} emptyText={taskGroup === "running" ? "当前没有进行中的复制任务" : "当前没有已完成的复制任务"} />
          </>}
        </section>
      </>}
    </section>
  );
}
