import { escapeHtml as esc, modal, runAction } from "../../components/native-ui.js";
import { pickNativeDirectory } from "../../components/cloud/native-directory-picker.js";

export function openTrackingSettings(api, task, onSaved) {
  const dialog = modal("追更设置", `${task.title} · S${task.season_number || 1}`);
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  const states = task.provider_states?.length ? task.provider_states : [task];
  const p115 = states.find((state) => state.provider === "p115");
  body.innerHTML = states.map((state) => `<section class="panel panel-pad" data-tracking-state="${state.id}">
    <div class="panel-head"><div><h3>${state.provider === "p115" ? "115" : state.provider === "quark" ? "夸克" : esc(state.provider)}</h3><small>${esc(state.completion_state || state.status || "")}</small></div></div>
    <div class="field"><label>保存路径</label><div class="directory-input"><input class="input" data-state-path value="${esc(state.save_path || "")}"><button class="directory-icon" data-state-browse aria-label="选择保存目录" title="选择目录"><svg class="ic"><use href="#i-folder"/></svg></button></div></div>
    <div class="field"><label>最终集号（留空使用 TMDB）</label><input class="input" data-state-final type="number" min="1" max="9999" value="${state.final_episode_override ?? ""}"></div>
    <div class="row-actions"><button class="mini-btn primary" data-state-save>保存路径与集数</button><button class="mini-btn" data-state-run>立即巡检</button><button class="mini-btn" data-state-season>处理本季已播集</button><button class="mini-btn" data-state-toggle>${state.status === "active" ? "暂停" : "恢复"}</button><button class="mini-btn" data-state-archive ${["caught_up", "complete"].includes(state.completion_state) && state.status !== "archived" ? "" : "disabled"}>归档本季</button></div>
  </section>`).join("") + `<section class="panel panel-pad"><div class="panel-head"><div><h3>跨盘自动补齐</h3><small>本季夸克原生转存成功、115 未找到原生资源时才补齐</small></div></div><label class="check"><input type="checkbox" data-tracking-fallback ${p115?.openlist_fallback_to_p115 ? "checked" : ""}>允许夸克 → 115 补齐</label><button class="mini-btn" data-fallback-save ${p115 ? "" : "disabled"}>保存本季规则</button></section>`;
  for (const state of states) {
    const section = body.querySelector(`[data-tracking-state="${state.id}"]`);
    const bind = (selector, action) => { const button = section.querySelector(selector); button.onclick = () => void runAction(button, output, async () => { const result = await action(); await onSaved(); return result; }); };
    section.querySelector("[data-state-browse]").onclick = () => void pickNativeDirectory(api, state.provider === "qas" ? "quark" : state.provider, (path) => { section.querySelector("[data-state-path]").value = path; });
    bind("[data-state-save]", async () => {
      const value = section.querySelector("[data-state-final]").value.trim();
      const final_episode = value ? Number(value) : null;
      if (value && (!Number.isInteger(final_episode) || final_episode < 1 || final_episode > 9999)) throw new Error("最终集号须为 1–9999");
      await api(`/api/tracking/${state.id}/save-path`, { method: "PATCH", body: JSON.stringify({ save_path: section.querySelector("[data-state-path]").value.trim() }) });
      await api(`/api/tracking/${state.id}/final-episode`, { method: "PUT", body: JSON.stringify({ final_episode }) });
      return { message: "路径与最终集数已保存" };
    });
    bind("[data-state-run]", () => api(`/api/tracking/${state.id}/run`, { method: "POST" }));
    bind("[data-state-season]", () => api(`/api/tracking/${state.id}/run-season`, { method: "POST" }));
    bind("[data-state-toggle]", async () => {
      const result = await api(`/api/tracking/${state.id}/${state.status === "active" ? "pause" : "resume"}`, { method: "POST" });
      state.status = state.status === "active" ? "paused" : "active";
      section.querySelector("[data-state-toggle]").textContent = state.status === "active" ? "暂停" : "恢复";
      return { ...result, message: state.status === "active" ? "已恢复" : "已暂停" };
    });
    bind("[data-state-archive]", async () => {
      const result = await api(`/api/tracking/${state.id}/archive`, { method: "POST" });
      section.querySelector("[data-state-archive]").disabled = true;
      return { ...result, message: "本季已归档" };
    });
  }
  body.querySelector("[data-fallback-save]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
    const result = await api(`/api/tracking/${p115.id}/openlist-fallback`, { method: "PATCH", body: JSON.stringify({ enabled: body.querySelector("[data-tracking-fallback]").checked }) });
    await onSaved();
    return { ...result, message: "本季跨盘规则已保存" };
  });
}

export function openWishlistSettings(api, item, onSaved) {
  const dialog = modal("愿望单设置", item.title);
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  const states = item.provider_states?.length ? item.provider_states : [item];
  body.innerHTML = `<div class="field"><label>每天检查小时（0–23）</label><input class="input" type="number" min="0" max="23" data-wish-hour value="${item.check_hour ?? 9}"></div>
    <div class="list">${states.map((state) => `<label class="list-row"><input type="checkbox" data-wish-enabled="${state.id}" ${state.enabled !== false ? "checked" : ""}><div class="grow"><b>${esc(state.provider)}</b><small>${esc(state.last_error || state.status || "")}</small></div></label>`).join("")}</div>
    <p class="muted-note">暂停后保留愿望单与历史记录。</p>`;
  dialog.querySelector(".picker-foot").innerHTML = '<button class="mini-btn primary" data-wish-save>保存愿望单设置</button>';
  dialog.querySelector("[data-wish-save]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
    const check_hour = Number(body.querySelector("[data-wish-hour]").value);
    if (!Number.isInteger(check_hour) || check_hour < 0 || check_hour > 23) throw new Error("检查小时须为 0–23");
    for (const state of states) {
      await api(`/api/wishlist/${state.id}/schedule`, { method: "PATCH", body: JSON.stringify({ check_hour }) });
      await api(`/api/wishlist/${state.id}/enabled`, { method: "PATCH", body: JSON.stringify({ enabled: body.querySelector(`[data-wish-enabled="${state.id}"]`).checked }) });
    }
    await onSaved();
    return { message: "愿望单设置已保存" };
  });
}

export function openReviewSelection(api, candidate, onSaved) {
  const dialog = modal("核对待确认资源", candidate.title || candidate.resource_title || "资源候选");
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  const files = candidate.files || [];
  body.innerHTML = `<p class="muted-note">${esc(candidate.job_message || candidate.message || "")}</p><p>${esc((candidate.reasons || []).join(" · "))}</p><span class="pill warn">${esc(candidate.provider || candidate.job_provider)} · 人工核对</span>
    <div class="list">${files.map((file, i) => `<label class="list-row"><input type="checkbox" data-review-file="${i}" checked><b>${esc(file)}</b></label>`).join("") || '<p class="muted-note">没有可选文件列表；确认将提交当前候选，由后端再次核验。</p>'}</div>`;
  dialog.querySelector(".picker-foot").innerHTML = '<button class="mini-btn" data-review-search>重新搜索本任务</button><button class="mini-btn primary" data-review-submit>确认所选资源并入库</button>';
  dialog.querySelector("[data-review-search]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
    const result = await api(`/api/review/job/${candidate.job_id}/research`, { method: "POST" });
    await onSaved();
    dialog.close();
    return result;
  });
  dialog.querySelector("[data-review-submit]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
    const selected_files = [...body.querySelectorAll("[data-review-file]:checked")].map((input) => files[Number(input.dataset.reviewFile)]);
    if (files.length && !selected_files.length) throw new Error("请至少选择一个文件");
    const result = await api(`/api/review/${candidate.id}/confirm`, { method: "POST", body: JSON.stringify({ selected_files }) });
    if (result.ok !== false) { await onSaved(); dialog.close(); }
    return result;
  });
}
