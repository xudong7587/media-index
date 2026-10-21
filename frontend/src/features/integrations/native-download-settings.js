import { escapeHtml as esc, listen } from "../../components/native-ui.js";

export function downloadSettingsView(config) {
  return `<section class="panel panel-pad">
    <div class="panel-head"><div><h2>云下载路由</h2><small>交互渠道和发现页的链接下载共用规则，链接类型自动决定网盘</small></div></div>
    <div class="switch-row"><div><b>允许直接下载</b><small>处理交互渠道与发现页提交的链接</small></div><button class="switch" id="setDirectEnabled" aria-checked="${Boolean(config.direct_download_enabled)}" aria-label="允许直接下载"></button></div>
    <div class="download-route-grid">${[["默认下载网盘", "115", "磁力、电驴、普通 HTTP 与无法识别网盘的链接"], ["夸克分享链接", "自动转存到夸克", "进入所选的夸克云下载子目录"], ["115 分享链接", "自动转存到 115", "进入所选的 115 云下载子目录"]].map(([name, target, help]) => `<div class="route-option"><small>${name}</small><b>${target}</b><span>${help}</span></div>`).join("")}</div>
    <div class="download-directory-guide">${[["p115", "115"], ["quark", "夸克"]].map(([key,label]) => `<div class="list-row"><div class="grow"><b>${label} 云下载目录</b><small>${esc(config[key + "_cloud_download_path"] || "尚未设置")}</small></div><button class="mini-btn" data-route="workspace" data-ws-section="cloud-download">配置目录</button></div>`).join("")}</div>
    <p class="muted-note">提交链接后选择允许的云下载直属子目录；先保留原始命名，核验与整理完成后再进入正式媒体库。</p>
    <div class="field"><label for="setDirectPath">默认保存目录（可选）</label><input class="input" id="setDirectPath" value="${esc(config.direct_download_save_path || "")}" placeholder="留空使用云下载目录选择"></div>
    <div class="row-actions"><span class="inline-result" data-download-result role="status"></span><button class="mini-btn primary" data-settings-save="direct">保存云下载设置</button></div>
  </section>
  <section class="panel panel-pad" data-interaction-records><div class="panel-head"><div><h2>交互转存记录</h2><small>企业微信与 Telegram 发起的最近任务</small></div><button class="mini-btn" data-records-refresh>刷新</button></div><div data-records-list>正在读取…</div></section>`;
}

export function bindDownloadRecords(api, openTask) {
  const panel = document.querySelector("[data-interaction-records]");
  if (!panel) return;
  const list = panel.querySelector("[data-records-list]");
  async function refresh() {
    try {
      const rows = await api("/api/transfers/wecom-records?limit=20");
      if (!panel.isConnected) return;
      list.innerHTML = `<div class="list">${rows.map(job => `<button class="list-row native-record-row" data-record-job="${job.id}"><div class="grow"><b>${esc(job.display_title || `任务 #${job.id}`)}</b><small>${esc(job.message || job.stage || "")}</small></div><span>${esc(job.status)}</span></button>`).join("") || '<p class="muted-note">暂无交互转存记录</p>'}</div>`;
      list.querySelectorAll("[data-record-job]").forEach(button => { button.onclick = () => openTask(button.dataset.recordJob); });
    } catch (error) { if (panel.isConnected) list.textContent = error.message; }
  }
  listen(panel.querySelector("[data-records-refresh]"), "click", refresh);
  void refresh();
}
