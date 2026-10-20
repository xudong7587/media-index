function taskCard(task) {
  const states = (task.provider_states || []).filter((entry) => entry.status !== "disabled");
  const statesForFilter = subsState.provider ? (task.provider_states || []).filter((entry) => entry.provider === subsState.provider) : states;
  if (subsState.provider && !statesForFilter.length) return "";
  const total = task.episode_count || Math.max(0, ...(task.provider_states || []).map((entry) => entry.episode_count || 0));
  const saved = task.saved_count || Math.max(0, ...(task.provider_states || []).map((entry) => entry.saved_count || 0));
  const percent = total ? Math.min(100, Math.round((saved / total) * 100)) : 0;
  const openState = statesForFilter.find((entry) => subsState.panels[entry.id]);
  const drives = statesForFilter.map((entry) => {
    const open = Boolean(subsState.panels[entry.id]);
    return `<div class="drive">
      <label><input type="checkbox" ${entry.status === "active" ? "checked" : ""} data-provider-toggle="${esc(entry.provider)}" data-task="${task.id}" /><b>${providerName(entry.provider)}</b></label>
      <small>已确认 ${entry.saved_count || 0} 集</small>
      <span class="pill ok"><i></i>在线</span>
      <button class="drive-caret" data-episodes="${entry.id}" data-task="${task.id}" aria-expanded="${open}" aria-label="展开${providerName(entry.provider)}分集"><svg class="ic" style="${open ? "transform:rotate(180deg)" : ""}"><use href="#i-chev-d"/></svg></button>
    </div>`;
  }).join("");
  const paused = task.status !== "active";
  return `
  <article class="task-card" data-task-card="${task.id}">
    <div class="task-head">
      <span class="thumb" style="${posterUrl(task) ? `background-image:url(${esc(posterUrl(task))})` : ""}"></span>
      <div class="task-title">
        <div><b>${esc(task.title)}</b>${pillFor(task.status)}</div>
        <small>${mediaTypeText(task.media_type)} · ${esc(task.year || "")}${task.next_check_at ? ` · 下次巡检 ${esc(formatDate(task.next_check_at))}` : ""} · 简介：${esc(task.overview || "暂无简介")}</small>
      </div>
      <div class="task-progress"><span>S${String(task.season_number || 1).padStart(2, "0")} 共 ${total || "?"} 集</span><div class="progress-line"><span class="progress"><i style="width:${percent}%"></i></span><span>${saved} / ${total || "?"}</span></div></div>
    </div>
    <div class="task-drives">
      ${drives || `<span class="muted-note">未启用网盘，勾选后开始追更。</span>`}
      <div class="task-path"><label>保存路径</label><input class="input" value="${esc(task.save_path || (states[0] && states[0].save_path) || "")}" data-path-input="${task.id}" /><div class="picker"><button class="mini-btn" data-pick-path="${task.id}" data-providers="${states.map((entry) => entry.provider).join(",")}">选择</button></div></div>
    </div>
    <div class="drive-panels">${openState ? episodePanelInline(task, openState) : ""}</div>
    <div class="task-actions">
      <div class="ctrl"><label>追更时间</label><input class="input" type="time" value="${esc(task.check_time || "20:00")}" data-time-input="${task.id}" /><button class="mini-btn" data-save-time="${task.id}">保存</button></div>
      <span class="task-next">${task.next_check_at ? `下次巡检 ${esc(formatDate(task.next_check_at))}` : "等待排期"}</span>
      <div class="row-actions">
        <button class="mini-btn" data-refresh-storage="${task.id}">刷新已存</button>
        <button class="mini-btn" data-sync-storage="${task.id}">夸克→115 补齐</button>
        <button class="mini-btn primary" data-run="${task.id}">执行</button>
        <button class="mini-btn" data-toggle="${task.id}" data-status="${esc(task.status)}">${paused ? "恢复" : "暂停"}</button>
        <button class="mini-btn danger" data-delete="${task.id}">删除</button>
      </div>
    </div>
  </article>`;
}

function episodePanelInline(task, entry) {
  const data = subsState.episodes[entry.id];
  const head = `<div class="ep-head"><b>${providerName(entry.provider)} · ${esc(task.title)}</b><span>${data ? episodeSummary(entry, data) : "正在读取分集…"}</span></div>`;
  if (!data) return `<div class="drive-episodes">${head}</div>`;
  const episodes = data.episodes || [];
  if (!episodes.length) return `<div class="drive-episodes">${head}<div class="empty-state" style="padding:14px 8px"><b>没有分集数据</b><span>先刷新已存或等待巡检。</span></div></div>`;
  return `<div class="drive-episodes">${head}
    <div class="ep-row">${episodes.map((episode) => `<button class="ep ${episode.status === "saved" ? "saved" : episode.aired ? "missing" : "unaired"}" data-ep-pick="${episode.episode_number}" data-ep-saved="${episode.status === "saved"}" title="${esc(episode.title || "")} ${esc(episode.air_date || "")}">E${String(episode.episode_number).padStart(2, "0")}</button>`).join("")}</div>
    <div class="ep-actions">
      <input class="input" data-share-input="${task.id}" placeholder="粘贴夸克分享链接，只补所选集" />
      <button class="mini-btn" data-fill-share="${task.id}">链接补齐所选</button>
      <button class="mini-btn" data-sync-selected="${task.id}">夸克补齐所选</button>
      <button class="mini-btn primary" data-ep-fill="${task.id}" style="margin-left:auto">补齐所选</button>
    </div>
  </div>`;
}

function episodeSummary(entry, data) {
  const episodes = data.episodes || [];
  const saved = episodes.filter((episode) => episode.status === "saved").length || (entry.saved_count || 0);
  const missing = episodes.filter((episode) => episode.status !== "saved" && episode.aired).length;
  const unaired = episodes.filter((episode) => !episode.aired).length;
  return `已存 ${saved} / 缺 ${missing} / 未播 ${unaired}`;
}
