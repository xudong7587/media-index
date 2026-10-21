import { escapeHtml as esc, modal, fieldsView, readFields, bindFields, runAction } from "../../components/native-ui.js";

export const scheduleDefinitions = [
  { name: "追更巡检", enabled: "tracking_scheduler_enabled", fields: [
    ["tracking_scheduler_enabled", "启用追更巡检", "boolean"], ["tracking_poll_minutes", "轮询周期（分钟）", "number"], ["tracking_check_time", "默认追更时间", "time"],
    ["tracking_retry_interval_minutes", "失败重试间隔（分钟）", "number"], ["tracking_max_retries", "最大重试次数", "number"],
  ], taskType: "tracking" },
  { name: "愿望单检查", enabled: "wishlist_scheduler_enabled", fields: [
    ["wishlist_scheduler_enabled", "启用愿望单检查", "boolean"], ["wishlist_poll_minutes", "轮询周期（分钟）", "number"], ["wishlist_default_check_hour", "默认检查小时（0–23）", "number"],
  ], taskType: "wishlist" },
  ...["p115", "quark"].map((provider) => ({ name: `${provider === "p115" ? "115" : "夸克"} STRM`, enabled: `${provider}_strm_enabled`, provider, fields: [
    [`${provider}_strm_enabled`, "启用 STRM", "boolean"], [`${provider}_strm_incremental_cron`, "增量计划（5 位 Cron）"],
  ] })),
  { name: "Emby 封面刷新", enabled: "emby_cover_refresh_enabled", fields: [
    ["emby_cover_refresh_enabled", "启用定时封面", "boolean"], ["emby_cover_refresh_cron", "封面计划（5 位 Cron）"], ["emby_cover_refresh_hours", "备用间隔（小时）", "number"],
  ], covers: true },
  { name: "云下载整理", enabled: "cloud_download_organizer_enabled", fields: [
    ["p115_cloud_download_organizer_enabled", "启用 115 整理", "boolean"], ["quark_cloud_download_organizer_enabled", "启用夸克整理", "boolean"],
    ["cloud_download_organizer_interval_minutes", "定时整理间隔（分钟）", "number"], ["cloud_download_organizer_stable_minutes", "稳定等待（分钟）", "number"],
  ], organizer: true },
];

export async function editSchedule(api, index, onSaved) {
  const definition = scheduleDefinitions[index];
  if (!definition) return;
  const dialog = modal(definition.name, "编辑调度参数；手动操作只执行明确选择的任务");
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  try {
    let config = await api("/api/config/status");
    if (!dialog.isConnected) return;
    body.innerHTML = fieldsView(definition.fields, config);
    if (definition.organizer) body.insertAdjacentHTML("beforeend", `<div class="field"><label>触发方式</label><div class="chip-row">${[["event", "事件"], ["scheduled", "定时"]].map(([key, text]) => `<label class="check"><input type="checkbox" data-schedule-trigger="${key}" ${(config.cloud_download_organizer_triggers || []).includes(key) ? "checked" : ""}>${text}</label>`).join("")}</div></div><p class="muted-note">手动整理请到工作台「云下载」选择具体媒体目录；这里不会发起全范围整理。</p>`);
    bindFields(body);
    dialog.querySelector(".picker-foot").innerHTML = '<button class="mini-btn primary" data-schedule-save>保存计划</button>';
    dialog.querySelector("[data-schedule-save]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
      const payload = readFields(body);
      if (definition.organizer) payload.cloud_download_organizer_triggers = [...body.querySelectorAll("[data-schedule-trigger]:checked")].map((node) => node.dataset.scheduleTrigger);
      const result = await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
      config = await api("/api/config/status");
      await onSaved();
      return { ...result, message: "计划已保存" };
    });
    if (definition.taskType) {
      const tasks = await api(`/api/${definition.taskType}`);
      if (!dialog.isConnected) return;
      body.insertAdjacentHTML("beforeend", `<div class="panel-head"><div><h3>手动执行单个任务</h3><small>沿用每个任务已保存的网盘和范围</small></div></div><div class="list">${tasks.filter((task) => task.status !== "archived").map((task) => `<div class="list-row"><div class="grow"><b>${esc(task.title)}</b><small>${esc(task.status || "")}</small></div><button class="mini-btn" data-schedule-run="${task.id}">立即检查</button></div>`).join("") || '<p class="muted-note">没有可执行任务</p>'}</div>`);
      body.querySelectorAll("[data-schedule-run]").forEach((button) => { button.onclick = () => void runAction(button, output, () => api(`/api/${definition.taskType}/${button.dataset.scheduleRun}/run`, { method: "POST" })); });
    } else if (definition.provider || definition.covers) {
      const button = document.createElement("button");
      button.className = "mini-btn";
      button.textContent = definition.provider ? "按已保存范围立即增量扫描" : "按已保存设置立即刷新封面";
      dialog.querySelector(".picker-foot").prepend(button);
      button.onclick = () => void runAction(button, output, async () => {
        config = await api("/api/config/status");
        if (definition.covers) return api("/api/integrations/emby/libraries/covers/refresh", { method: "POST", body: JSON.stringify({
          style: config.emby_cover_style, options: config.emby_cover_options || {}, library_ids: config.emby_cover_library_ids || [], library_options: config.emby_cover_library_options || {},
        }) });
        const provider = definition.provider;
        const directories = config[`${provider}_strm_included_directories`] || [];
        if (!directories.length) throw new Error("请先在 STRM 设置中保存扫描子目录");
        return api("/api/cloud/strm/jobs", { method: "POST", body: JSON.stringify({ provider, mode: "incremental", root_path: config[`${provider}_strm_source_root`], output_root: config.strm_output_root, include_directories: directories, playback_base_url: config.strm_playback_base_url }) });
      });
    }
  } catch (error) { output.textContent = error.message; }
}
