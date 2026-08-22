import { ArrowsClockwise, FileVideo, FolderSimple, ListChecks, PlayCircle, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ConfigStatus, DeletionIntent, MediaAsset, StrmEntry } from "../../lib/api";

export function MediaLibraryWorkspace({ config, onConfigChanged, initialInventoryProvider = "p115" }: { config: ConfigStatus | null; onConfigChanged: () => Promise<void>; initialInventoryProvider?: "p115" | "quark" }) {
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [entries, setEntries] = useState<StrmEntry[]>([]);
  const [intents, setIntents] = useState<DeletionIntent[]>([]);
  const [inventoryRoot, setInventoryRoot] = useState(config?.p115_root_path || "/strm");
  const [inventoryProvider, setInventoryProvider] = useState<"p115" | "quark">(initialInventoryProvider);
  const [outputRoot, setOutputRoot] = useState(config?.strm_output_root || "");
  const [webhookToken, setWebhookToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [nextAssets, nextEntries, nextIntents] = await Promise.all([api.mediaAssets(), api.strmEntries(), api.deletionIntents()]);
    setAssets(nextAssets);
    setEntries(nextEntries);
    setIntents(nextIntents);
  }

  useEffect(() => { void refresh().catch((error: Error) => setMessage(error.message)); }, []);
  useEffect(() => {
    if (!config) return;
    setInventoryRoot((value) => value || config.p115_root_path || "/strm");
    setOutputRoot((value) => value || config.strm_output_root || "");
  }, [config]);
  useEffect(() => {
    setInventoryProvider(initialInventoryProvider);
    setInventoryRoot(initialInventoryProvider === "p115" ? config?.p115_root_path || "/strm" : config?.quark_root_path || "/strm");
  }, [config, initialInventoryProvider]);

  async function scanInventory() {
    setBusy(true); setMessage("");
    try {
      const result = inventoryProvider === "p115" ? await api.scanP115Inventory(inventoryRoot) : await api.scanQuarkInventory(inventoryRoot);
      setMessage(`已只读索引 ${result.files_indexed} 个文件、${result.directories_scanned} 个目录${result.truncated ? "（达到本次上限）" : ""}。`);
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "索引失败"); }
    finally { setBusy(false); }
  }

  async function reconcile() {
    setBusy(true); setMessage("");
    try {
      await api.saveConfig({ strm_output_root: outputRoot });
      await onConfigChanged();
      const result = await api.reconcileStrm({ output_root: outputRoot });
      setMessage(`STRM 校正完成：新增 ${result.created}，替换 ${result.replaced}，保持 ${result.unchanged}，过滤 ${result.filtered}，冲突 ${result.conflicts}，清理 ${result.removed}。`);
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "STRM 校正失败"); }
    finally { setBusy(false); }
  }

  async function createDeletion(assetId: number) {
    setBusy(true); setMessage("");
    try {
      const intent = await api.createDeletionIntent(assetId);
      setMessage(`已创建回收意图 #${intent.id}。请确认后才会将精确文件 ID 移入 115 回收站。`);
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "创建删除意图失败"); }
    finally { setBusy(false); }
  }

  async function confirmDeletion(intentId: number) {
    setBusy(true); setMessage("");
    try {
      const intent = await api.confirmDeletionIntent(intentId);
      setMessage(`删除意图 #${intent.id} 已完成：文件已移入 115 回收站，而不是永久删除。`);
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "确认删除失败"); }
    finally { setBusy(false); }
  }

  async function saveDeletionWebhook() {
    setBusy(true); setMessage("");
    try {
      await api.saveConfig({ emby_deletion_webhook_token: webhookToken });
      await onConfigChanged();
      setWebhookToken("");
      setMessage("已保存 Emby 删除同步密钥。Webhook 只会按已登记的精确 STRM 映射创建回收意图。\n接口：/api/integrations/emby/strm-deleted（Header: X-MediaIndex-Webhook）。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存删除同步设置失败"); }
    finally { setBusy(false); }
  }

  return (
    <div className="library-workspace">
      <div className="workspace-section-heading"><div><p className="eyebrow">ASSET REGISTRY</p><h2>媒体资产与 STRM</h2><p>网盘文件先登记为资产，再生成可替换、可核对的 STRM。不会从现有 STRM 文本反向猜测网盘文件。</p></div></div>
      {message && <p className="workspace-message">{message}</p>}
      <div className="library-setup-grid">
        <section className="library-card">
          <div className="library-card-title"><FolderSimple size={21} weight="fill" /><strong>1. 只读建立网盘资产索引</strong></div>
          <p>扫描只读取已有目录和文件 ID；目录不存在时会停止，不会自动创建。</p>
          <label>网盘<select value={inventoryProvider} onChange={(event) => { const next = event.target.value as "p115" | "quark"; setInventoryProvider(next); setInventoryRoot(next === "p115" ? config?.p115_root_path || "/strm" : config?.quark_root_path || "/strm"); }}><option value="p115">115</option><option value="quark">原生夸克</option></select></label>
          <label>{inventoryProvider === "p115" ? "115" : "夸克"} 索引根目录<input value={inventoryRoot} onChange={(event) => setInventoryRoot(event.target.value)} placeholder="/strm" /></label>
          <button type="button" className="ghost" disabled={busy || inventoryProvider === "p115" && !config?.has_p115_cookie && !config?.has_p115_open || inventoryProvider === "quark" && !config?.has_quark_cookie} onClick={() => void scanInventory()}><ListChecks size={17} /> 开始只读索引</button>
        </section>
        <section className="library-card">
          <div className="library-card-title"><PlayCircle size={21} weight="fill" /><strong>2. 校正 STRM 与 302 播放入口</strong></div>
          <p>STRM 只写入 MediaIndex 的签名播放地址，不写入网盘 Cookie 或临时直链。</p>
          <label>STRM 输出目录<input value={outputRoot} onChange={(event) => setOutputRoot(event.target.value)} placeholder="例如 D:\\Media\\strm 或已挂载路径" /></label>
          <p>优先使用已配置的 STRM 播放地址；未配置时才使用 Emby 主机与 302 内网端口自动生成。</p>
          <button type="button" className="primary" disabled={busy || !outputRoot.trim()} onClick={() => void reconcile()}><ArrowsClockwise size={17} /> 保存并全量校正</button>
        </section>
        <section className="library-card">
          <div className="library-card-title"><Trash size={21} weight="fill" /><strong>3. Emby 删除同步（回收站）</strong></div>
          <p>Emby 事件只能凭精确的 MediaIndex STRM 路径创建意图；确认后才会将对应 115 文件移入回收站。</p>
          <label>Webhook 密钥<input type="password" value={webhookToken} onChange={(event) => setWebhookToken(event.target.value)} placeholder={config?.has_emby_deletion_webhook_token ? "已保存；填写新值可轮换" : "设置一个仅供 Emby 调用的随机密钥"} /></label>
          <button type="button" className="ghost" disabled={busy || !webhookToken.trim()} onClick={() => void saveDeletionWebhook()}>保存删除同步密钥</button>
        </section>
      </div>
      <div className="library-summary"><span><strong>{assets.length}</strong> 个资产</span><span><strong>{entries.length}</strong> 条 MediaIndex STRM 映射</span><span>冲突资产会进入待复核，避免覆盖同名媒体。</span></div>
      <section className="library-assets"><div className="transfer-queue-head"><div><strong>资产清单</strong><small>文件 ID 是删除、播放和同步的唯一依据；名称/路径只用于显示与组织。</small></div></div>{assets.length ? <div className="library-asset-list">{assets.slice(0, 100).map((asset) => <article key={asset.id} className="library-asset"><FileVideo size={19} weight="fill" /><div><strong>{asset.name}</strong><small>{asset.provider} · {formatBytes(asset.size)} · 文件 ID {asset.file_id}</small></div><span className={`transfer-state state-${asset.status}`}>{asset.status === "ready" ? "可播放" : asset.status === "discovered" ? "已发现" : asset.status === "needs_review" ? "待复核" : asset.status}</span>{asset.status === "ready" && asset.provider === "p115" && <button type="button" className="compact-action danger-action" disabled={busy} onClick={() => void createDeletion(asset.id)}>移入回收站…</button>}</article>)}</div> : <p className="transfer-placeholder">先通过跨盘任务或只读索引登记资产。</p>}</section>
      {intents.some((intent) => intent.state === "requested") && <section className="library-assets deletion-intents"><div className="transfer-queue-head"><div><strong>待确认回收意图</strong><small>不会按名称猜测，也不会永久删除；确认只操作此处显示的文件 ID。</small></div></div><div className="library-asset-list">{intents.filter((intent) => intent.state === "requested").map((intent) => <article key={intent.id} className="library-asset"><Trash size={19} weight="fill" /><div><strong>{intent.asset_name}</strong><small>文件 ID {intent.file_id} · {intent.trigger_source} · {intent.message_safe}</small></div><button type="button" className="compact-action danger-action" disabled={busy} onClick={() => void confirmDeletion(intent.id)}>确认移入回收站</button></article>)}</div></section>}
    </div>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"]; let size = value / 1024; let index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[index]}`;
}
