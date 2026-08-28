import { api, type MediaItem, type TransferBatch } from "../../lib/api";

export type CloudProvider = "qas" | "quark" | "p115";

export async function waitForTransferBatch(
  id: number,
  onProgress: (batch: TransferBatch) => void,
): Promise<TransferBatch> {
  const terminal = new Set(["done", "partial", "needs_review", "failed", "stopped"]);
  for (let attempt = 0; attempt < 360; attempt += 1) {
    const batch = await api.transferBatch(id);
    onProgress(batch);
    if (terminal.has(batch.status)) return batch;
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
  throw new Error("transfer_batch_timeout");
}

export function resourceKey(provider: CloudProvider, seasonNumber: number) {
  return `${provider}:${seasonNumber}`;
}

export function canSmartTrackMedia(item: Pick<MediaItem, "media_type" | "category">, fallbackType = "") {
  const type = item.category || (fallbackType === "movie" ? "" : fallbackType) || item.media_type;
  return type === "tv" || type === "variety" || type === "anime" || type === "documentary";
}

export function providerLabel(provider: CloudProvider) {
  return provider === "p115" ? "115" : "夸克";
}

export function noticeTone(message: string) {
  if (/(失败|错误|异常|无权限|不可用|超时|不匹配|不存在|无效|失效|拒绝)/.test(message)) return "error";
  if (/(需要确认|暂无|尚未|没有已验证|请先|请勿|至少|正在读取网盘配置)/.test(message)) return "warning";
  return "";
}

export function providerShortLabel(provider: CloudProvider) {
  return provider === "p115" ? "115" : provider === "quark" ? "夸克原生" : "夸克";
}

export function transferStageLabel(stage: string) {
  const labels: Record<string, string> = {
    tmdb_resolving: "正在匹配 TMDB",
    checking_saved: "正在检查目标目录",
    validating_link: "正在检查旧链接",
    searching_sources: "正在检索 PanSou 与 TG 频道资源",
    matching_files: "正在匹配文件",
    preparing_names: "正在生成文件名",
    qas_transferring: "正在执行转存",
    provider_submitting: "正在执行转存",
    provider_submitted: "已提交给网盘",
    provider_triggered: "等待网盘确认",
    provider_completed: "已确认完成",
    openlist_sync: "正在同步 OpenList",
    openlist_copy_waiting: "正在确认 115 落盘",
    openlist_sync_done: "OpenList 同步完成",
    openlist_sync_failed: "OpenList 同步失败",
    openlist_landing_failed: "跨盘转存未确认落盘",
    openlist_post_processing_done: "跨盘转存与入库处理完成",
    openlist_post_processing_failed: "跨盘转存后处理失败",
    stopped: "任务已终止",
  };
  return labels[stage] || "正在处理";
}

export function formatTrackingTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
