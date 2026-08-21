import { ArrowLeft, ArrowsLeftRight, CheckCircle, CircleNotch, FileVideo, Folder, Play, Trash, WarningCircle, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { api, CrossCloudTransfer, P115DirectoryEntry, QuarkDirectoryEntry } from "../../lib/api";

type FolderStep = { id: string; name: string };
type TargetFolderStep = FolderStep & { path: string };
type DirectoryLoadState = "idle" | "loading" | "ready" | "error";

const runnableStates = new Set(["created", "failed_recoverable", "retry_wait"]);
const activeStates = new Set(["fingerprinting", "rapid_probe", "upload_initializing", "streaming", "target_confirming", "cancel_requested"]);
const deletableStates = new Set(["created", "failed_recoverable", "paused_source_changed", "completed"]);

export function CrossCloudTransferCenter() {
  const [workspace, setWorkspace] = useState<{ quark_connected: boolean; p115_connected: boolean; default_p115_target_path: string } | null>(null);
  const [entries, setEntries] = useState<QuarkDirectoryEntry[]>([]);
  const [folders, setFolders] = useState<FolderStep[]>([{ id: "0", name: "夸克根目录" }]);
  const [targetEntries, setTargetEntries] = useState<P115DirectoryEntry[]>([]);
  const [targetFolders, setTargetFolders] = useState<TargetFolderStep[]>([{ id: "0", name: "115 根目录", path: "/" }]);
  const [targetDirectoryState, setTargetDirectoryState] = useState<DirectoryLoadState>("idle");
  const [targetDirectoryError, setTargetDirectoryError] = useState("");
  const [selected, setSelected] = useState<QuarkDirectoryEntry | null>(null);
  const [targetPath, setTargetPath] = useState("");
  const [targetName, setTargetName] = useState("");
  const [transfers, setTransfers] = useState<CrossCloudTransfer[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const currentFolder = folders.at(-1) ?? { id: "0", name: "夸克根目录" };
  const currentTargetFolder = targetFolders.at(-1) ?? { id: "0", name: "115 根目录", path: "/" };
  const sourceReady = Boolean(
    selected
    && targetPath.trim()
    && workspace?.quark_connected
    && workspace?.p115_connected
    && targetDirectoryState === "ready",
  );

  async function refreshTransfers() {
    setTransfers(await api.crossCloudTransfers());
  }

  async function openFolder(folder: FolderStep, nextFolders?: FolderStep[]) {
    setMessage("");
    setSelected(null);
    const next = nextFolders ?? [...folders, folder];
    setFolders(next);
    setEntries(await api.listQuarkDirectory(folder.id));
  }

  async function openTargetFolder(folder: TargetFolderStep, nextFolders?: TargetFolderStep[]) {
    setTargetDirectoryState("loading");
    setTargetDirectoryError("");
    try {
      const result = await api.listP115Directory(folder.id);
      setTargetEntries(result.entries.filter((entry) => entry.is_dir));
      setTargetFolders(nextFolders ?? [...targetFolders, folder]);
      setTargetDirectoryState("ready");
    } catch (error) {
      setTargetEntries([]);
      setTargetDirectoryError(error instanceof Error ? error.message : "115 目录加载失败");
      setTargetDirectoryState("error");
    }
  }

  async function refreshWorkspace() {
    const next = await api.cloudWorkspace();
    setWorkspace(next);
    setTargetPath((value) => value || next.default_p115_target_path || "/strm");
  }

  useEffect(() => {
    void Promise.all([refreshWorkspace(), refreshTransfers()]).catch((error: Error) => setMessage(error.message));
  }, []);

  useEffect(() => {
    if (!workspace?.quark_connected) return;
    void api.listQuarkDirectory(currentFolder.id).then(setEntries).catch((error: Error) => setMessage(error.message));
  }, [workspace?.quark_connected]);

  useEffect(() => {
    if (!workspace?.p115_connected) {
      setTargetDirectoryState("idle");
      setTargetEntries([]);
      return;
    }
    const root = { id: "0", name: "115 根目录", path: "/" };
    void openTargetFolder(root, [root]);
  }, [workspace?.p115_connected]);

  useEffect(() => {
    if (!activeStates.size || !transfers.some((item) => activeStates.has(item.state))) return;
    const timer = window.setInterval(() => void refreshTransfers().catch(() => undefined), 1800);
    return () => window.clearInterval(timer);
  }, [transfers]);

  const breadCrumb = useMemo(() => folders.map((item) => item.name).join(" / "), [folders]);
  const targetBreadCrumb = useMemo(() => targetFolders.map((item) => item.name).join(" / "), [targetFolders]);

  async function createTransfer() {
    if (!selected) return;
    setBusy(true);
    setMessage("");
    try {
      const created = await api.createCrossCloudTransfer({
        source_parent_id: currentFolder.id,
        source_file_id: selected.file_id,
        target_parent_path: targetPath,
        target_name: targetName.trim() || selected.name,
      });
      setTargetName("");
      setMessage(`已建立任务 #${created.id}。请在下方确认后启动，建立任务本身没有写入任何网盘。`);
      await refreshTransfers();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建任务失败");
    } finally {
      setBusy(false);
    }
  }

  async function runTransfer(id: number) {
    setBusy(true);
    setMessage("");
    try {
      await api.runCrossCloudTransfer(id);
      setMessage(`任务 #${id} 已启动：只有夸克直接提供可信 SHA1 才会尝试真正秒传；否则先不落盘读取校验。`);
      await refreshTransfers();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "启动任务失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancelTransfer(id: number) {
    setBusy(true);
    try {
      const transfer = await api.cancelCrossCloudTransfer(id);
      setMessage(`任务 #${id}：${transfer.stage_message}`);
      await refreshTransfers();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "停止任务失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteTransfer(id: number) {
    if (!window.confirm("只删除这条本地任务记录，不会删除夸克或 115 文件。是否继续？")) return;
    setBusy(true);
    setMessage("");
    try {
      await api.deleteCrossCloudTransfer(id);
      setMessage(`任务 #${id} 的本地记录已删除。`);
      await refreshTransfers();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除任务记录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cross-cloud-center">
      <div className="workspace-section-heading">
        <div>
          <p className="eyebrow">QUARK → 115</p>
          <h2>跨盘转存</h2>
          <p>先选择已在夸克中的单个文件，再创建可审阅任务；仅在你点击“启动”后才允许向 115 写入。</p>
        </div>
        <div className="transfer-connection-summary">
          <span className={workspace?.quark_connected ? "ready" : "pending"}>夸克{workspace?.quark_connected ? "已连接" : "待连接"}</span>
          <span className={targetDirectoryState === "ready" ? "ready" : "pending"}>
            115{targetDirectoryState === "ready" ? "实时可读" : workspace?.p115_connected ? "已配置，待验证" : "待连接"}
          </span>
        </div>
      </div>

      {message && <p className="workspace-message">{message}</p>}

      <div className="transfer-planner">
        <section className="source-browser">
          <div className="source-browser-head">
            <div><strong>1. 选择夸克源文件</strong><small>{breadCrumb}</small></div>
            {folders.length > 1 && (
              <button type="button" className="compact-action" onClick={() => void openFolder(folders[folders.length - 2], folders.slice(0, -1))}>
                <ArrowLeft size={16} /> 返回
              </button>
            )}
          </div>
          {!workspace?.quark_connected ? (
            <p className="transfer-placeholder">请先到“账号连接”完成夸克 Cookie 验证。</p>
          ) : (
            <div className="source-entry-list">
              {entries.map((entry) => (
                <button
                  type="button"
                  key={entry.file_id}
                  className={`source-entry ${selected?.file_id === entry.file_id ? "selected" : ""}`}
                  onClick={() => entry.is_dir ? void openFolder({ id: entry.file_id, name: entry.name }) : (setSelected(entry), setTargetName(""))}
                >
                  {entry.is_dir ? <Folder size={19} weight="fill" /> : <FileVideo size={19} weight="fill" />}
                  <span><strong>{entry.name}</strong><small>{entry.is_dir ? "文件夹" : formatBytes(entry.size)}</small></span>
                </button>
              ))}
              {!entries.length && <p className="transfer-placeholder">这个目录还没有可选择的文件。</p>}
            </div>
          )}
        </section>

        <section className="transfer-intent">
          <div className="transfer-intent-heading"><ArrowsLeftRight size={22} /><strong>2. 定义目标与任务</strong></div>
          <div className="target-directory-browser">
            <div className="source-browser-head">
              <div><strong>115 目标目录</strong><small>{targetBreadCrumb}</small></div>
              {targetFolders.length > 1 && (
                <button
                  type="button"
                  className="compact-action"
                  disabled={targetDirectoryState === "loading"}
                  onClick={() => void openTargetFolder(targetFolders[targetFolders.length - 2], targetFolders.slice(0, -1))}
                >
                  <ArrowLeft size={16} /> 返回
                </button>
              )}
            </div>
            {!workspace ? (
              <p className="transfer-placeholder"><CircleNotch className="spin" size={17} /> 正在检查 115 连接…</p>
            ) : !workspace.p115_connected ? (
              <p className="transfer-placeholder"><WarningCircle size={17} /> 请先到“账号连接”完成 115 扫码或 Cookie 配置。</p>
            ) : targetDirectoryState === "loading" ? (
              <p className="transfer-placeholder"><CircleNotch className="spin" size={17} /> 正在实时读取 115 目录…</p>
            ) : targetDirectoryState === "error" ? (
              <div className="target-directory-error">
                <p><WarningCircle size={18} />{targetDirectoryError}</p>
                <button type="button" className="compact-action" onClick={() => void openTargetFolder(currentTargetFolder, targetFolders)}>重新加载</button>
              </div>
            ) : (
              <div className="source-entry-list target-entry-list">
                {targetEntries.map((entry) => (
                  <button
                    type="button"
                    key={entry.file_id}
                    className="source-entry"
                    onClick={() => void openTargetFolder(
                      { id: entry.file_id, name: entry.name, path: joinCloudPath(currentTargetFolder.path, entry.name) },
                    )}
                  >
                    <Folder size={19} weight="fill" />
                    <span><strong>{entry.name}</strong><small>进入文件夹</small></span>
                  </button>
                ))}
                {!targetEntries.length && <p className="transfer-placeholder">这个目录没有子目录，仍可选择当前目录。</p>}
              </div>
            )}
            <div className="target-directory-footer">
              <button
                type="button"
                className="compact-action"
                disabled={targetDirectoryState !== "ready"}
                onClick={() => setTargetPath(currentTargetFolder.path)}
              >
                <CheckCircle size={16} /> 选择当前目录
              </button>
              <small>已选：{targetPath || "尚未选择"}</small>
            </div>
          </div>
          <details className="target-manual-path">
            <summary>高级：手动输入兼容路径</summary>
            <label>115 绝对路径<input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="/strm/TV" /></label>
          </details>
          <label>目标文件名（可选）<input value={targetName} onChange={(event) => setTargetName(event.target.value)} placeholder={selected?.name || "选择源文件后可改名"} /></label>
          <div className="transfer-intent-summary">
            <span>源文件</span><strong>{selected ? `${selected.name} · ${formatBytes(selected.size)}` : "尚未选择"}</strong>
            <span>执行策略</span><strong>{selected?.sha1_available ? "夸克原生 SHA1：先探测真正秒传" : "无夸克原生 SHA1：完整读取校验后探测内容复用，未命中再流式中转"}</strong>
            <span>本地落盘</span><strong>禁止；仅使用固定上限内存缓冲</strong>
          </div>
          <button type="button" className="primary" disabled={!sourceReady || busy} onClick={() => void createTransfer()}>
            {busy ? <CircleNotch className="spin" size={18} /> : <ArrowsLeftRight size={18} />} 创建可审阅转存任务
          </button>
        </section>
      </div>

      <section className="transfer-queue">
        <div className="transfer-queue-head"><div><strong>任务队列</strong><small>任务进度和失败上下文会留在工作台；不依赖 OpenList。</small></div></div>
        {!transfers.length ? <p className="transfer-placeholder">还没有跨盘转存任务。</p> : (
          <div className="transfer-queue-list">
            {transfers.map((transfer) => (
              <TransferRow
                key={transfer.id}
                transfer={transfer}
                busy={busy}
                canRun={Boolean(workspace?.quark_connected && targetDirectoryState === "ready")}
                onRun={runTransfer}
                onCancel={cancelTransfer}
                onDelete={deleteTransfer}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function TransferRow({ transfer, busy, canRun, onRun, onCancel, onDelete }: { transfer: CrossCloudTransfer; busy: boolean; canRun: boolean; onRun: (id: number) => Promise<void>; onCancel: (id: number) => Promise<void>; onDelete: (id: number) => Promise<void> }) {
  const progressBase = transfer.state === "fingerprinting" ? transfer.fingerprinted_bytes : transfer.uploaded_bytes;
  const progress = transfer.total_bytes ? Math.min(100, Math.round(progressBase / transfer.total_bytes * 100)) : 0;
  return (
    <article className="transfer-queue-item">
      <div className="transfer-queue-title"><FileVideo size={20} weight="fill" /><div><strong>{transfer.target_name}</strong><small>夸克 → 115 · {formatBytes(transfer.total_bytes)} · 尝试 {transfer.attempt || 0}</small></div><span className={`transfer-state state-${transfer.state}`}>{stateLabel(transfer.state)}</span></div>
      <p>{transfer.stage_message}</p>
      {activeStates.has(transfer.state) && <div className="transfer-progress"><span style={{ width: `${progress}%` }} /><small>{transfer.state === "fingerprinting" ? `源读取 / 指纹 ${progress}%` : `传输 ${progress}%`}</small></div>}
      <div className="transfer-queue-meta"><span>{rapidProbeLabel(transfer)}</span>{transfer.cleanup_state !== "not_needed" && <span>远端：{cleanupLabel(transfer.cleanup_state)}</span>}</div>
      <div className="transfer-queue-actions">
        {runnableStates.has(transfer.state) && <button type="button" className="primary compact-action" disabled={busy || !canRun} onClick={() => void onRun(transfer.id)}><Play size={15} weight="fill" /> {canRun ? "启动" : "连接就绪后启动"}</button>}
        {activeStates.has(transfer.state) && <button type="button" className="ghost compact-action" disabled={busy} onClick={() => void onCancel(transfer.id)}><X size={15} /> 请求停止</button>}
        {deletableStates.has(transfer.state) && transfer.cleanup_state !== "remote_cleanup_pending" && <button type="button" className="ghost compact-action danger-action" disabled={busy} onClick={() => void onDelete(transfer.id)}><Trash size={15} /> 删除记录</button>}
      </div>
    </article>
  );
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value < 1024) return `${Math.max(0, value || 0)} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let size = value / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[index]}`;
}

function stateLabel(state: string) {
  const labels: Record<string, string> = { created: "待启动", fingerprinting: "源读取 / 指纹", rapid_probe: "内容复用探测", upload_initializing: "初始化", streaming: "流式中转", target_confirming: "核对结果", completed: "已完成", failed_recoverable: "可恢复失败", paused_source_changed: "源文件变化", cancel_requested: "停止中", cancelled_with_remote_residue: "需清理" };
  return labels[state] || state;
}

function rapidProbeLabel(transfer: CrossCloudTransfer) {
  const trueRapid = transfer.strategy === "provider_sha1_rapid_then_stream";
  if (transfer.rapid_probe_result === "hit") {
    return trueRapid ? "秒传：真正 SHA1 秒传命中" : "内容复用：已命中（源已完整读取，非秒传）";
  }
  if (transfer.rapid_probe_result === "miss") {
    return trueRapid ? "秒传：未命中，已转流式传输" : "内容复用：未命中，已转流式传输";
  }
  return trueRapid ? "秒传：尚未探测" : "内容复用：尚未探测";
}

function joinCloudPath(parent: string, name: string) {
  const base = parent === "/" ? "" : parent.replace(/\/$/, "");
  return `${base}/${name}`;
}

function cleanupLabel(state: string) {
  if (state === "remote_cleanup_pending") return "状态需核对 / 清理";
  return state;
}
