import { useEffect, useState } from "react";
import { CaretDown, CaretUp, File, FolderOpen } from "@phosphor-icons/react";
import { api, ApiError, OpenListEntry } from "../../lib/api";

type OpenListSortKey = "name" | "type" | "time";
type OpenListSortState = { key: OpenListSortKey; direction: "asc" | "desc" };
export function OpenListManualSync({ qasPath, p115Path, enabled, copyDisabled = false, copyDisabledReason = "", reverseCopyDisabled = false, reverseCopyDisabledReason = "" }: { qasPath: string; p115Path: string; enabled: boolean; copyDisabled?: boolean; copyDisabledReason?: string; reverseCopyDisabled?: boolean; reverseCopyDisabledReason?: string }) {
  const [leftPath, setLeftPath] = useState(qasPath || "/");
  const [rightPath, setRightPath] = useState(p115Path || "/");
  const [leftEntries, setLeftEntries] = useState<OpenListEntry[]>([]);
  const [rightEntries, setRightEntries] = useState<OpenListEntry[]>([]);
  const [leftSelected, setLeftSelected] = useState<string[]>([]);
  const [rightSelected, setRightSelected] = useState<string[]>([]);
  const [leftSort, setLeftSort] = useState<OpenListSortState>({ key: "type", direction: "asc" });
  const [rightSort, setRightSort] = useState<OpenListSortState>({ key: "type", direction: "asc" });
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function load(path: string, side: "left" | "right") {
    try {
      const result = await api.listOpenListEntries(path);
      if (side === "left") { setLeftPath(result.path); setLeftEntries(result.entries); setLeftSelected([]); }
      else { setRightPath(result.path); setRightEntries(result.entries); setRightSelected([]); }
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "读取 OpenList 目录失败");
    }
  }

  useEffect(() => {
    if (enabled) { void load(leftPath, "left"); void load(rightPath, "right"); }
  }, [enabled]);

  function parent(path: string) {
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    return parts.length ? `/${parts.join("/")}` : "/";
  }

  function toggleSort(side: "left" | "right", key: OpenListSortKey) {
    const setSort = side === "left" ? setLeftSort : setRightSort;
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }

  function sortedEntries(entries: OpenListEntry[], sort: OpenListSortState) {
    return [...entries].sort((a, b) => {
      let result = 0;
      if (sort.key === "type") {
        result = Number(b.is_dir) - Number(a.is_dir);
      } else if (sort.key === "time") {
        result = Date.parse(a.modified || "") - Date.parse(b.modified || "");
      } else {
        result = a.name.localeCompare(b.name, "zh-CN", { numeric: true, sensitivity: "base" });
      }
      if (result === 0) result = a.name.localeCompare(b.name, "zh-CN", { numeric: true, sensitivity: "base" });
      return sort.direction === "asc" ? result : -result;
    });
  }

  function formatEntryTime(value?: string) {
    if (!value) return "";
    const timestamp = Date.parse(value);
    if (Number.isNaN(timestamp)) return value;
    return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(timestamp));
  }

  async function copy(direction: "left-to-right" | "right-to-left") {
    if (copyDisabled) {
      setMessage(copyDisabledReason || "手动复制暂时停用");
      return;
    }
    if (direction === "right-to-left" && reverseCopyDisabled) {
      setMessage(reverseCopyDisabledReason || "从 115 复制到夸克暂时停用");
      return;
    }
    const sourcePath = direction === "left-to-right" ? leftPath : rightPath;
    const targetPath = direction === "left-to-right" ? rightPath : leftPath;
    const names = direction === "left-to-right" ? leftSelected : rightSelected;
    if (!names.length) { setMessage("请先勾选要复制的文件或目录"); return; }
    setBusy(true); setMessage("");
    try {
      const result = await api.syncSelectedOpenList({ source_dir: sourcePath, target_dir: targetPath, names, overwrite });
      setMessage(result.message);
      if (result.ok) window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "提交同步失败");
    } finally { setBusy(false); }
  }

  function column(title: string, path: string, entries: OpenListEntry[], selected: string[], setSelected: (value: string[]) => void, side: "left" | "right") {
    const sort = side === "left" ? leftSort : rightSort;
    const visibleEntries = sortedEntries(entries, sort);
    const sortOptions: { key: OpenListSortKey; label: string }[] = [
      { key: "name", label: "文件名" },
      { key: "type", label: "类型" },
      { key: "time", label: "时间" },
    ];
    const toggleSelected = (name: string, checked?: boolean) => {
      const shouldSelect = checked ?? !selected.includes(name);
      setSelected(shouldSelect ? [...selected, name] : selected.filter((item) => item !== name));
    };
    return (
      <section className="openlist-sync-column">
        <header><strong>{title}</strong><code>{path}</code></header>
        <div className="openlist-sync-column-actions">
          <button type="button" className="ghost compact-action" onClick={() => void load(parent(path), side)} disabled={!enabled || path === "/" || busy}>返回上级</button>
          <button type="button" className="ghost compact-action" onClick={() => void load(path, side)} disabled={!enabled || busy}>刷新</button>
        <div className="openlist-sync-sortbar" aria-label={`${title}排序`}>
          {sortOptions.map((option) => {
            const active = sort.key === option.key;
            const DirectionIcon = sort.direction === "asc" ? CaretUp : CaretDown;
            return (
              <button
                type="button"
                key={option.key}
                className={active ? "active" : ""}
                onClick={() => toggleSort(side, option.key)}
                title={`${option.label}${active && sort.direction === "desc" ? "倒序" : "正序"}`}
              >
                <span>{option.label}</span>
                {active && <DirectionIcon size={14} weight="bold" />}
              </button>
            );
          })}
        </div>
        </div>
        <div className="openlist-sync-entry-list">
          {!enabled && <p className="settings-help">请先启用 OpenList 并保存 Token。</p>}
          {enabled && !entries.length && <p className="settings-help">当前目录为空，或没有可读取的项目。</p>}
          {visibleEntries.map((entry) => (
            <div className="openlist-sync-entry" key={entry.name}>
              <input type="checkbox" checked={selected.includes(entry.name)} onChange={(event) => toggleSelected(entry.name, event.target.checked)} />
              <button
                type="button"
                className="openlist-sync-entry-main"
                title={entry.is_dir ? "进入目录" : entry.name}
                onClick={() => {
                  if (entry.is_dir) void load(`${path === "/" ? "" : path}/${entry.name}`, side);
                  else toggleSelected(entry.name);
                }}
              >
                {entry.is_dir ? <FolderOpen size={18} /> : <File size={18} />}
                <span>{entry.name}</span>
              </button>
              {entry.modified && <time dateTime={entry.modified}>{formatEntryTime(entry.modified)}</time>}
            </div>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="openlist-manual-sync">
      <div className="openlist-sync-options">
        <span>已勾选后复制</span>
        <label><input type="radio" checked={!overwrite} onChange={() => setOverwrite(false)} />跳过已存在</label>
        <label><input type="radio" checked={overwrite} onChange={() => setOverwrite(true)} />覆盖已存在</label>
      </div>
      {copyDisabled && <p className="settings-help">{copyDisabledReason}</p>}
      {reverseCopyDisabled && <p className="settings-help">{reverseCopyDisabledReason || "当前暂不支持从 115 复制到夸克。"}</p>}
      <div className="openlist-sync-columns">
        {column("夸克媒体库", leftPath, leftEntries, leftSelected, setLeftSelected, "left")}
        <div className="openlist-sync-arrows" aria-label="复制方向">
          <button type="button" className="primary icon" title={copyDisabled ? copyDisabledReason : "从夸克复制到 115"} onClick={() => void copy("left-to-right")} disabled={!enabled || busy || copyDisabled}>→</button>
          <button type="button" className="primary icon" title={reverseCopyDisabled ? reverseCopyDisabledReason || "从 115 复制到夸克暂时停用" : copyDisabled ? copyDisabledReason : "从 115 复制到夸克"} onClick={() => void copy("right-to-left")} disabled={!enabled || busy || copyDisabled || reverseCopyDisabled}>←</button>
        </div>
        {column("115 媒体库", rightPath, rightEntries, rightSelected, setRightSelected, "right")}
      </div>
      {message && <div className="settings-inline-result">{message}</div>}
    </section>
  );
}
