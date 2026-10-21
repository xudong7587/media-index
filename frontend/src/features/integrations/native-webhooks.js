import { escapeHtml as esc, modal, runAction } from "../../components/native-ui.js";

const base = "/api/webhooks/connections";
export async function renderWebhookManager(api, panel, publicBaseUrl) {
  if (!panel) return;
  try {
    const [data, deliveryData] = await Promise.all([api(base), api(`${base}/deliveries/recent`)]);
    if (!panel.isConnected) return;
    const reload = () => renderWebhookManager(api, panel, publicBaseUrl);
    panel.innerHTML = `<div class="panel-head"><div><h2>Webhook 连接</h2><small>独立管理入站、出站、签名和投递记录</small></div><button class="mini-btn primary" data-webhook-new>新建连接</button></div>
      <div class="list">${data.items.map((item, index) => `<div class="list-row"><div class="grow"><b>${esc(item.name)}</b><small>${item.direction === "inbound" ? "入站" : "出站"} · ${esc(item.verification_state)}${item.last_error ? ` · ${esc(item.last_error)}` : ""}</small></div><span class="pill ${item.enabled ? "ok" : "muted"}">${item.enabled ? "启用" : "停用"}</span>${item.kind === "built_in" ? '<span class="muted-note">由上方 MDC 设置管理</span>' : `<button class="mini-btn" data-webhook-edit="${index}">管理</button>`}</div>`).join("")}</div>
      <div class="panel-head"><div><h3>最近投递</h3><small>失败记录保留服务端错误，可重新投递</small></div><button class="mini-btn" data-webhook-refresh>刷新</button></div>
      <div class="list">${(deliveryData.items || []).map((d) => `<div class="list-row"><div class="grow"><b>${esc(d.event_type)}</b><small>${esc(d.error_safe || d.message || d.created_at || "")}</small></div><span class="pill ${d.status === "delivered" ? "ok" : "warn"}">${esc(d.status)}</span>${d.status === "failed" ? `<button class="mini-btn" data-delivery-retry="${d.id}">重投</button>` : ""}</div>`).join("") || '<p class="muted-note">暂无投递记录</p>'}</div><p class="inline-result" role="status"></p>`;
    panel.querySelector("[data-webhook-new]").onclick = () => editConnection(api, null, data, publicBaseUrl, reload);
    panel.querySelector("[data-webhook-refresh]").onclick = reload;
    panel.querySelectorAll("[data-webhook-edit]").forEach((button) => { button.onclick = () => editConnection(api, data.items[Number(button.dataset.webhookEdit)], data, publicBaseUrl, reload); });
    panel.querySelectorAll("[data-delivery-retry]").forEach((button) => { button.onclick = () => void runAction(button, panel.querySelector('[role="status"]'), async () => {
      const result = await api(`${base}/deliveries/${button.dataset.deliveryRetry}/retry`, { method: "POST" });
      await reload();
      return result;
    }); });
  } catch (error) {
    if (panel.isConnected) {
      panel.innerHTML = `<p class="inline-result error">${esc(error.message)}</p><button class="mini-btn" data-webhook-retry>重试</button>`;
      panel.querySelector("[data-webhook-retry]").onclick = () => void renderWebhookManager(api, panel, publicBaseUrl);
    }
  }
}

function editConnection(api, original, data, publicBaseUrl, reload) {
  const dialog = modal(original ? "管理 Webhook" : "新建 Webhook", "出站测试将向目标地址发送测试事件");
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  let connection = original;
  const action = original?.action || {};
  const providers = (data.inbound_actions?.providers || []).filter((p) => p.source_root && p.directories.length);
  body.innerHTML = `<div class="form-grid native-form">
    <div class="field"><label>名称</label><input class="input" data-name value="${esc(original?.name || "")}" maxlength="80"></div>
    <div class="field"><label>方向</label><select class="input" data-direction ${original ? "disabled" : ""}><option value="inbound" ${original?.direction !== "outbound" ? "selected" : ""}>入站</option><option value="outbound" ${original?.direction === "outbound" ? "selected" : ""}>出站</option></select></div>
    <div class="field" data-outbound><label>目标 URL</label><input class="input" data-target value="${esc(original?.target_url || "")}" placeholder="https://..."></div>
    <div class="field"><label class="check"><input type="checkbox" data-enabled ${original?.enabled !== false ? "checked" : ""}>启用连接</label></div>
  </div>
  <div class="field"><label>事件类型</label><div class="chip-row">${["*", ...data.event_types].map((e) => `<label class="check"><input type="checkbox" data-event-name="${esc(e)}" ${(original?.event_types || ["*"]).includes(e) ? "checked" : ""}>${esc(e)}</label>`).join("")}</div></div>
  <div data-inbound><div class="form-grid native-form">
    <div class="field"><label>入站动作</label><select class="input" data-action><option value="none">仅记录消息</option><option value="strm_scan" ${action.type === "strm_scan" ? "selected" : ""} ${!providers.length || !data.inbound_actions?.strm_output_configured ? "disabled" : ""}>扫描已授权 STRM 目录</option></select></div>
    <div class="field"><label>网盘</label><select class="input" data-action-provider>${providers.map((p) => `<option value="${p.provider}" ${p.provider === action.provider ? "selected" : ""}>${p.provider === "p115" ? "115" : "夸克"}</option>`).join("")}</select></div>
    <div class="field"><label>已保存的扫描范围</label><select class="input" data-action-directory></select></div>
    <div class="field"><label>扫描方式</label><select class="input" data-action-mode><option value="incremental">增量</option><option value="full" ${action.mode === "full" ? "selected" : ""}>全量</option></select></div>
    <div class="field"><label>等待秒数（0–600）</label><input class="input" type="number" min="0" max="600" data-action-delay value="${action.delay_seconds ?? 300}"></div>
  </div><p class="muted-note" data-endpoint></p></div><div data-secret-output></div>`;
  const direction = body.querySelector("[data-direction]");
  const provider = body.querySelector("[data-action-provider]");
  const paintDirectories = () => {
    const current = providers.find((p) => p.provider === provider.value);
    body.querySelector("[data-action-directory]").innerHTML = (current?.directories || []).map((d) => `<option value="${esc(d)}" ${d === action.directory ? "selected" : ""}>${esc(d)}</option>`).join("");
  };
  const paintDirection = () => {
    body.querySelector("[data-inbound]").hidden = direction.value !== "inbound";
    body.querySelector("[data-outbound]").hidden = direction.value !== "outbound";
    body.querySelector("[data-endpoint]").textContent = connection ? `${(publicBaseUrl || location.origin).replace(/\/$/, "")}/api/webhooks/in/${connection.endpoint_key}` : "保存后生成专属入站地址";
  };
  provider.onchange = paintDirectories;
  direction.onchange = paintDirection;
  paintDirectories();
  paintDirection();
  function buttons() {
    dialog.querySelector(".picker-foot").innerHTML = `<button class="mini-btn primary" data-connection-save>保存连接</button>${connection ? `<button class="mini-btn" data-connection-secret>复制签名密钥</button><button class="mini-btn" data-connection-rotate>轮换密钥</button>${connection.direction === "outbound" ? '<button class="mini-btn" data-connection-test>发送测试事件</button>' : ""}<button class="mini-btn danger" data-connection-delete>删除连接</button>` : ""}`;
    const bind = (selector, work) => {
      const button = dialog.querySelector(selector);
      if (button) button.onclick = () => void runAction(button, output, work);
    };
    bind("[data-connection-save]", async () => {
      const payload = {
        name: body.querySelector("[data-name]").value.trim(),
        target_url: direction.value === "outbound" ? body.querySelector("[data-target]").value.trim() : "",
        event_types: [...body.querySelectorAll("[data-event-name]:checked")].map((e) => e.dataset.eventName),
        action: {},
      };
      if (direction.value === "inbound" && body.querySelector("[data-action]").value === "strm_scan") payload.action = {
        type: "strm_scan", provider: provider.value, directory: body.querySelector("[data-action-directory]").value,
        mode: body.querySelector("[data-action-mode]").value, delay_seconds: Number(body.querySelector("[data-action-delay]").value),
      };
      if (!payload.name || !payload.event_types.length) throw new Error("请填写名称并选择事件");
      if (connection) payload.enabled = body.querySelector("[data-enabled]").checked;
      else payload.direction = direction.value;
      connection = await api(connection ? `${base}/${connection.id}` : base, { method: connection ? "PATCH" : "POST", body: JSON.stringify(payload) });
      if (connection.enabled !== body.querySelector("[data-enabled]").checked) connection = await api(`${base}/${connection.id}`, { method: "PATCH", body: JSON.stringify({ enabled: body.querySelector("[data-enabled]").checked }) });
      direction.disabled = true;
      buttons(); paintDirection();
      await reload();
      return { message: "连接已保存。需要时可复制签名密钥供发送端配置。" };
    });
    bind("[data-connection-secret]", async () => {
      const response = await api(`${base}/${connection.id}/secret`);
      await navigator.clipboard.writeText(response.signing_secret);
      return { message: "签名密钥已复制" };
    });
    bind("[data-connection-rotate]", async () => {
      if (!confirm("轮换后旧签名密钥立即失效，继续？")) return { message: "已取消" };
      await api(`${base}/${connection.id}/rotate-secret`, { method: "POST" });
      await reload();
      return { message: "密钥已轮换，请复制新密钥并更新发送端" };
    });
    bind("[data-connection-test]", () => api(`${base}/${connection.id}/test`, { method: "POST" }));
    bind("[data-connection-delete]", async () => {
      if (!confirm("删除这个 Webhook 连接？")) return { message: "已取消" };
      await api(`${base}/${connection.id}`, { method: "DELETE" });
      dialog.close();
      await reload();
    });
  }
  buttons();
}
