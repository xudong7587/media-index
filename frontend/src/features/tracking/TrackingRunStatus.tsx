type ActiveTrackingRun = {
  id: number;
  status: string;
  stage: string;
  message: string;
};

const stageLabels: Record<string, string> = {
  tmdb_resolving: "正在读取 TMDB 媒体信息",
  checking_saved: "正在读取目标网盘目录",
  validating_link: "正在检查已有分享链接",
  searching_sources: "正在通过 PanSou 搜索资源",
  matching_files: "正在核对候选文件",
  preparing_names: "正在生成规范文件名",
  provider_submitting: "正在提交网盘转存",
  openlist_sync: "正在同步另一网盘的缺失集",
  provider_triggered: "网盘已接受任务，等待文件落盘",
};

export function TrackingRunStatus({ run }: { run?: ActiveTrackingRun | null }) {
  if (!run) return null;
  const waiting = run.status === "triggered";
  const detail = run.message || stageLabels[run.stage] || "正在处理";
  return (
    <p className={`tracking-run-status ${waiting ? "waiting" : "running"}`} aria-live="polite">
      <span className={waiting ? "tracking-run-dot" : "spinner"} aria-hidden="true" />
      <span>{waiting ? "等待网盘：" : "正在执行："}{detail}</span>
    </p>
  );
}
