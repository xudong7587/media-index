import {
  ArrowClockwise, Broadcast, CheckCircle, CircleNotch, Database, Funnel,
  MagnifyingGlass, PaperPlaneTilt, PauseCircle, Plus, SlidersHorizontal,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { api, ChannelCloudDownloadTarget, ChannelMessage, ChannelSubscription } from "../../lib/api";
import { SettingsToggle } from "../settings/SettingsFormParts";
import "./channel-workspace.css";

type WorkspaceView = "channels" | "activity";
type ChannelFilter = "all" | "active" | "setup" | "paused";
const PAGE_SIZE = 8;

function keywordList(value: string) {
  return [...new Set(value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean))];
}

function needsSetup(item: ChannelSubscription) {
  return item.enabled && !item.auto_save_resources && !item.auto_transfer
    && item.positive_keywords.length === 0 && item.negative_keywords.length === 0
    && !item.cloud_download_child;
}

function channelMode(item: ChannelSubscription) {
  if (!item.enabled) return "已停用";
  if (needsSetup(item)) return "待配置";
  if (!item.auto_save_resources) return "仅建索引";
  return item.auto_classify ? "自动分类转存" : `转存到 ${item.cloud_download_child || "未选目录"}`;
}

export function ChannelWorkspace() {
  const [subscriptions, setSubscriptions] = useState<ChannelSubscription[]>([]);
  const [messages, setMessages] = useState<ChannelMessage[]>([]);
  const [targets, setTargets] = useState<ChannelCloudDownloadTarget[]>([]);
  const [trackingEnabled, setTrackingEnabled] = useState(false);
  const [pollMinutes, setPollMinutes] = useState("5");
  const [view, setView] = useState<WorkspaceView>("channels");
  const [filter, setFilter] = useState<ChannelFilter>("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [channelId, setChannelId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [channelEnabled, setChannelEnabled] = useState(true);
  const [autoSaveResources, setAutoSaveResources] = useState(true);
  const [positiveKeywords, setPositiveKeywords] = useState("");
  const [negativeKeywords, setNegativeKeywords] = useState("");
  const [autoClassify, setAutoClassify] = useState(true);
  const [cloudDownloadChild, setCloudDownloadChild] = useState("");
  const [legacyWishlistTransfer, setLegacyWishlistTransfer] = useState(false);
  const [requireDouban, setRequireDouban] = useState(false);
  const [doubanTitles, setDoubanTitles] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"refresh" | "settings" | "channel" | "">("");

  const targetOptions = useMemo(() => {
    const grouped = new Map<string, Set<string>>();
    for (const target of targets) {
      const providers = grouped.get(target.child_name) || new Set<string>();
      providers.add(target.provider === "p115" ? "115" : "夸克");
      grouped.set(target.child_name, providers);
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b, "zh-CN"));
  }, [targets]);

  const counts = useMemo(() => ({
    all: subscriptions.length,
    active: subscriptions.filter((item) => item.enabled && !needsSetup(item)).length,
    setup: subscriptions.filter(needsSetup).length,
    paused: subscriptions.filter((item) => !item.enabled).length,
  }), [subscriptions]);

  const filteredSubscriptions = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("zh-CN");
    return subscriptions.filter((item) => {
      if (filter === "active" && (!item.enabled || needsSetup(item))) return false;
      if (filter === "setup" && !needsSetup(item)) return false;
      if (filter === "paused" && item.enabled) return false;
      return !needle || `${item.display_name} ${item.channel_id}`.toLocaleLowerCase("zh-CN").includes(needle);
    });
  }, [filter, query, subscriptions]);
  const pageCount = Math.max(1, Math.ceil(filteredSubscriptions.length / PAGE_SIZE));
  const visibleSubscriptions = filteredSubscriptions.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const selected = subscriptions.find((item) => item.id === selectedId) || null;

  async function refresh() {
    const [nextSubscriptions, nextMessages, config, p115Targets, quarkTargets] = await Promise.all([
      api.channelSubscriptions(), api.channelMessages(), api.config(),
      api.channelCloudDownloadTargets("p115").catch(() => []),
      api.channelCloudDownloadTargets("quark").catch(() => []),
    ]);
    setSubscriptions(nextSubscriptions); setMessages(nextMessages);
    setTrackingEnabled(config.telegram_channel_source_enabled);
    setPollMinutes(String(config.telegram_channel_poll_minutes || 5));
    setTargets([...p115Targets, ...quarkTargets]);
  }

  useEffect(() => { void refresh().catch((error: Error) => setMessage(error.message)); }, []);
  useEffect(() => { setPage(1); }, [filter, query]);
  useEffect(() => { if (page > pageCount) setPage(pageCount); }, [page, pageCount]);

  function resetEditor() {
    setSelectedId(null); setChannelId(""); setDisplayName(""); setChannelEnabled(true); setAutoSaveResources(true);
    setPositiveKeywords(""); setNegativeKeywords(""); setAutoClassify(true); setCloudDownloadChild("");
    setLegacyWishlistTransfer(false); setRequireDouban(false); setDoubanTitles("");
  }

  function edit(item: ChannelSubscription) {
    setSelectedId(item.id); setChannelId(item.channel_id); setDisplayName(item.display_name || ""); setChannelEnabled(item.enabled);
    setAutoSaveResources(item.auto_save_resources); setPositiveKeywords(item.positive_keywords.join(", "));
    setNegativeKeywords(item.negative_keywords.join(", ")); setAutoClassify(item.auto_classify);
    setCloudDownloadChild(item.cloud_download_child || ""); setLegacyWishlistTransfer(item.auto_transfer);
    setRequireDouban(item.require_douban_match); setDoubanTitles(item.douban_titles.join("\n"));
  }

  async function saveTrackingSettings() {
    setBusy("settings"); setMessage("");
    try {
      const interval = Math.max(1, Math.min(Number(pollMinutes) || 5, 1440));
      await api.saveConfig({ telegram_channel_source_enabled: trackingEnabled, telegram_channel_poll_minutes: interval });
      setPollMinutes(String(interval)); setMessage("TG 追踪总开关与检查间隔已保存。"); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "追踪设置保存失败"); }
    finally { setBusy(""); }
  }

  async function saveChannel() {
    setBusy("channel"); setMessage("");
    try {
      const result = await api.saveChannelSubscription({
        channel_id: channelId, display_name: displayName, enabled: channelEnabled,
        auto_transfer: legacyWishlistTransfer, auto_save_resources: autoSaveResources,
        positive_keywords: keywordList(positiveKeywords), negative_keywords: keywordList(negativeKeywords),
        auto_classify: autoClassify, cloud_download_child: autoClassify ? "" : cloudDownloadChild,
        require_douban_match: requireDouban, douban_titles: keywordList(doubanTitles),
      });
      let feedback = `已保存频道 ${result.display_name || result.channel_id} 的独立规则。`;
      if (trackingEnabled && result.channel_id.startsWith("@")) {
        const sync = await api.syncChannelSources(result.channel_id); feedback += ` ${sync.message}`;
      } else if (result.channel_id.startsWith("@") && !trackingEnabled) feedback += " 总开关当前关闭，规则暂不执行。";
      else feedback += " 数字频道 ID 通过已配置的 Bot 接收新消息。";
      setMessage(feedback); await refresh(); edit(result);
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存频道失败"); }
    finally { setBusy(""); }
  }

  async function syncPublicSources() {
    setBusy("refresh"); setMessage("");
    try { const result = await api.syncChannelSources(); setMessage(result.message); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "公开频道拉取失败"); }
    finally { setBusy(""); }
  }

  return <div className="channel-workspace">
    <div className="workspace-section-heading channel-workspace-heading"><div><p className="eyebrow">TELEGRAM → CLOUD DOWNLOAD</p><h2>追踪 TG 频道</h2><p>每个频道拥有自己的关键词、转存方式和目录；匹配资源先进入云下载，再由整理、STRM 与 Emby 流程接管。</p></div><div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={Boolean(busy) || !trackingEnabled} onClick={() => void syncPublicSources()}>{busy === "refresh" ? <CircleNotch className="spin" /> : <Database />}立即检查</button><button type="button" className="ghost compact-action" disabled={Boolean(busy)} onClick={() => void refresh()}><ArrowClockwise />刷新</button></div></div>
    {message && <p className="workspace-message" role="status">{message}</p>}
    <section className="channel-control-bar"><div className="channel-control-summary"><span className={trackingEnabled ? "is-on" : ""}>{trackingEnabled ? <CheckCircle weight="fill" /> : <PauseCircle weight="fill" />}</span><div><strong>{trackingEnabled ? "频道追踪正在运行" : "频道追踪已暂停"}</strong><small>{counts.active} 个有效频道 · {counts.setup} 个待配置 · 公开频道每 {pollMinutes || 5} 分钟检查</small></div></div><div className="channel-control-settings"><SettingsToggle label="追踪总开关" help="控制所有频道的自动读取；单个频道仍有自己的启用开关。" value={trackingEnabled} onChange={setTrackingEnabled} trueLabel="运行" falseLabel="暂停" /><label>检查间隔<input type="number" min="1" max="1440" value={pollMinutes} onChange={(event) => setPollMinutes(event.target.value)} /><small>分钟</small></label><button type="button" className="primary compact-action" disabled={Boolean(busy)} onClick={() => void saveTrackingSettings()}>{busy === "settings" && <CircleNotch className="spin" />}保存运行设置</button></div></section>
    <div className="channel-view-tabs" role="tablist" aria-label="TG 频道追踪页面"><button type="button" role="tab" aria-selected={view === "channels"} className={view === "channels" ? "active" : ""} onClick={() => setView("channels")}><SlidersHorizontal />频道与规则 <span>{subscriptions.length}</span></button><button type="button" role="tab" aria-selected={view === "activity"} className={view === "activity" ? "active" : ""} onClick={() => setView("activity")}><PaperPlaneTilt />运行记录 <span>{messages.length}</span></button></div>
    {view === "channels" ? <ChannelManager subscriptions={subscriptions} selectedId={selectedId} selected={selected} visibleSubscriptions={visibleSubscriptions} filteredCount={filteredSubscriptions.length} counts={counts} filter={filter} query={query} page={page} pageCount={pageCount} busy={Boolean(busy)} channelId={channelId} displayName={displayName} channelEnabled={channelEnabled} autoSaveResources={autoSaveResources} positiveKeywords={positiveKeywords} negativeKeywords={negativeKeywords} autoClassify={autoClassify} cloudDownloadChild={cloudDownloadChild} legacyWishlistTransfer={legacyWishlistTransfer} requireDouban={requireDouban} doubanTitles={doubanTitles} targetOptions={targetOptions} onFilter={setFilter} onQuery={setQuery} onPage={setPage} onNew={resetEditor} onEdit={edit} onChannelId={setChannelId} onDisplayName={setDisplayName} onChannelEnabled={setChannelEnabled} onAutoSave={setAutoSaveResources} onPositive={setPositiveKeywords} onNegative={setNegativeKeywords} onAutoClassify={setAutoClassify} onTarget={setCloudDownloadChild} onLegacy={setLegacyWishlistTransfer} onRequireDouban={setRequireDouban} onDoubanTitles={setDoubanTitles} onSave={() => void saveChannel()} /> : <ActivityPanel messages={messages} />}
  </div>;
}

type ManagerProps = {
  subscriptions: ChannelSubscription[]; selectedId: number | null; selected: ChannelSubscription | null; visibleSubscriptions: ChannelSubscription[]; filteredCount: number;
  counts: Record<ChannelFilter, number>; filter: ChannelFilter; query: string; page: number; pageCount: number; busy: boolean;
  channelId: string; displayName: string; channelEnabled: boolean; autoSaveResources: boolean; positiveKeywords: string; negativeKeywords: string; autoClassify: boolean; cloudDownloadChild: string;
  legacyWishlistTransfer: boolean; requireDouban: boolean; doubanTitles: string; targetOptions: [string, Set<string>][];
  onFilter: (value: ChannelFilter) => void; onQuery: (value: string) => void; onPage: (value: number | ((value: number) => number)) => void; onNew: () => void; onEdit: (item: ChannelSubscription) => void;
  onChannelId: (value: string) => void; onDisplayName: (value: string) => void; onChannelEnabled: (value: boolean) => void; onAutoSave: (value: boolean) => void; onPositive: (value: string) => void; onNegative: (value: string) => void; onAutoClassify: (value: boolean) => void; onTarget: (value: string) => void; onLegacy: (value: boolean) => void; onRequireDouban: (value: boolean) => void; onDoubanTitles: (value: string) => void; onSave: () => void;
};

function ChannelManager(props: ManagerProps) {
  return <div className="channel-manager"><section className="channel-directory" aria-label="频道目录">
    <header><div><small>CHANNEL DIRECTORY</small><h3>频道目录</h3><p>先选择一个频道，再编辑它自己的规则。</p></div><button type="button" className="ghost compact-action" onClick={props.onNew}><Plus />新增频道</button></header>
    {props.counts.setup > 0 && <div className="channel-import-note"><Funnel weight="duotone" /><p><strong>{props.counts.setup} 个频道等待配置</strong><span>旧版收集但尚未启用自动转存的来源集中在这里。它们现在只建索引，不会写入网盘。</span></p><button type="button" onClick={() => props.onFilter("setup")}>只看待配置</button></div>}
    <label className="channel-search"><MagnifyingGlass /><input value={props.query} onChange={(event) => props.onQuery(event.target.value)} placeholder="搜索频道名称或 @用户名" /></label>
    <div className="channel-filter-row" role="group" aria-label="筛选频道">{([ ["all", "全部"], ["active", "有效"], ["setup", "待配置"], ["paused", "已停用"] ] as const).map(([value, label]) => <button type="button" className={props.filter === value ? "active" : ""} onClick={() => props.onFilter(value)} key={value}>{label}<span>{props.counts[value]}</span></button>)}</div>
    <div className="channel-directory-list">{props.visibleSubscriptions.length ? props.visibleSubscriptions.map((item) => <button type="button" key={item.id} className={`${props.selectedId === item.id ? "selected" : ""} ${needsSetup(item) ? "needs-setup" : ""}`} onClick={() => props.onEdit(item)}><span className="channel-directory-state">{!item.enabled ? <PauseCircle weight="fill" /> : <Broadcast weight="fill" />}</span><span><strong>{item.display_name || item.channel_id}</strong><small>{item.channel_id}</small><em>{channelMode(item)}</em></span></button>) : <p className="transfer-placeholder">没有符合条件的频道。</p>}</div>
    {props.pageCount > 1 && <footer className="channel-pagination"><button type="button" disabled={props.page === 1} onClick={() => props.onPage((value) => value - 1)}>上一页</button><span>{props.page} / {props.pageCount} · 共 {props.filteredCount} 个</span><button type="button" disabled={props.page === props.pageCount} onClick={() => props.onPage((value) => value + 1)}>下一页</button></footer>}
  </section><section className="channel-rule-card">
    <header className="channel-rule-head"><div><small>{props.selected ? "INDEPENDENT RULE" : "NEW CHANNEL"}</small><h3>{props.selected ? (props.selected.display_name || props.selected.channel_id) : "新增频道规则"}</h3><p>{props.selected ? "修改只影响当前频道，不会覆盖 PanSou 或其他频道。" : "添加一个公开频道，或填写已加入 Bot 的私有频道 ID。"}</p></div>{props.selected && <span className={needsSetup(props.selected) ? "setup" : "ready"}>{channelMode(props.selected)}</span>}</header>
    <div className="channel-form-section"><strong>1. 频道身份</strong><div className="channel-identity-grid"><label>频道来源<input value={props.channelId} disabled={Boolean(props.selected)} onChange={(event) => props.onChannelId(event.target.value)} placeholder="@频道名 / t.me 链接 / -100…" /></label><label>显示名称（可选）<input value={props.displayName} onChange={(event) => props.onDisplayName(event.target.value)} placeholder="影视发布频道" /></label></div><small className="settings-field-help">公开频道使用 @用户名或 t.me 链接；私有频道填写 -100… 数字 ID，并把已配置的 Bot 加入频道。保存后频道 ID 不可修改。</small></div>
    <div className="channel-form-section"><strong>2. 这条规则是否执行</strong><div className="channel-rule-toggles"><SettingsToggle label="启用此频道" help="停用后保留规则与历史，但不再接收新消息。" value={props.channelEnabled} onChange={props.onChannelEnabled} trueLabel="已启用" falseLabel="已停用" /><SettingsToggle label="自动转存匹配资源" help="关闭后只记录消息和候选资源，不写入网盘。" value={props.autoSaveResources} onChange={props.onAutoSave} trueLabel="自动转存" falseLabel="仅建索引" /></div></div>
    <div className="channel-form-section"><strong>3. 哪些消息符合条件</strong><div className="channel-keyword-grid"><label>必须包含（正向词）<textarea value={props.positiveKeywords} onChange={(event) => props.onPositive(event.target.value)} placeholder="4K, REMUX, 国语；为空表示全部允许" /><small>命中任意一个即可；为空不过滤。</small></label><label>必须排除（反向词）<textarea value={props.negativeKeywords} onChange={(event) => props.onNegative(event.target.value)} placeholder="预告, 花絮, 枪版, 低清" /><small>命中任意一个立即拒绝，优先级最高。</small></label></div></div>
    {props.autoSaveResources && <div className="channel-form-section"><strong>4. 转存到哪里</strong><SettingsToggle label="自动识别分类" help="仅当消息分类与云下载直属目录均唯一时转存；判断不清会停止，不会猜目录。" value={props.autoClassify} onChange={props.onAutoClassify} trueLabel="自动分类" falseLabel="指定目录" />{!props.autoClassify && <label className="channel-target-field">云下载直属子目录<select value={props.cloudDownloadChild} onChange={(event) => props.onTarget(event.target.value)}><option value="">请选择</option>{props.targetOptions.map(([name, providers]) => <option value={name} key={name}>{name} · {[...providers].join(" / ")}</option>)}</select><small>资源属于哪个网盘，就使用该网盘云下载根下的同名直属子目录。</small></label>}</div>}
    <details className="channel-legacy-rule"><summary>旧版兼容规则（通常不需要）</summary><div className="channel-rule-toggles"><SettingsToggle label="愿望单唯一命中后建任务" help="仅在关闭全资源自动转存时使用。" value={props.legacyWishlistTransfer} onChange={props.onLegacy} trueLabel="启用" falseLabel="关闭" /><SettingsToggle label="同时要求豆瓣白名单" help="旧规则的附加过滤，不影响本页正反关键词。" value={props.requireDouban} onChange={props.onRequireDouban} trueLabel="要求" falseLabel="不要求" /></div><label>豆瓣榜单标题（每行一个）<textarea value={props.doubanTitles} onChange={(event) => props.onDoubanTitles(event.target.value)} /></label></details>
    <footer className="channel-rule-footer"><span>{props.selected ? "保存后立即替换当前频道规则" : "每个频道都从一份独立规则开始"}</span><button type="button" className="primary" disabled={props.busy || !props.channelId.trim() || (props.autoSaveResources && !props.autoClassify && !props.cloudDownloadChild)} onClick={props.onSave}><PaperPlaneTilt />{props.selected ? "保存当前频道" : "添加并保存"}</button></footer>
  </section></div>;
}

function ActivityPanel({ messages }: { messages: ChannelMessage[] }) {
  return <section className="channel-activity-panel"><header><div><small>ACTIVITY</small><h3>频道消息与转存结果</h3><p>这里用于核对规则是否命中和转存任务是否建立；分享链接本身不会回显。</p></div></header>{messages.length ? <div className="library-asset-list">{messages.map((item) => <article key={item.id} className="channel-message"><span className={`transfer-state state-${item.state}`}>{item.state}</span><div><strong>{item.display_name || item.channel_id} · 消息 {item.message_id}</strong><small>识别 {item.indexed_resource_count || 0} 个资源 · {item.message_safe}{item.transfer_job_ids?.length ? ` · 任务 ${item.transfer_job_ids.map((id) => `#${id}`).join("、")}` : ""}</small><p>{item.text_preview}</p></div></article>)}</div> : <p className="transfer-placeholder">等待频道新消息。</p>}</section>;
}
