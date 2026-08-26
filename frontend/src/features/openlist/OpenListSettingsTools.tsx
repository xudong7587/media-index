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

function normalizeOpenListPath(value: string) {
  const normalized = value.trim().replace(/\\/g, "/").replace(/\/+/g, "/");
  if (!normalized || normalized === "/") return "/";
  return `/${normalized.replace(/^\/+/, "").replace(/\/+$/, "")}`;
}

export function ProviderDirectoryPicker({
  provider,
  label,
  startPath,
  onClose,
  onSelect,
}: {
  provider: "qas" | "quark" | "p115";
  label: string;
  startPath: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const [path, setPath] = useState(normalizeOpenListPath(startPath || "/"));
  const [directories, setDirectories] = useState<{ name: string; is_dir: boolean }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextPath: string) {
    setLoading(true);
    setError("");
    try {
      const result = await api.browseProviderPath(provider, normalizeOpenListPath(nextPath));
      setPath(result.path);
      setDirectories(result.directories);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "读取网盘目录失败");
      setDirectories([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(normalizeOpenListPath(startPath || "/"));
  }, [provider, startPath]);

  function parentPath() {
    if (path === "/") return "/";
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    return parts.length ? `/${parts.join("/")}` : "/";
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="directory-picker-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">×</button>
        <div className="directory-picker-heading">
          <div>
            <h2>选择{label}</h2>
            <p>通过已配置的网盘凭据读取目录。</p>
          </div>
          <FolderOpen size={28} aria-hidden />
        </div>
        <div className="directory-picker-path" title={path}>{path}</div>
        <div className="directory-picker-actions">
          <button type="button" className="ghost compact-action" onClick={() => void load("/")} disabled={loading || path === "/"}>根目录</button>
          <button type="button" className="ghost compact-action" onClick={() => void load(parentPath())} disabled={loading || path === "/"}>返回上级</button>
          <button type="button" className="primary compact-action" onClick={() => onSelect(path)} disabled={loading}>选择当前目录</button>
        </div>
        {loading && <div className="directory-picker-empty">读取中…</div>}
        {!loading && error && <div className="settings-inline-result error">{error}</div>}
        {!loading && !error && !directories.length && <div className="directory-picker-empty">当前目录没有可进入的子目录</div>}
        {!loading && !error && directories.length > 0 && (
          <div className="directory-picker-list">
            {directories.map((directory) => {
              const nextPath = `${path === "/" ? "" : path}/${directory.name}`;
              return (
                <button type="button" className="directory-picker-item" key={nextPath} onClick={() => void load(nextPath)}>
                  <FolderOpen size={19} />
                  <span>{directory.name}</span>
                  <CaretRight size={17} />
                </button>
              );
            })}
          </div>
        )}
      </article>
    </div>
  );
}

type OpenListSortKey = "name" | "type" | "time";
type OpenListSortState = { key: OpenListSortKey; direction: "asc" | "desc" };
