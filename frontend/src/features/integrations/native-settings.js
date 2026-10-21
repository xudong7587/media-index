import { escapeHtml as esc, fieldsView, readFields, bindFields, runAction } from "../../components/native-ui.js";

// The same command names as notification_channels and the existing interaction UI.
export const commandReference = [
  ["资源名 / 分享链接 / 磁力链接", "搜索影视或下载链接，按提示选择网盘与云下载子目录"],
  ["/review", "待确认任务"], ["/status", "服务器状态"], ["/tracking", "智能追更"],
  ["/wishlist", "愿望单"], ["/notifications", "最近通知"], ["/emby", "Emby 状态"],
  ["/strm_full", "全量扫描"], ["/strm_incremental", "增量扫描"],
  ["/strm_directory", "选择指定目录扫描"], ["/download", "下载帮助"],
  ["/cancel", "取消当前选择"], ["/help", "内置帮助"],
];
export const callbackFields = [
  ["wecom_origin", "企业微信 API 地址"],
  ["wecom_app_to_party", "接收部门 ID（用 | 分隔）"],
  ["wecom_app_to_tag", "接收标签 ID（用 | 分隔）"],
  ["wecom_callback_enabled", "启用企业微信回调交互", "boolean"],
  ["wecom_callback_url", "公开回调地址"],
  ["wecom_callback_token", "回调 Token", "secret"],
  ["wecom_callback_aes_key", "EncodingAESKey", "secret"],
  ["wecom_callback_allowed_users", "允许交互的成员 UserID"],
];
const shortcuts = [["strm_full", "全量扫描"], ["strm_incremental", "增量扫描"], ["strm_directory", "目录扫描"], ["tracking", "追更"], ["wishlist", "愿望单"], ["status", "状态"], ["review", "待确认"], ["download", "下载"]];

export function wecomCallbackView(config) {
  return `<div class="panel-head"><div><h3>接收范围与回调交互</h3><small>与上方企业微信应用一起保存</small></div></div>${fieldsView(callbackFields, config)}<p class="muted-note">服务回调入口：${esc((config.public_base_url || location.origin).replace(/\/$/, ""))}/api/notifications/wecom/callback</p>`;
}

export function integrationSettingsView(config) {
  return `
  <section class="panel panel-pad" data-interaction-settings>
    <div class="panel-head"><div><h2>交互指令</h2><small>企业微信与 Telegram 共用参与网盘、资源选择和快捷菜单</small></div></div>
    <div class="field"><label>参与交互的网盘</label><div class="chip-row">${[["quark", "夸克"], ["p115", "115"]].map(([v, text]) => `<label class="check"><input type="checkbox" data-interaction-provider="${v}" ${(config.interaction_providers || []).includes(v) ? "checked" : ""}>${text}</label>`).join("")}</div></div>
    <div class="field"><label>快捷菜单</label><div class="chip-row">${shortcuts.map(([v, text]) => `<label class="check"><input type="checkbox" data-interaction-shortcut="${v}" ${(config.interaction_shortcuts || []).includes(v) ? "checked" : ""}>${text}</label>`).join("")}</div></div>
    <div class="row-actions"><button class="mini-btn primary" data-interaction-save>保存设置</button><button class="mini-btn" data-interaction-sync>保存并同步到企微 / Telegram</button></div><p class="inline-result" role="status"></p>
    <div class="list">${commandReference.map(([command, description]) => `<div class="list-row"><div class="grow"><b>${esc(command)}</b><small>${esc(description)}</small></div></div>`).join("")}</div>
  </section>`;
}

export function bindIntegrationSettings(api, onSaved) {
  const interaction = document.querySelector("[data-interaction-settings]");
  if (!interaction) return;
  const save = async (sync) => {
    await api("/api/config", { method: "PUT", body: JSON.stringify({
      interaction_providers: [...interaction.querySelectorAll("[data-interaction-provider]:checked")].map((e) => e.dataset.interactionProvider),
      interaction_shortcuts: [...interaction.querySelectorAll("[data-interaction-shortcut]:checked")].map((e) => e.dataset.interactionShortcut),
    }) });
    const result = sync ? await api("/api/notifications/interaction-shortcuts/sync", { method: "POST" }) : { ok: true, message: "交互设置已保存" };
    await onSaved();
    return result;
  };
  for (const [selector, sync] of [["[data-interaction-save]", false], ["[data-interaction-sync]", true]]) {
    interaction.querySelector(selector).onclick = (event) => void runAction(event.currentTarget, interaction.querySelector('[role="status"]'), () => save(sync));
  }
}
