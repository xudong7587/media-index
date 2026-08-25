import { useEffect, useState } from "react";
import { CaretDown, CaretRight, CaretUp, FolderOpen, TerminalWindow } from "@phosphor-icons/react";
import { api, ApiError, OpenListEntry } from "../../lib/api";
export function CommandReference() {
  const commands = [
    ["资源名", "搜索影视，存在多个结果时回复数字选择"],
    ["本地 资源名", "搜索影视并将确认后的资源保存到本地"],
    ["分享链接", "夸克或 115 分享链接直接转存到默认路径"],
    ["磁力链接", "按交互设置中的磁力默认网盘提交离线下载"],
    ["/review", "查看待确认任务，并通过编号选择候选资源"],
    ["/status", "查看追更、愿望单、待确认和未读通知数量"],
    ["/tracking", "查看最近的智能追更任务"],
    ["/wishlist", "查看最近的愿望单任务"],
    ["/notifications", "查看最近通知"],
    ["/cancel", "取消当前等待中的编号选择"],
    ["/help", "查看企业微信内置指令帮助"],
  ];
  return (
    <section className="command-reference" aria-labelledby="command-reference-title">
      <div className="command-reference-heading">
        <TerminalWindow size={23} aria-hidden />
        <div>
          <strong id="command-reference-title">内置指令速查</strong>
          <span>在企业微信自建应用会话中直接发送</span>
        </div>
      </div>
      <div className="command-reference-grid">
        {commands.map(([command, description]) => (
          <div className="command-reference-item" key={command}>
            <code>{command}</code>
            <span>{description}</span>
          </div>
        ))}
      </div>
      <p>编号选择有效期为 30 分钟。回复数字确认当前选项，发送“取消”或 <code>/cancel</code> 终止选择。</p>
    </section>
  );
}

export function InteractionDownloadDirectoryGuide({ p115Root, quarkRoot, onOpenP115Rules }: { p115Root: string; quarkRoot: string; onOpenP115Rules: () => void }) {
  return <>
    <p className="channel-help">115 分享、磁力、电驴和 HTTP 链接会读取 115 保存根目录的子目录；夸克分享链接会读取夸克保存根目录。两者都会返回目录编号供你确认。</p>
    <div className="settings-action-strip"><button type="button" className="ghost compact-action" onClick={onOpenP115Rules}>前往 115 保存目录设置</button></div>
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
