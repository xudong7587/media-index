import { escapeHtml as esc, modal, runAction } from "../../components/native-ui.js";

export function openNativeSessions(api, initial = []) {
  const dialog = modal("播放会话", "Emby 当前在线设备与播放状态", "media-sessions-dialog");
  const body = dialog.querySelector(".native-dialog-body"), output = dialog.querySelector('[role="status"]');
  function paint(sessions) {
    body.innerHTML = sessions.length ? `<div class="list">${sessions.map((session) => `<article class="list-row"><div class="grow"><b>${esc(session.item_name || "未播放内容")}</b><small>${esc(session.user_name || "访客")} · ${esc(session.device_name || "未知设备")}${session.client ? ` · ${esc(session.client)}` : ""}</small></div><span class="pill ${session.is_playing ? "ok" : "muted"}"><i></i>${session.is_playing ? "播放中" : "空闲"}</span></article>`).join("")}</div>` : '<div class="empty-state"><b>当前没有播放会话</b><span>有设备在线或播放时会显示在这里。</span></div>';
  }
  dialog.querySelector(".picker-foot").innerHTML = '<button class="mini-btn" data-sessions-refresh>刷新会话</button><button class="mini-btn primary" data-sessions-close>关闭</button>';
  dialog.querySelector("[data-sessions-close]").onclick = () => dialog.close();
  dialog.querySelector("[data-sessions-refresh]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
    const dashboard = await api("/api/integrations/emby/dashboard");
    if (dialog.isConnected) paint(dashboard.sessions || []);
    return { message: "会话已刷新" };
  });
  paint(initial);
  return dialog;
}
