import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { CaretRight, FolderOpen } from "@phosphor-icons/react";
import { api, ApiError } from "../../lib/api";

export function LocalDirectoryPicker({ label, startPath, onClose, onSelect }: {
  label: string;
  startPath: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const [root, setRoot] = useState("");
  const [path, setPath] = useState(startPath);
  const [directories, setDirectories] = useState<{ name: string; is_dir: boolean }[]>([]);
  const [exists, setExists] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  async function load(nextPath: string) {
    setLoading(true); setError("");
    try {
      const result = await api.browseLocalPath(nextPath);
      setRoot(result.root); setPath(result.path); setExists(result.exists); setDirectories(result.directories);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "读取本地目录失败");
      setExists(false);
      setDirectories([]);
    } finally { setLoading(false); }
  }
  useEffect(() => { void load(startPath); }, [startPath]);
  function childPath(name: string) {
    const separator = path.includes("\\") ? "\\" : "/";
    return `${path.replace(/[\\/]+$/, "")}${separator}${name}`;
  }
  function parentPath() {
    if (!path || path === root) return root;
    const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
    const parent = normalized.slice(0, normalized.lastIndexOf("/")) || "/";
    return path.includes("\\") ? parent.replace(/\//g, "\\") : parent;
  }
  return <div className="modal-backdrop" onClick={onClose}>
    <article className="directory-picker-modal" onClick={(event) => event.stopPropagation()}>
      <button className="modal-close" onClick={onClose} title="关闭">×</button>
      <div className="directory-picker-heading"><div><h2>选择{label}</h2><p>仅显示容器中已挂载的 STRM 目录。</p></div><FolderOpen size={28} /></div>
      <div className="directory-picker-path" title={path}>{path || "正在读取…"}</div>
      <div className="directory-picker-actions"><button type="button" className="ghost compact-action" onClick={() => void load(root)} disabled={loading || !root || path === root}>挂载根目录</button><button type="button" className="ghost compact-action" onClick={() => void load(parentPath())} disabled={loading || !root || path === root}>返回上级</button><button type="button" className="primary compact-action" onClick={() => onSelect(path)} disabled={loading || !path}>选择当前目录</button></div>
      {loading && <div className="directory-picker-empty">读取中…</div>}
      {!loading && error && <div className="settings-inline-result error">{error}</div>}
      {!loading && !error && !exists && <div className="notice page-notice">该目录尚未创建；保存后首次生成 STRM 时会在挂载目录内自动创建。</div>}
      {!loading && !error && exists && !directories.length && <div className="directory-picker-empty">当前目录没有可进入的子目录</div>}
      {!loading && !error && directories.length > 0 && <div className="directory-picker-list">{directories.map((directory) => <button type="button" className="directory-picker-item" key={directory.name} onClick={() => void load(childPath(directory.name))}><FolderOpen size={19} /><span>{directory.name}</span><CaretRight size={17} /></button>)}</div>}
    </article>
  </div>;
}

export function SettingsSection({
  title,
  body,
  children,
  className = "",
}: {
  title: string;
  body: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`settings-section ${className}`.trim()}>
      <header>
        <strong>{title}</strong>
        <span>{body}</span>
      </header>
      <div className="settings-section-body">{children}</div>
    </section>
  );
}

export function normalizeOpenListPath(value: string) {
  const parts = String(value || "").replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length ? `/${parts.join("/")}` : "/";
}

export function normalizeCategoryInputPath(value: string) {
  const parts = String(value || "").replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length ? `/${parts.join("/")}` : "/";
}

export function OpenListDirectoryPicker({
  label,
  onClose,
  onSelect,
}: {
  label: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const [path, setPath] = useState("/");
  const [directories, setDirectories] = useState<{ name: string; is_dir: boolean }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextPath: string) {
    setLoading(true);
    setError("");
    try {
      const result = await api.browseOpenList(nextPath);
      setPath(result.path);
      setDirectories(result.directories);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "读取 OpenList 目录失败");
      setDirectories([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("/");
  }, []);

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
            <p>通过 OpenList Token 读取可访问的目录。</p>
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

export function Segmented({
  value,
  items,
  onChange,
}: {
  value: string;
  items: readonly (readonly [string, string])[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="segmented">
      {items.map(([key, label]) => (
        <button type="button" key={key} className={value === key ? "active" : ""} onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  );
}
