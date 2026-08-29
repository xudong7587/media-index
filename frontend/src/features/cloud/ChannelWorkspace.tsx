import { ArrowClockwise, Broadcast, CheckCircle, Database, ListChecks, PaperPlaneTilt } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { api, ChannelCloudDownloadTarget, ChannelMessage, ChannelSubscription } from "../../lib/api";
import { SettingsToggle } from "../settings/SettingsFormParts";
import "./channel-workspace.css";

function keywordList(value: string) {
  return [...new Set(value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean))];
}

export function ChannelWorkspace() {
  const [subscriptions, setSubscriptions] = useState<ChannelSubscription[]>([]);
  const [messages, setMessages] = useState<ChannelMessage[]>([]);
  const [targets, setTargets] = useState<ChannelCloudDownloadTarget[]>([]);
  const [trackingEnabled, setTrackingEnabled] = useState(false);
  const [pollMinutes, setPollMinutes] = useState("5");
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
  const [busy, setBusy] = useState(false);

  const targetOptions = useMemo(() => {
    const grouped = new Map<string, Set<string>>();
    for (const target of targets) {
      const providers = grouped.get(target.child_name) || new Set<string>();
      providers.add(target.provider === "p115" ? "115" : "夸克");
      grouped.set(target.child_name, providers);
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b, "zh-CN"));
  }, [targets]);

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

  function resetEditor() {
    setChannelId(""); setDisplayName(""); setChannelEnabled(true); setAutoSaveResources(true);
    setPositiveKeywords(""); setNegativeKeywords(""); setAutoClassify(true); setCloudDownloadChild("");
    setLegacyWishlistTransfer(false); setRequireDouban(false); setDoubanTitles("");
  }

  async function save() {
    setBusy(true); setMessage("");
    try {
      const interval = Math.max(1, Math.min(Number(pollMinutes) || 5, 1440));
      await api.saveConfig({ telegram_channel_source_enabled: trackingEnabled, telegram_channel_poll_minutes: interval });
      const result = await api.saveChannelSubscription({
        channel_id: channelId, display_name: displayName, enabled: channelEnabled,
        auto_transfer: legacyWishlistTransfer, auto_save_resources: autoSaveResources,
        positive_keywords: keywordList(positiveKeywords), negative_keywords: keywordList(negativeKeywords),
        auto_classify: autoClassify, cloud_download_child: autoClassify ? "" : cloudDownloadChild,
        require_douban_match: requireDouban, douban_titles: keywordList(doubanTitles),
      });
      let feedback = `已保存频道 ${result.display_name || result.channel_id}。`;
      if (trackingEnabled && result.channel_id.startsWith("@")) {
        const sync = await api.syncChannelSources(result.channel_id); feedback += ` ${sync.message}`;
      } else if (result.channel_id.startsWith("@")) {
        feedback += " 追踪总开关当前关闭，规则已保存但不会自动拉取。";
      } else feedback += " 数字频道 ID 将通过已配置的 Bot 接收新消息。";
      setMessage(feedback); resetEditor(); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存频道失败"); }
    finally { setBusy(false); }
  }

  async function syncPublicSources() {
    setBusy(true); setMessage("");
    try { const result = await api.syncChannelSources(); setMessage(result.message); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "公开频道拉取失败"); }
    finally { setBusy(false); }
  }

  function edit(item: ChannelSubscription) {
    setChannelId(item.channel_id); setDisplayName(item.display_name || ""); setChannelEnabled(item.enabled);
    setAutoSaveResources(item.auto_save_resources); setPositiveKeywords(item.positive_keywords.join(", "));
    setNegativeKeywords(item.negative_keywords.join(", ")); setAutoClassify(item.auto_classify);
    setCloudDownloadChild(item.cloud_download_child || ""); setLegacyWishlistTransfer(item.auto_transfer);
    setRequireDouban(item.require_douban_match); setDoubanTitles(item.douban_titles.join("\n"));
  }

  return <div className="channel-workspace">
    <div className="workspace-section-heading"><div><p className="eyebrow">TELEGRAM → CLOUD DOWNLOAD</p><h2>追踪 TG 频道</h2><p>持续读取频道新消息；通过正向/反向关键词后，将支持的资源逐条转存到云下载暂存，再由现有整理、STRM 与 Emby 流程接管。</p></div><div className="settings-action-strip"><button type="button" className="ghost compact-action" disabled={busy || !trackingEnabled} onClick={() => void syncPublicSources()}><Database />立即检查频道</button><button type="button" className="ghost compact-action" disabled={busy} onClick={() => void refresh()}><ArrowClockwise />刷新记录</button></div></div>
    {message && <p className="workspace-message">{message}</p>}
    <div className="channel-tracking-master"><SettingsToggle label="开启 TG 频道追踪" help="公开频道按下方间隔自动读取；私有频道需要把已配置的 Telegram Bot 加入频道。" value={trackingEnabled} onChange={setTrackingEnabled} trueLabel="自动追踪" falseLabel="已暂停" /><label>公开频道检查间隔（分钟）<input type="number" min="1" max="1440" value={pollMinutes} onChange={(event) => setPollMinutes(event.target.value)} /></label></div>
    <div className="channel-layout">
      <section className="channel-rule-card">
        <div className="library-card-title"><Broadcast size={21} weight="fill" /><strong>{subscriptions.some((item) => item.channel_id === channelId) ? "编辑频道规则" : "新增频道规则"}</strong></div>
        <label>频道来源<input value={channelId} onChange={(event) => setChannelId(event.target.value)} placeholder="公开频道链接 / @频道名 / 私有频道数字 ID" /></label><small className="settings-field-help">公开频道示例：https://t.me/channel_name；私有频道填写 -100… 并将 Bot 加入频道。</small>
        <label>显示名称（可选）<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="影视发布频道" /></label>
        <div className="channel-rule-toggles"><SettingsToggle label="启用此频道" help="停用后保留历史，不再接收或拉取新消息。" value={channelEnabled} onChange={setChannelEnabled} trueLabel="已启用" falseLabel="已停用" /><SettingsToggle label="自动转存匹配资源" help="正向词为空代表全部允许；命中任一反向词时始终拒绝。每条链接独立建任务并去重。" value={autoSaveResources} onChange={setAutoSaveResources} trueLabel="自动转存" falseLabel="仅建索引" /><SettingsToggle label="自动分类" help="根据消息中的电影、剧集、动漫、综艺、纪录片或演唱会证据选择唯一对应的云下载直属子目录；无法唯一判断时停止并显示失败。" value={autoClassify} onChange={setAutoClassify} trueLabel="自动分类" falseLabel="指定目录" /></div>
        <div className="channel-keyword-grid"><label>正向关键词（可选）<textarea value={positiveKeywords} onChange={(event) => setPositiveKeywords(event.target.value)} placeholder="4K, REMUX, 国语；为空则全部允许" /></label><label>反向关键词（可选）<textarea value={negativeKeywords} onChange={(event) => setNegativeKeywords(event.target.value)} placeholder="预告, 花絮, 枪版, 低清" /></label></div>
        {!autoClassify && <label>云下载直属子目录<select value={cloudDownloadChild} onChange={(event) => setCloudDownloadChild(event.target.value)}><option value="">请选择</option>{targetOptions.map(([name, providers]) => <option value={name} key={name}>{name} · {[...providers].join(" / ")}</option>)}</select><small className="settings-field-help">资源属于哪个网盘，就在该网盘的云下载根下使用这个同名直属子目录；不存在时安全失败。</small></label>}
        <details className="channel-legacy-rule"><summary>兼容旧版愿望单规则</summary><div className="channel-rule-toggles"><SettingsToggle label="愿望单唯一命中后建任务" help="仅在关闭上面的全资源自动转存时使用。" value={legacyWishlistTransfer} onChange={setLegacyWishlistTransfer} trueLabel="启用" falseLabel="关闭" /><SettingsToggle label="同时要求豆瓣白名单" help="旧规则的附加过滤，不影响 TG 正/反关键词。" value={requireDouban} onChange={setRequireDouban} trueLabel="要求" falseLabel="不要求" /></div><label>豆瓣榜单标题（每行一个）<textarea value={doubanTitles} onChange={(event) => setDoubanTitles(event.target.value)} /></label></details>
        <button type="button" className="primary" disabled={busy || !channelId.trim() || (autoSaveResources && !autoClassify && !cloudDownloadChild)} onClick={() => void save()}><PaperPlaneTilt size={17} />保存频道追踪</button>
      </section>
      <section className="channel-status-card"><div className="library-card-title"><ListChecks size={21} weight="fill" /><strong>已追踪频道</strong></div><ol><li>公开频道由 MediaIndex 定时拉取近期新消息；私有频道由 Bot 实时接收。</li><li>反向关键词优先拒绝；正向关键词为空时匹配全部。</li><li>自动分类必须得到唯一分类和唯一子目录，否则不会猜测目标。</li><li>转存只进入云下载暂存；整理成功后继续现有 STRM、Emby 与通知。</li></ol><div className="channel-subscription-list">{subscriptions.length ? subscriptions.map((item) => <button type="button" key={item.id} onClick={() => edit(item)}><CheckCircle size={17} weight="fill" /><span><strong>{item.display_name || item.channel_id}</strong><small>{item.enabled ? (item.channel_id.startsWith("@") ? `每 ${pollMinutes} 分钟检查` : "Bot 实时接收") : "已停用"} · {item.auto_save_resources ? `${item.auto_classify ? "自动分类" : item.cloud_download_child || "未选目录"}后转存` : "仅候选索引"}{item.last_error ? ` · ${item.last_error}` : item.last_checked_at ? ` · 最近 ${new Date(item.last_checked_at).toLocaleString()}` : ""}</small></span></button>) : <p className="transfer-placeholder">尚未追踪频道。</p>}</div></section>
    </div>
    <section className="library-assets"><div className="transfer-queue-head"><div><strong>频道消息与转存结果</strong><small>分享链接本身不会在页面回显；多链接按资源分别去重、提交和记录。</small></div></div>{messages.length ? <div className="library-asset-list">{messages.map((item) => <article key={item.id} className="channel-message"><span className={`transfer-state state-${item.state}`}>{item.state}</span><div><strong>{item.display_name || item.channel_id} · 消息 {item.message_id}</strong><small>识别 {item.indexed_resource_count || 0} 个资源 · {item.message_safe}{item.transfer_job_ids?.length ? ` · 任务 ${item.transfer_job_ids.map((id) => `#${id}`).join("、")}` : ""}</small><p>{item.text_preview}</p></div></article>)}</div> : <p className="transfer-placeholder">等待频道新消息。</p>}</section>
  </div>;
}
