import {
  ArrowDownLeft,
  ArrowUpRight,
  ArrowsClockwise,
  CheckCircle,
  ClockCounterClockwise,
  Copy,
  Key,
  PencilSimple,
  Plus,
  PlugsConnected,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, ApiError, type WebhookConnection, type WebhookDelivery } from "../../lib/api";
import "./webhook-connections.css";


const EVENT_LABELS: Record<string, string> = {
  "*": "全部消息",
  transfer_success: "转存成功",
  failure: "处理失败",
  review: "需要确认",
  library: "媒体入库",
  no_resource: "暂无资源",
  playback: "播放事件",
};

type Direction = "inbound" | "outbound";

function connectionState(connection: WebhookConnection) {
  if (!connection.enabled || connection.verification_state === "disabled") return { label: "已停用", tone: "muted" };
  if (connection.verification_state === "verified") return { label: "已连通", tone: "success" };
  if (connection.verification_state === "failing") return { label: "投递异常", tone: "danger" };
  if (connection.verification_state === "configured") return { label: "已配置", tone: "ready" };
  return { label: "待验证", tone: "ready" };
}

function localTime(value?: string | null) {
  if (!value) return "尚无事件";
  const parsed = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN", { hour12: false });
}

export function WebhookConnectionManager({ publicBaseUrl, onOpenMdc }: { publicBaseUrl: string; onOpenMdc: () => void }) {
  const [connections, setConnections] = useState<WebhookConnection[]>([]);
  const [eventTypes, setEventTypes] = useState<string[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([]);
  const [filter, setFilter] = useState<"all" | Direction>("all");
  const [selectedId, setSelectedId] = useState<WebhookConnection["id"] | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<WebhookConnection | null>(null);
  const [editing, setEditing] = useState<WebhookConnection | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    const [connectionResult, deliveryResult] = await Promise.all([
      api.webhookConnections(),
      api.webhookDeliveries(),
    ]);
    setConnections(connectionResult.items);
    setEventTypes(connectionResult.event_types);
    setDeliveries(deliveryResult.items);
  }, []);

  useEffect(() => { void refresh().catch((error: Error) => setMessage(error.message)); }, [refresh]);

  const visible = useMemo(
    () => connections.filter((connection) => filter === "all" || connection.direction === filter),
    [connections, filter],
  );
  const selected = connections.find((connection) => connection.id === selectedId) || null;

  async function run(label: string, action: () => Promise<unknown>, success: string) {
    setBusy(label);
    setMessage("");
    try {
      await action();
      await refresh();
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Webhook 操作失败");
    } finally {
      setBusy("");
    }
  }

  async function reveal(connection: WebhookConnection) {
    if (typeof connection.id !== "number") return;
    setBusy(`secret-${connection.id}`);
    try {
      const result = await api.revealWebhookSecret(connection.id);
      setConnections((items) => items.map((item) => item.id === connection.id ? { ...item, signing_secret: result.signing_secret } : item));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "密钥读取失败");
    } finally {
      setBusy("");
    }
  }

  async function copy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      setMessage(`${label}已复制`);
    } catch {
      window.prompt(`复制${label}`, value);
    }
  }

  return <div className="webhook-hub">
    <div className="webhook-hub-toolbar">
      <div className="webhook-direction-tabs" role="tablist" aria-label="Webhook 方向筛选">
        {(["all", "inbound", "outbound"] as const).map((item) => <button key={item} type="button" className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item === "all" ? "全部连接" : item === "inbound" ? "接收消息" : "发送消息"}</button>)}
      </div>
      <button type="button" className="primary compact-action" onClick={() => { setCreated(null); setCreateOpen(true); }}><Plus size={16} />新建 Webhook</button>
    </div>

    <div className="webhook-summary-strip">
      <span><strong>{connections.length}</strong> 个连接</span>
      <span><strong>{connections.filter((item) => item.verification_state === "verified").length}</strong> 个已连通</span>
      <span><strong>{deliveries.filter((item) => item.status === "retry_wait" || item.status === "failed").length}</strong> 个待处理投递</span>
      <small>连接成功以真实接收或目标端返回 2xx 为准</small>
    </div>

    {message && <div className="notice webhook-hub-notice">{message}</div>}
    <div className="webhook-connection-grid">
      {visible.map((connection) => {
        const state = connectionState(connection);
        const expanded = selectedId === connection.id;
        const endpoint = connection.direction === "inbound" ? `${publicBaseUrl}/api/webhooks/in/${connection.endpoint_key}` : connection.target_url;
        return <article className={`webhook-connection-card ${expanded ? "expanded" : ""}`} key={String(connection.id)}>
          <button type="button" className="webhook-card-main" onClick={() => setSelectedId(expanded ? null : connection.id)}>
            <span className={`webhook-direction-icon ${connection.direction}`} aria-hidden="true">{connection.direction === "inbound" ? <ArrowDownLeft /> : <ArrowUpRight />}</span>
            <span className="webhook-card-copy"><span className="webhook-card-title"><strong>{connection.name}</strong>{connection.kind === "built_in" && <em>内置适配器</em>}</span><small>{connection.direction === "inbound" ? "接收消息" : "发送消息"} · {connection.event_types.map((item) => EVENT_LABELS[item] || item).join("、")}</small></span>
            <span className={`webhook-state ${state.tone}`}>{state.tone === "success" ? <CheckCircle weight="fill" /> : state.tone === "danger" ? <WarningCircle weight="fill" /> : <PlugsConnected />}{state.label}</span>
          </button>
          {expanded && <div className="webhook-card-detail">
            <div className="webhook-endpoint-line"><div><small>{connection.direction === "inbound" ? "接收 URL" : "目标 URL"}</small><code>{endpoint}</code></div><button type="button" className="icon" aria-label="复制 URL" onClick={() => void copy(endpoint, "URL")}><Copy /></button></div>
            <div className="webhook-detail-meta"><span>最近事件：{localTime(connection.last_event_at)}</span><span>验证状态：{state.label}</span></div>
            {connection.last_error && <div className="webhook-error"><WarningCircle />{connection.last_error}</div>}
            {connection.kind === "built_in" ? <div className="webhook-card-actions"><button type="button" className="primary compact-action" onClick={onOpenMdc}>查看 MDC-NG 设置</button><span>继续使用原有专用端点、鉴权和增量 STRM 流程。</span></div> : <GenericConnectionActions connection={connection} endpoint={endpoint} deliveries={deliveries.filter((item) => item.connection_id === connection.id).slice(0, 5)} busy={busy} onReveal={() => void reveal(connection)} onCopy={copy} onRun={run} onRefresh={refresh} onEdit={() => setEditing(connection)} onDeleted={() => setSelectedId(null)} />}
          </div>}
        </article>;
      })}
    </div>

    <DeliveryTimeline deliveries={deliveries.slice(0, 12)} busy={busy} onRun={run} />
    {createOpen && <CreateWebhookDialog publicBaseUrl={publicBaseUrl} eventTypes={eventTypes} created={created} onCreated={async (connection) => { setCreated(connection); await refresh(); }} onClose={() => { setCreateOpen(false); setCreated(null); }} onCopy={copy} />}
    {editing && typeof editing.id === "number" && <EditWebhookDialog connection={editing} eventTypes={eventTypes} onSaved={async () => { setEditing(null); await refresh(); setMessage("Webhook 连接设置已保存"); }} onClose={() => setEditing(null)} />}
  </div>;
}

function GenericConnectionActions({ connection, endpoint, deliveries, busy, onReveal, onCopy, onRun, onRefresh, onEdit, onDeleted }: {
  connection: WebhookConnection;
  endpoint: string;
  deliveries: WebhookDelivery[];
  busy: string;
  onReveal: () => void;
  onCopy: (value: string, label: string) => Promise<void>;
  onRun: (label: string, action: () => Promise<unknown>, success: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  onEdit: () => void;
  onDeleted: () => void;
}) {
  if (typeof connection.id !== "number") return null;
  const secret = connection.signing_secret || "";
  const curl = secret ? inboundCurl(endpoint, secret) : "";
  return <>
    <div className="webhook-secret-row"><Key /><div><small>签名密钥</small><code>{secret || "whsec_••••••••••••••••••••"}</code></div><button type="button" className="ghost compact-action" onClick={onReveal} disabled={busy === `secret-${connection.id}`}>{secret ? "收起后刷新页面" : "显示"}</button>{secret && <button type="button" className="icon" aria-label="复制密钥" onClick={() => void onCopy(secret, "签名密钥")}><Copy /></button>}</div>
    {connection.direction === "inbound" && secret && <div className="webhook-command"><div><small>快速测试命令（Bearer 兼容模式）</small><button type="button" onClick={() => void onCopy(curl, "curl 命令")}><Copy />复制</button></div><pre>{curl}</pre><p>生产集成建议使用 Standard Webhooks HMAC 签名；接收体支持 CloudEvents 1.0。</p></div>}
    {deliveries.length > 0 && <div className="webhook-mini-history">{deliveries.map((item) => <span key={item.id}><i className={item.status} />{EVENT_LABELS[item.event_type] || item.event_type}<small>{item.status} · {localTime(item.updated_at)}</small></span>)}</div>}
    <div className="webhook-card-actions">
      {connection.direction === "outbound" && <button type="button" className="primary compact-action" disabled={!!busy} onClick={() => void onRun(`test-${connection.id}`, () => api.testWebhookConnection(connection.id as number), "目标端已确认测试消息")}>验证连接</button>}
      <button type="button" className="ghost compact-action" disabled={!!busy} onClick={onEdit}><PencilSimple />编辑设置</button>
      <button type="button" className="ghost compact-action" disabled={!!busy} onClick={() => void onRun(`toggle-${connection.id}`, () => api.updateWebhookConnection(connection.id as number, { enabled: !connection.enabled }), connection.enabled ? "连接已停用" : "连接已启用")}>{connection.enabled ? "停用" : "启用"}</button>
      <button type="button" className="ghost compact-action" disabled={!!busy} onClick={() => void onRun(`rotate-${connection.id}`, async () => { const result = await api.rotateWebhookSecret(connection.id as number); await onRefresh(); if (result.signing_secret) await onCopy(result.signing_secret, "新签名密钥"); }, "密钥已轮换；旧密钥立即失效")}>轮换密钥</button>
      <button type="button" className="danger compact-action" disabled={!!busy} onClick={() => { if (window.confirm(`删除“${connection.name}”及其投递记录？此操作不可恢复。`)) void onRun(`delete-${connection.id}`, async () => { await api.deleteWebhookConnection(connection.id as number); onDeleted(); }, "Webhook 连接已删除"); }}><Trash />删除</button>
    </div>
  </>;
}

function EditWebhookDialog({ connection, eventTypes, onSaved, onClose }: {
  connection: WebhookConnection;
  eventTypes: string[];
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const [name, setName] = useState(connection.name);
  const [targetUrl, setTargetUrl] = useState(connection.target_url);
  const [selected, setSelected] = useState(connection.event_types);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  if (typeof connection.id !== "number") return null;

  async function save() {
    setSaving(true);
    setError("");
    try {
      await api.updateWebhookConnection(connection.id as number, {
        name,
        ...(connection.direction === "outbound" ? { target_url: targetUrl, event_types: selected } : {}),
      });
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Webhook 设置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return <div className="webhook-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><section className="webhook-dialog" role="dialog" aria-modal="true" aria-labelledby="webhook-edit-title"><header><div><small>CONNECTION SETTINGS</small><h2 id="webhook-edit-title">编辑 Webhook</h2></div><button type="button" className="icon" aria-label="关闭" onClick={onClose}><X /></button></header><div className="webhook-create-form"><label>连接名称<input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} /></label>{connection.direction === "outbound" && <><label>目标 URL<input value={targetUrl} onChange={(event) => setTargetUrl(event.target.value)} /><small>修改目标后连接会回到“待验证”，请重新发送测试消息。</small></label><fieldset><legend>订阅消息</legend><div className="webhook-event-options">{eventTypes.map((item) => <label key={item}><input type="checkbox" checked={selected.includes(item)} onChange={(event) => { if (item === "*") setSelected(event.target.checked ? ["*"] : []); else setSelected((current) => event.target.checked ? [...current.filter((value) => value !== "*"), item] : current.filter((value) => value !== item)); }} />{EVENT_LABELS[item] || item}</label>)}</div></fieldset></>}{error && <div className="webhook-error"><WarningCircle />{error}</div>}<footer><button type="button" className="ghost" onClick={onClose}>取消</button><button type="button" className="primary" disabled={saving || !name.trim() || (connection.direction === "outbound" && (!targetUrl.trim() || !selected.length))} onClick={() => void save()}>{saving ? "正在保存" : "保存设置"}</button></footer></div></section></div>;
}

function DeliveryTimeline({ deliveries, busy, onRun }: { deliveries: WebhookDelivery[]; busy: string; onRun: (label: string, action: () => Promise<unknown>, success: string) => Promise<void> }) {
  return <section className="webhook-delivery-panel"><header><div><small>DELIVERY ACTIVITY</small><h3>最近消息</h3></div><span>接收与发送共用一份可追踪记录</span></header>{deliveries.length ? <div className="webhook-delivery-list">{deliveries.map((item) => <div key={item.id}><i className={item.status}>{item.direction === "inbound" ? <ArrowDownLeft /> : <ArrowUpRight />}</i><span><strong>{item.name}</strong><small>{EVENT_LABELS[item.event_type] || item.event_type} · {localTime(item.created_at)}</small></span><em className={item.status}>{item.status === "delivered" || item.status === "received" ? "成功" : item.status === "retry_wait" ? "等待重试" : item.status === "failed" ? "失败" : "处理中"}</em>{item.direction === "outbound" && ["failed", "retry_wait"].includes(item.status) && <button type="button" className="ghost compact-action" disabled={!!busy} onClick={() => void onRun(`retry-${item.id}`, () => api.retryWebhookDelivery(item.id), "已加入重投队列")}><ArrowsClockwise />重投</button>}</div>)}</div> : <div className="webhook-empty"><ClockCounterClockwise /><span>还没有消息记录<small>接收到事件或完成第一次投递后会显示在这里。</small></span></div>}</section>;
}

function CreateWebhookDialog({ publicBaseUrl, eventTypes, created, onCreated, onClose, onCopy }: {
  publicBaseUrl: string;
  eventTypes: string[];
  created: WebhookConnection | null;
  onCreated: (connection: WebhookConnection) => Promise<void>;
  onClose: () => void;
  onCopy: (value: string, label: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [direction, setDirection] = useState<Direction>("inbound");
  const [targetUrl, setTargetUrl] = useState("");
  const [selected, setSelected] = useState<string[]>(["*"]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setSaving(true);
    setError("");
    try {
      const result = await api.createWebhookConnection({ name, direction, target_url: targetUrl, event_types: direction === "outbound" ? selected : ["*"] });
      await onCreated(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Webhook 创建失败");
    } finally {
      setSaving(false);
    }
  }

  const endpoint = created ? `${publicBaseUrl}/api/webhooks/in/${created.endpoint_key}` : "";
  return <div className="webhook-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><section className="webhook-dialog" role="dialog" aria-modal="true" aria-labelledby="webhook-dialog-title"><header><div><small>NEW CONNECTION</small><h2 id="webhook-dialog-title">{created ? "连接已经创建" : "新建 Webhook"}</h2></div><button type="button" className="icon" aria-label="关闭" onClick={onClose}><X /></button></header>{created ? <div className="webhook-created"><CheckCircle weight="fill" /><h3>{created.name}</h3><p>请立即保存下面的接入信息。密钥之后仍可由已登录管理员查看或轮换。</p>{created.direction === "inbound" ? <><label>接收 URL<code>{endpoint}</code><button type="button" onClick={() => void onCopy(endpoint, "接收 URL")}><Copy />复制</button></label><label>签名密钥<code>{created.signing_secret}</code><button type="button" onClick={() => void onCopy(created.signing_secret || "", "签名密钥")}><Copy />复制</button></label><div className="webhook-command"><div><small>快速测试命令</small><button type="button" onClick={() => void onCopy(inboundCurl(endpoint, created.signing_secret || ""), "curl 命令")}><Copy />复制</button></div><pre>{inboundCurl(endpoint, created.signing_secret || "")}</pre></div></> : <><label>目标 URL<code>{created.target_url}</code></label><label>签名密钥<code>{created.signing_secret}</code><button type="button" onClick={() => void onCopy(created.signing_secret || "", "签名密钥")}><Copy />复制</button></label><p>MediaIndex 会向目标发送 CloudEvents JSON，并附带 Standard Webhooks 三个签名头。返回任意 2xx 即视为成功。</p></>}<button type="button" className="primary" onClick={onClose}>完成</button></div> : <div className="webhook-create-form"><div className="webhook-direction-choice"><button type="button" className={direction === "inbound" ? "active" : ""} onClick={() => setDirection("inbound")}><ArrowDownLeft /><strong>接收消息</strong><small>为其他系统生成安全入口</small></button><button type="button" className={direction === "outbound" ? "active" : ""} onClick={() => setDirection("outbound")}><ArrowUpRight /><strong>发送消息</strong><small>把 MediaIndex 事件推送出去</small></button></div><label>连接名称<input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder={direction === "inbound" ? "例如：Home Assistant 接收" : "例如：家庭通知中心"} /></label>{direction === "outbound" && <label>目标 URL<input value={targetUrl} onChange={(event) => setTargetUrl(event.target.value)} placeholder="https://example.com/webhooks/mediaindex" /><small>公网地址必须使用 HTTPS；局域网与 Docker 服务名可使用 HTTP。</small></label>}{direction === "outbound" && <fieldset><legend>订阅消息</legend><div className="webhook-event-options">{eventTypes.map((item) => <label key={item}><input type="checkbox" checked={selected.includes(item)} onChange={(event) => { if (item === "*") setSelected(event.target.checked ? ["*"] : []); else setSelected((current) => event.target.checked ? [...current.filter((value) => value !== "*"), item] : current.filter((value) => value !== item)); }} />{EVENT_LABELS[item] || item}</label>)}</div></fieldset>}<div className="webhook-contract-note"><Key /><span><strong>安全合同</strong><small>密钥不会出现在连接列表；请求限制 256 KB；接收事件按 ID 去重；发送失败自动退避重试。</small></span></div>{error && <div className="webhook-error"><WarningCircle />{error}</div>}<footer><button type="button" className="ghost" onClick={onClose}>取消</button><button type="button" className="primary" disabled={saving || !name.trim() || (direction === "outbound" && (!targetUrl.trim() || !selected.length))} onClick={() => void submit()}>{saving ? "正在创建" : "创建连接"}</button></footer></div>}</section></div>;
}

function inboundCurl(endpoint: string, secret: string) {
  return [
    `curl -X POST '${endpoint}'`,
    "  -H 'Content-Type: application/cloudevents+json'",
    `  -H 'Authorization: Bearer ${secret}'`,
    "  -d '{\"specversion\":\"1.0\",\"id\":\"demo-001\",\"source\":\"/my-app\",\"type\":\"example.completed\",\"data\":{\"message\":\"hello\"}}'",
  ].join(" \\\n");
}
