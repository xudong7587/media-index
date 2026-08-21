import { ArrowClockwise, Broadcast, CheckCircle, Database, ListChecks, PaperPlaneTilt } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ChannelMessage, ChannelSubscription } from "../../lib/api";
import { SettingsToggle } from "../settings/SettingsFormParts";

export function ChannelWorkspace() {
  const [subscriptions, setSubscriptions] = useState<ChannelSubscription[]>([]);
  const [messages, setMessages] = useState<ChannelMessage[]>([]);
  const [channelId, setChannelId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [channelEnabled, setChannelEnabled] = useState(true);
  const [autoTransfer, setAutoTransfer] = useState(false);
  const [requireDouban, setRequireDouban] = useState(false);
  const [doubanTitles, setDoubanTitles] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [nextSubscriptions, nextMessages] = await Promise.all([api.channelSubscriptions(), api.channelMessages()]);
    setSubscriptions(nextSubscriptions);
    setMessages(nextMessages);
  }

  useEffect(() => { void refresh().catch((error: Error) => setMessage(error.message)); }, []);

  async function save() {
    setBusy(true);
    setMessage("");
    try {
      const titles = doubanTitles.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
      const result = await api.saveChannelSubscription({
        channel_id: channelId,
        display_name: displayName,
        enabled: channelEnabled,
        auto_transfer: autoTransfer,
        require_douban_match: requireDouban,
        douban_titles: titles,
      });
      let feedback = `已保存频道 ${result.display_name || result.channel_id}。`;
      if (result.channel_id.startsWith("@")) {
        const sync = await api.syncChannelSources(result.channel_id);
        feedback += ` ${sync.message}`;
      } else {
        feedback += " 数字频道 ID 将通过 Bot 接收新消息。";
      }
      setMessage(feedback);
      setChannelId("");
      setDisplayName("");
      setChannelEnabled(true);
      setAutoTransfer(false);
      setRequireDouban(false);
      setDoubanTitles("");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存频道失败");
    } finally {
      setBusy(false);
    }
  }

  async function syncPublicSources() {
    setBusy(true);
    setMessage("");
    try {
      const result = await api.syncChannelSources();
      setMessage(result.message);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "公开频道拉取失败");
    } finally {
      setBusy(false);
    }
  }

  function edit(item: ChannelSubscription) {
    setChannelId(item.channel_id);
    setDisplayName(item.display_name || "");
    setChannelEnabled(item.enabled);
    setAutoTransfer(item.auto_transfer);
    setRequireDouban(item.require_douban_match);
    setDoubanTitles(item.douban_titles.join("\n"));
  }

  return <div className="channel-workspace">
    <div className="workspace-section-heading">
      <div>
        <p className="eyebrow">TELEGRAM RESOURCE INDEX</p>
        <h2>TG 频道资源基座</h2>
        <p>频道里的夸克与 115 链接会先进入统一候选索引；发现详情、愿望单和追更补集都从这里检索，再执行 TMDB、验真和转存规则。</p>
      </div>
      <div className="settings-action-strip">
        <button type="button" className="ghost compact-action" disabled={busy} onClick={() => void syncPublicSources()}><Database />立即更新频道索引</button>
        <button type="button" className="ghost compact-action" disabled={busy} onClick={() => void refresh()}><ArrowClockwise />刷新记录</button>
      </div>
    </div>
    {message && <p className="workspace-message">{message}</p>}
    <div className="channel-layout">
      <section className="channel-rule-card">
        <div className="library-card-title"><Broadcast size={21} weight="fill" /><strong>{subscriptions.some((item) => item.channel_id === channelId) ? "编辑频道规则" : "新增频道规则"}</strong></div>
        <label>频道来源<input value={channelId} onChange={(event) => setChannelId(event.target.value)} placeholder="公开频道链接 / @频道名 / 私有频道数字 ID" /></label>
        <small className="settings-field-help">公开频道示例：https://t.me/channel_name；私有频道填写 -100… 并将 Bot 加入频道。</small>
        <label>显示名称（可选）<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="影视发布频道" /></label>
        <div className="channel-rule-toggles">
          <SettingsToggle label="启用频道来源" help="停用后保留历史索引，但不再接收或按需更新该频道。" value={channelEnabled} onChange={setChannelEnabled} trueLabel="已启用" falseLabel="已停用" />
          <SettingsToggle label="愿望单唯一命中后自动建任务" help="只创建可追溯的统一转存任务，不会绕过验真、命名和转存规则。" value={autoTransfer} onChange={setAutoTransfer} trueLabel="自动" falseLabel="仅候选" />
          <SettingsToggle label="同时要求豆瓣白名单" help="开启后，只有下方白名单中的标题才允许进入自动转存判断。" value={requireDouban} onChange={setRequireDouban} trueLabel="要求" falseLabel="不要求" />
        </div>
        <label className="channel-whitelist-field">豆瓣榜单标题（每行一个，可选）<textarea value={doubanTitles} onChange={(event) => setDoubanTitles(event.target.value)} placeholder="开启白名单过滤后，每行填写一个允许自动处理的标题" /></label>
        <button type="button" className="primary" disabled={busy || !channelId.trim()} onClick={() => void save()}><PaperPlaneTilt size={17} />保存并接入资源索引</button>
      </section>
      <section className="channel-status-card">
        <div className="library-card-title"><ListChecks size={21} weight="fill" /><strong>已追踪频道</strong></div>
        <ol>
          <li>公开频道在发现搜索、愿望单检查和追更补集时按需更新，保存频道时也立即拉取。</li>
          <li>私有频道通过 Bot 实时接收 channel_post。</li>
          <li>夸克与 115 链接都会进入全局候选索引。</li>
          <li>自动转存仍需唯一命中愿望单，可叠加豆瓣白名单。</li>
        </ol>
        <div className="channel-subscription-list">
          {subscriptions.length ? subscriptions.map((item) => <button type="button" key={item.id} onClick={() => edit(item)}>
            <CheckCircle size={17} weight="fill" />
            <span>
              <strong>{item.display_name || item.channel_id}</strong>
              <small>{item.enabled ? (item.channel_id.startsWith("@") ? "搜索时更新" : "Bot 接收") : "已停用"} · {item.auto_transfer ? "愿望单命中后自动" : "进入候选索引"}{item.last_error ? ` · ${item.last_error}` : item.last_checked_at ? ` · 最近拉取 ${new Date(item.last_checked_at).toLocaleString()}` : ""}</small>
            </span>
          </button>) : <p className="transfer-placeholder">尚未订阅频道。</p>}
        </div>
      </section>
    </div>
    <section className="library-assets">
      <div className="transfer-queue-head"><div><strong>频道消息与候选入库</strong><small>不回显分享链接中的凭据；候选会自动参与发现详情、愿望单与追更补集检索。</small></div></div>
      {messages.length ? <div className="library-asset-list">{messages.map((item) => <article key={item.id} className="channel-message">
        <span className={`transfer-state state-${item.state}`}>{item.state}</span>
        <div><strong>{item.display_name || item.channel_id} · 消息 {item.message_id}</strong><small>已索引 {item.indexed_resource_count || 0} 个候选 · {item.message_safe}{item.transfer_job_id ? ` · 任务 #${item.transfer_job_id}` : ""}</small><p>{item.text_preview}</p></div>
      </article>)}</div> : <p className="transfer-placeholder">等待公开频道拉取或 Bot 接收新消息。</p>}
    </section>
  </div>;
}
