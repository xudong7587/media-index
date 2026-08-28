import { CaretRight, FolderOpen } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ApiError } from "../lib/api";

function normalizeProviderPath(value: string) {
  const normalized = value.trim().replace(/\\/g, "/").replace(/\/+/g, "/");
  if (!normalized || normalized === "/") return "/";
  return `/${normalized.replace(/^\/+/, "").replace(/\/+$/, "")}`;
}

function pathWithinRoot(path: string, root: string) {
  const normalizedPath = normalizeProviderPath(path).toLocaleLowerCase();
  const normalizedRoot = normalizeProviderPath(root).toLocaleLowerCase();
  return normalizedRoot === "/" || normalizedPath === normalizedRoot || normalizedPath.startsWith(`${normalizedRoot}/`);
}

export function ProviderDirectoryPicker({
  provider,
  label,
  startPath,
  allowMissing = false,
  boundaryRoots = [],
  onClose,
  onSelect,
}: {
  provider: "qas" | "quark" | "p115";
  label: string;
  startPath: string;
  allowMissing?: boolean;
  boundaryRoots?: string[];
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const roots = Array.from(new Set(boundaryRoots.map(normalizeProviderPath)));
  const safeStartPath = roots.some((root) => pathWithinRoot(startPath, root)) ? normalizeProviderPath(startPath) : roots[0] || normalizeProviderPath(startPath || "/");
  const [path, setPath] = useState(safeStartPath);
  const [directories, setDirectories] = useState<{ name: string; is_dir: boolean }[]>([]);
  const [exists, setExists] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextPath: string) {
    const normalizedNextPath = normalizeProviderPath(nextPath);
    if (roots.length && !roots.some((root) => pathWithinRoot(normalizedNextPath, root))) {
      setError("只能选择已授权 STRM 范围内的目录");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await api.browseProviderPath(provider, normalizedNextPath, false, allowMissing);
      setPath(result.path);
      setExists(result.exists);
      setDirectories(result.directories);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "读取网盘目录失败");
      setExists(false);
      setDirectories([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(safeStartPath);
  }, [provider, safeStartPath, allowMissing]);

  const activeBoundaryRoot = roots.find((root) => pathWithinRoot(path, root)) || roots[0] || "/";

  function parentPath() {
    if (path === activeBoundaryRoot) return activeBoundaryRoot;
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    const parent = parts.length ? `/${parts.join("/")}` : "/";
    return pathWithinRoot(parent, activeBoundaryRoot) ? parent : activeBoundaryRoot;
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="directory-picker-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">×</button>
        <div className="directory-picker-heading">
          <div><h2>选择{label}</h2><p>{roots.length ? "可进入已授权范围内的任意层级子目录。" : "通过已配置的网盘凭据读取目录。"}</p></div>
          <FolderOpen size={28} aria-hidden />
        </div>
        {roots.length > 1 && <div className="directory-picker-boundary-roots" aria-label="已授权 STRM 范围">
          {roots.map((root) => <button type="button" className={activeBoundaryRoot === root ? "active" : ""} key={root} title={root} onClick={() => void load(root)} disabled={loading}>{root.split("/").filter(Boolean).at(-1) || root}</button>)}
        </div>}
        <div className="directory-picker-path" title={path}>{path}</div>
        <div className="directory-picker-actions">
          <button type="button" className="ghost compact-action" onClick={() => void load(activeBoundaryRoot)} disabled={loading || path === activeBoundaryRoot}>{roots.length ? "授权根目录" : "根目录"}</button>
          <button type="button" className="ghost compact-action" onClick={() => void load(parentPath())} disabled={loading || path === activeBoundaryRoot}>返回上级</button>
          <button type="button" className="primary compact-action" onClick={() => onSelect(path)} disabled={loading || Boolean(error)}>选择当前目录</button>
        </div>
        {loading && <div className="directory-picker-empty">读取中…</div>}
        {!loading && error && <div className="settings-inline-result error">{error}</div>}
        {!loading && !error && !exists && <div className="notice page-notice">该目标目录尚未创建；首次成功转存时会自动逐级创建。</div>}
        {!loading && !error && exists && !directories.length && <div className="directory-picker-empty">当前目录没有可进入的子目录</div>}
        {!loading && !error && directories.length > 0 && (
          <div className="directory-picker-list">
            {directories.map((directory) => {
              const nextPath = `${path === "/" ? "" : path}/${directory.name}`;
              return <button type="button" className="directory-picker-item" key={nextPath} onClick={() => void load(nextPath)}><FolderOpen size={19} /><span>{directory.name}</span><CaretRight size={17} /></button>;
            })}
          </div>
        )}
      </article>
    </div>
  );
}

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
    setLoading(true);
    setError("");
    try {
      const result = await api.browseLocalPath(nextPath);
      setRoot(result.root);
      setPath(result.path);
      setExists(result.exists);
      setDirectories(result.directories);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "读取本地目录失败");
      setExists(false);
      setDirectories([]);
    } finally {
      setLoading(false);
    }
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

  return (
    <div className="modal-backdrop" onClick={onClose}>
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
    </div>
  );
}
