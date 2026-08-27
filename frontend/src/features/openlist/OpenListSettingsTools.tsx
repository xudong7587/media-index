import { useEffect, useState } from "react";
import { CaretDown, CaretRight, CaretUp, FolderOpen } from "@phosphor-icons/react";
import { api, ApiError, OpenListEntry } from "../../lib/api";
export function InteractionDownloadDirectoryGuide({ p115Root, quarkRoot, onOpenP115Rules, onOpenQuarkRules }: { p115Root: string; quarkRoot: string; onOpenP115Rules: () => void; onOpenQuarkRules: () => void }) {
  return <>
    <p className="channel-help">115 分享、磁力、电驴和 HTTP 链接会读取 115 云下载目录；夸克分享链接会读取夸克云下载目录。未填写资源名时会返回该目录的一级子目录供你选择。</p>
    <div className="settings-action-strip"><button type="button" className="ghost compact-action" onClick={onOpenQuarkRules}>设置夸克云下载目录</button><button type="button" className="ghost compact-action" onClick={onOpenP115Rules}>设置 115 云下载目录</button></div>
    <div className="direct-download-grid">
      <div className="settings-field compact-select-field"><span>磁力 / 电驴默认网盘</span><strong>115（离线下载）</strong></div>
      <div className="settings-field compact-select-field"><span>115 目录来源</span><strong>{p115Root || "/"}</strong><small>发送 115 或离线下载链接时实时读取该目录的一级子目录。</small></div>
      <div className="settings-field compact-select-field"><span>夸克目录来源</span><strong>{quarkRoot || "/"}</strong></div>
      <p className="settings-help">115 分享链接转存和离线下载需要配置有效 Cookie。</p>
    </div>
  </>;
}

export function buildPushConfigPayload(form: Record<string, string>) {
  const payload: Record<string, string | number | boolean | string[]> = {};
  const booleanKeys = ["notification_external_enabled", "telegram_enabled", "wecom_enabled", "wecom_app_enabled", "wecom_callback_enabled", "direct_download_enabled"];
  const clearableKeys = ["wecom_app_to_user", "wecom_app_to_party", "wecom_app_to_tag", "wecom_callback_allowed_users", "wecom_callback_url", "direct_download_save_path"];
  Object.entries(form).forEach(([key, value]) => {
    if (booleanKeys.includes(key)) {
      payload[key] = value === "true";
    } else if (key === "interaction_providers") {
      payload[key] = value.split(",").map((item) => item.trim()).filter(Boolean);
    } else if (key === "wecom_app_agent_id") {
      if (value.trim()) payload[key] = Number(value);
    } else if (value.trim() || clearableKeys.includes(key)) {
      payload[key] = value.trim();
    }
  });
  return payload;
}

type OpenListSortKey = "name" | "type" | "time";
type OpenListSortState = { key: OpenListSortKey; direction: "asc" | "desc" };
