import { escapeHtml as esc, runAction } from "../../components/native-ui.js";
import { workflowStepsView, workflowLanes, workflowNodes } from "../transfer/native-workflow.js";

const name = (provider) => provider === "p115" ? "115" : "夸克";
const icon = (id) => `<svg class="ic"><use href="#i-${id}"/></svg>`;

export async function openNativeMediaDetail(api, item, onChanged = () => {}, onTrack = () => {}, options = {}) {
  const page = document.createElement("section");
  page.className = "media-detail-page";
  page.setAttribute("aria-label", `${item.title} · 媒体详情`);
  const isSeries = item.media_type !== "movie";
  const identity = { tmdb_id: item.tmdb_id, media_type: item.media_type, title: item.title, year: item.year || "", poster_url: item.poster_url || "", overview: item.overview || "" };
  const seasons = (item.seasons || []).filter((season) => season.season_number > 0);
  const facts = [["类型", isSeries ? "剧集" : "电影"], ["首映", item.release_date || item.first_air_date || item.year || "待定"], ["时长", item.runtime ? `${item.runtime} 分钟` : "未提供"], ["状态", item.status || "未提供"]];
  page.innerHTML = `<div class="md-toolbar"><button class="mini-btn" data-md-close>${icon("chev-l")}返回发现</button><span>TMDB COLLECTION</span></div>
    <section class="md-hero" style="${item.backdrop_url ? `background-image:linear-gradient(90deg,rgba(8,14,25,.94),rgba(8,14,25,.45)),url('${esc(item.backdrop_url)}')` : ""}">
      ${item.poster_url ? `<img src="${esc(item.poster_url)}" alt="${esc(item.title)}海报">` : ""}<div><small>TMDB · ${isSeries ? "TV SERIES" : "MOVIE"}</small><h1>${esc(item.title)} <small>${esc(item.year || "")}</small></h1><div class="md-meta"><span>★ ${item.vote_average ? Number(item.vote_average).toFixed(1) : "待评分"}</span><span>${isSeries ? "剧集" : "电影"}</span>${item.runtime ? `<span>${item.runtime} 分钟</span>` : ""}</div><p>${esc(item.overview || "暂无剧情简介。")}</p></div>
    </section><div class="md-lower"><aside class="panel md-profile"><span class="md-eyebrow">WORK PROFILE</span><h2>作品资料</h2><dl>${facts.map(([label, value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl><small>题材标签</small><div class="md-genres">${(item.genres || []).map((genre) => `<span class="pill">${esc(typeof genre === "string" ? genre : genre.name)}</span>`).join("") || '<span class="muted-note">暂无标签</span>'}</div></aside>
    <section class="panel md-workbench"><header><div><span class="md-eyebrow">MEDIAINDEX WORKFLOW</span><h2>核对与转存</h2></div>${icon("cloud")}</header><div class="md-controls"><label class="field">媒体分类<select class="input" data-md-category>${[["movie","电影"],["tv","电视剧"],["variety","综艺"],["anime","动漫"],["documentary","纪录片"],["concert","演唱会"]].map(([key,label])=>`<option value="${key}" ${key === (item.category || item.media_type) ? "selected" : ""}>${label}</option>`).join("")}</select></label>${isSeries ? `<fieldset class="md-seasons"><legend>选择季度</legend>${seasons.length ? seasons.map((season, index) => `<label><input type="checkbox" data-md-season value="${season.season_number}" ${index === 0 ? "checked" : ""}>${esc(season.name || `第 ${season.season_number} 季`)}</label>`).join("") : '<label>季度 <input class="input" type="number" min="1" value="1" data-md-season-number></label>'}</fieldset>` : ""}</div>
    <div class="md-providers" data-md-providers><div class="loading-block">正在读取网盘配置…</div></div>
    <div class="md-actions"><button class="btn ghost" data-md-wish disabled>${icon("star")}加入愿望单</button>${isSeries ? `<button class="btn ghost" data-md-track>${icon("bell")}加入智能追更</button>` : ""}<button class="btn ghost" data-md-refresh disabled>${icon("refresh")}刷新资源</button><button class="btn primary" data-md-transfer disabled>${icon("cloud")}一键转存到两边</button></div><p class="muted-note" data-md-combined-hint>分享资源经核验、命名后直接保存到各网盘正式媒体库。</p>
    <form class="md-manual"><label for="mdManualLink">手动分享链接</label><div><input class="input" id="mdManualLink" placeholder="粘贴夸克或 115 分享，按本作品身份核验入库" required><button class="mini-btn" type="submit">识别网盘</button></div><div data-md-manual-target></div></form><p class="inline-result" role="status" data-md-output></p>
    <section class="md-workflows" aria-label="自动入库整体进度"><header><h3>入库链路</h3><button class="mini-btn" data-md-workflow-refresh>刷新状态</button></header><div data-md-workflow></div></section></section></div>`;
  const container = options.container || document.getElementById("content") || document.getElementById("root");
  container.replaceChildren(page);
  page.querySelectorAll("[data-md-close]").forEach((button) => { button.onclick = () => { page.dispose(); if (options.onBack) options.onBack(); else page.remove(); }; });
  let config = {}, providers = [], revision = 0, busy = false, lanes = [], timer, copyTimer;
  function showCopyNotice(message, error = false) {
    if (disposed || !page.isConnected) return;
    window.clearTimeout(copyTimer);
    page.querySelector(".md-copy-notice")?.remove();
    const notice = document.createElement("div");
    notice.className = `md-copy-notice${error ? " error" : ""}`;
    notice.setAttribute("role", "status");
    notice.textContent = message;
    page.append(notice);
    copyTimer = window.setTimeout(() => notice.remove(), 1800);
  }
  const results = new Map(), selected = new Map(), submittedProviders = new Set(), expandedNodes = new Map(), renderedProviders = new Map();
  const output = page.querySelector("[data-md-output]");
  const providerRoot = page.querySelector("[data-md-providers]");
  const transferButton = page.querySelector("[data-md-transfer]");
  const refreshButton = page.querySelector("[data-md-refresh]");
  const category = () => page.querySelector("[data-md-category]").value;
  const chosenSeasons = () => !isSeries ? [0] : seasons.length ? [...page.querySelectorAll("[data-md-season]:checked")].map((input) => Number(input.value)) : [Number(page.querySelector("[data-md-season-number]").value)].filter((n) => Number.isInteger(n) && n > 0);
  const keyOf = (provider, season) => `${provider}:${season}`;
  const providerForLink = (value) => {
    try { const host = new URL(String(value).match(/https?:\/\/[^\s]+/i)?.[0] || value).hostname.toLowerCase(); return host === "pan.quark.cn" ? "quark" : ["115.com", "115cdn.com", "anxia.com"].some((domain) => host === domain || host.endsWith(`.${domain}`)) ? "p115" : ""; } catch { return ""; }
  };
  const selectedCandidate = (provider, season) => { const key = keyOf(provider, season); return results.get(key)?.candidates?.[selected.get(key)]; };
  const resourceUrl = (provider, season) => { const result = results.get(keyOf(provider, season)); return selectedCandidate(provider, season)?.share_url || result?.share_url || result?.source_share_url || ""; };
  const valid = (provider, season) => {
    const key = keyOf(provider, season), result = results.get(key), candidate = result?.candidates?.[selected.get(key)];
    const declared = candidate?.cloud_type === "115" ? "p115" : candidate?.cloud_type;
    const linkedProvider = candidate && (providerForLink(candidate.share_url) || (candidate.share_url?.startsWith("magnet:") ? "p115" : ""));
    return Boolean(result && !result.error && ((candidate?.share_url && (!declared || declared === provider) && (!linkedProvider || linkedProvider === provider)) || (result.ready && result.found && !result.requires_review && !selected.has(key))));
  };
  const ready = (provider) => providers.includes(provider) && chosenSeasons().length > 0 && chosenSeasons().every((season) => valid(provider, season));
  const syncConfigured = () => { const route = config.cross_copy_transport || "openlist"; return Boolean(config.openlist_enabled && config[`${route}_url`] && config[`has_${route}_token`] && config[`${route}_qas_library_path`] && config[`${route}_p115_library_path`]); };
  const canFallback = () => ready("quark") && providers.includes("p115") && chosenSeasons().every((season) => { const result = results.get(keyOf("p115", season)); return result && !result.error && !result.found && !result.requires_review && !result.candidate_count && !result.candidates?.length; });
  function updateButtons() {
    const both = ready("quark") && ready("p115"), fallback = canFallback();
    transferButton.hidden = providers.length < 2;
    transferButton.disabled = busy || submittedProviders.size > 0 || !(both || (fallback && syncConfigured()));
    transferButton.textContent = submittedProviders.size > 0 ? "已有网盘提交，请查看对应任务" : fallback ? "先存夸克，再同步到115" : "一键转存到两边";
    page.querySelector("[data-md-combined-hint]").textContent = fallback ? syncConfigured() ? "夸克完成核验并进入正式库后，按现有跨盘通路补齐 115。" : "夸克有资源，115 暂无资源；请先配置并启用跨盘通路，或单独转存到夸克。" : "分享资源经核验、命名后直接写入正式媒体库；磁力资源仍需先完成 115 下载。";
    refreshButton.disabled = busy || !providers.length;
    page.querySelectorAll(".md-controls input,.md-controls select,.md-providers input,.md-providers select,.md-providers button").forEach((control) => {
      control.disabled = busy;
    });
    page.querySelectorAll("[data-md-provider-transfer]").forEach((button) => { const provider = button.dataset.mdProviderTransfer; button.disabled = busy || submittedProviders.has(provider) || !ready(provider); button.textContent = submittedProviders.has(provider) ? `${name(provider)}已提交` : `转存到${name(provider)}`; });
    page.querySelectorAll("[data-md-copy-share]").forEach((button) => { button.disabled = busy || !resourceUrl(button.dataset.mdCopyShare, Number(button.dataset.season)); });
  }
  function renderProviders() {
    if (!providers.length) { providerRoot.innerHTML = '<p class="muted-note">没有启用的网盘，请先配置网盘连接。</p>'; updateButtons(); return; }
    if (!providerRoot.querySelector("[data-md-provider]")) {
      providerRoot.innerHTML = providers.map((provider) => `<article class="md-provider" data-md-provider="${provider}"><header><b>${name(provider)}</b><span class="pill">自动 STRM · ${config[`${provider}_strm_enabled`] ? "开启" : "关闭"}</span></header><div data-provider-resources></div><button class="btn primary md-provider-transfer" data-md-provider-transfer="${provider}" disabled>转存到${name(provider)}</button></article>`).join("");
      providerRoot.querySelectorAll("[data-md-provider-transfer]").forEach((button) => { button.onclick = () => void submitTransfer([button.dataset.mdProviderTransfer], button); });
    }
    for (const provider of providers) {
      const card = providerRoot.querySelector(`[data-md-provider="${provider}"]`);
      const seasonNumbers = chosenSeasons();
      const resourceValues = seasonNumbers.map((season) => results.get(keyOf(provider, season)));
      const previous = renderedProviders.get(provider) || {};
      if (String(previous.seasons) !== String(seasonNumbers) || resourceValues.some((result, index) => result !== previous.resources?.[index]) || !previous.resources) {
        card.querySelector("[data-provider-resources]").innerHTML = seasonNumbers.map((season) => {
          const key = keyOf(provider, season), result = results.get(key);
          return `<div class="md-resource"><div class="md-resource-status"><b>${season ? `S${season} · ` : ""}${result ? result.error ? "查询失败" : result.requires_review ? "需要核对" : result.ready ? "资源就绪" : result.found ? "已找到候选" : "暂无可用资源" : "正在检索…"}</b><small>${esc(result?.error || result?.message || "正在核对资源与文件，请稍候")}</small></div>${result?.candidates?.length ? `<label class="field">候选资源<select class="input" data-md-candidate="${key}"><option value="">请选择候选</option>${result.candidates.map((candidate, index) => `<option value="${index}" ${selected.get(key) === index ? "selected" : ""}>${esc(candidate.title || `候选 ${index + 1}`)}${candidate.files?.length ? ` · ${candidate.files.length} 个文件` : ""}</option>`).join("")}</select></label>` : ""}${result?.episode_numbers?.length ? `<small>可用剧集：${esc(result.episode_numbers.map((n) => `E${n}`).join(" · "))}</small>` : ""}</div>`;
        }).join("") || '<p class="muted-note">请先选择季度</p>';
        card.querySelectorAll(".md-resource").forEach((resource, index) => { resource.insertAdjacentHTML("beforeend", `<div class="md-resource-links" data-md-links="${seasonNumbers[index]}"></div>`); });
        card.querySelectorAll("[data-md-candidate]").forEach((input) => { input.onchange = () => { if (input.value === "") selected.delete(input.dataset.mdCandidate); else selected.set(input.dataset.mdCandidate, Number(input.value)); renderResourceLinks(card, provider, seasonNumbers); updateButtons(); }; });
      }
      renderResourceLinks(card, provider, seasonNumbers);
      renderedProviders.set(provider, { seasons: seasonNumbers, resources: resourceValues });
    }
    updateButtons();
  }
  function renderResourceLinks(card, provider, seasons) {
    for (const season of seasons) {
      const host = card.querySelector(`[data-md-links="${season}"]`);
      if (!host) continue;
      const url = resourceUrl(provider, season), safe = /^https?:\/\//i.test(url);
      const pansou = /^https?:\/\//i.test(config.pansou_url || "") ? config.pansou_url : "";
      host.innerHTML = `${safe ? `<a class="mini-btn" href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开资源</a>` : ""}<button class="mini-btn" data-md-copy-share="${provider}" data-season="${season}" ${url ? "" : "disabled"}>分享链接</button>${pansou ? `<a class="mini-btn" href="${esc(pansou)}" target="_blank" rel="noopener noreferrer">进入 PanSou 查看</a>` : ""}`;
      host.querySelector("[data-md-copy-share]").onclick = async (event) => {
        const button = event.currentTarget;
        if (button.disabled) return;
        button.disabled = true;
        try {
          const candidate = selectedCandidate(provider, season), code = candidate?.password || candidate?.extract_code;
          const url = resourceUrl(provider, season);
          if (!url) throw new Error("请先选择资源");
          await navigator.clipboard.writeText(url + (code ? ` 提取码：${code}` : ""));
          showCopyNotice(`${name(provider)}分享链接已复制`);
        } catch (error) { showCopyNotice(error.message || "复制失败，请重试", true); }
        finally { updateButtons(); }
      };
    }
  }
  async function search(refresh = false) {
    if (busy) return;
    const current = ++revision;
    submittedProviders.clear(); results.clear(); selected.clear(); output.textContent = "";
    renderProviders();
    const jobs = providers.flatMap((provider) => chosenSeasons().map(async (season) => {
      const query = new URLSearchParams({ provider, title: item.title, year: item.year || "", refresh: String(refresh) });
      if (season) query.set("season_number", String(season));
      let result;
      try { result = await api(`/api/media/${item.media_type}/${item.tmdb_id}/resources?${query}`); } catch (error) { result = { error: error.message }; }
      if (disposed || !page.isConnected || revision !== current) return;
      results.set(keyOf(provider, season), result);
      renderProviders();
    }));
    await Promise.all(jobs);
  }
  async function refreshWorkflow() {
    const data = await api(`/api/transfers/workflow/${item.media_type}/${item.tmdb_id}`);
    if (disposed || !page.isConnected) return;
    const focused = page.ownerDocument.activeElement;
    const focusedLane = focused?.closest?.("[data-workflow-lane]")?.dataset.workflowLane;
    const focusedNode = focused?.dataset?.workflowNode;
    const focusedClose = focused?.hasAttribute?.("data-node-close");
    lanes = workflowLanes(data);
    const displayLanes = [...lanes, ...providers.filter((provider) => !lanes.some((lane) => lane.provider === provider)).map((provider) => ({ provider, steps: !lanes.length ? data.steps || [] : workflowNodes.map(([key]) => ({ key, status: "pending", message: "本次未启动，网盘链路独立执行" })) }))];
    page.querySelector("[data-md-workflow]").innerHTML = displayLanes.map((lane) => `<article class="md-workflow-lane" data-workflow-lane="${esc(`${lane.provider}:${lane.job_id || 0}:${lane.season_number || 0}`)}"><header><b>${name(lane.provider)}${lane.season_number ? ` · S${lane.season_number}` : ""}</b><span>${lane.job_id ? `任务 #${lane.job_id}` : "等待开始"}</span></header>${workflowStepsView(lane, true)}<div class="workflow-node-detail" hidden></div></article>`).join("");
    page.querySelectorAll("[data-workflow-lane]").forEach((lane) => showNodeDetail(lane));
    if (focusedLane && (focusedNode || focusedClose)) {
      const lane = [...page.querySelectorAll("[data-workflow-lane]")].find((node) => node.dataset.workflowLane === focusedLane);
      if (focusedClose) lane?.querySelector("[data-node-close]")?.focus({ preventScroll: true });
      else [...(lane?.querySelectorAll("[data-workflow-node]") || [])].find((node) => node.dataset.workflowNode === focusedNode)?.focus({ preventScroll: true });
    }
  }
  async function poll() {
    try { await refreshWorkflow(); } catch (error) { if (page.isConnected) page.querySelector("[data-md-workflow]").textContent = `链路读取失败：${error.message}`; }
    if (page.isConnected && !disposed) timer = window.setTimeout(poll, 5000);
  }
  let disposed = false;
  page.dispose = () => { disposed = true; revision++; window.clearTimeout(timer); window.clearTimeout(copyTimer); page.querySelector(".md-copy-notice")?.remove(); };
  function showNodeDetail(lane) {
    const key = expandedNodes.get(lane.dataset.workflowLane);
    const button = [...lane.querySelectorAll("[data-workflow-node]")].find((node) => node.dataset.workflowNode === key);
    const detail = lane.querySelector(".workflow-node-detail");
    lane.querySelectorAll("[data-workflow-node]").forEach((node) => node.setAttribute("aria-expanded", String(node === button)));
    detail.hidden = !button;
    if (!button) { detail.replaceChildren(); return; }
    const data = button.dataset;
    detail.innerHTML = `<header><b>${esc(data.workflowLabel)}</b><span class="pill">${esc(data.workflowStatus)}</span><button class="icon-btn" type="button" data-node-close aria-label="收起节点详情">${icon("close")}</button></header><p>${esc(data.workflowMessage)}</p>${data.workflowTime ? `<small>更新时间 · ${esc(data.workflowTime.replace("T", " "))}</small>` : ""}`;
    detail.querySelector("[data-node-close]").onclick = () => { expandedNodes.delete(lane.dataset.workflowLane); showNodeDetail(lane); button.focus(); };
  }
  page.querySelector("[data-md-workflow]").onclick = (event) => {
    const button = event.target.closest("button[data-workflow-node]");
    if (!button) return;
    const lane = button.closest("[data-workflow-lane]"), key = button.dataset.workflowNode;
    if (expandedNodes.get(lane.dataset.workflowLane) === key) expandedNodes.delete(lane.dataset.workflowLane);
    else expandedNodes.set(lane.dataset.workflowLane, key);
    showNodeDetail(lane);
  };
  page.querySelector("[data-md-workflow-refresh]").onclick = (event) => void runAction(event.currentTarget, output, refreshWorkflow);
  refreshButton.onclick = () => void search(true);
  page.querySelectorAll("[data-md-season],[data-md-season-number]").forEach((input) => { input.onchange = () => void search(); });
  page.querySelector("[data-md-track]")?.addEventListener("click", () => onTrack(item));
  page.querySelector("[data-md-wish]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
    if (!chosenSeasons().length) throw new Error("请先选择季度");
    const outcomes = await Promise.allSettled(providers.flatMap((provider) => chosenSeasons().map((season) => api("/api/wishlist", { method: "POST", body: JSON.stringify({ ...identity, category: category(), provider, season_number: season || undefined, save_target: "cloud" }) }))));
    const failed = outcomes.filter((result) => result.status === "rejected");
    return { message: `已加入 ${outcomes.length - failed.length} 项愿望${failed.length ? `；${failed.length} 项失败：${failed.map((r) => r.reason.message).join("；")}` : ""}` };
  });
  async function submitTransfer(targets, button, fallback = false, manualLink = "") {
    if (busy || targets.some((provider) => submittedProviders.has(provider))) return;
    if (!chosenSeasons().length || targets.some((provider) => !manualLink && !ready(provider))) { output.textContent = "请先选择并核对对应网盘的资源"; return; }
    if (fallback && (!canFallback() || !syncConfigured())) { output.textContent = "资源状态或跨盘配置已变更，请重新核对"; return; }
    const items = targets.flatMap((provider) => chosenSeasons().map((season) => {
      const result = results.get(keyOf(provider, season)) || {}, candidate = result.candidates?.[selected.get(keyOf(provider, season))];
      const entry = { provider, season_number: season || undefined, openlist_fallback_to_p115: fallback && provider === "quark" };
      if (manualLink || candidate) { entry.preferred_share_urls = [manualLink || candidate.share_url]; entry.preferred_share_only = true; }
      else if (result.plan_reusable && result.plan) entry.media_plan = result.plan;
      else { const urls = [result.share_url, result.source_share_url].filter(Boolean); if (urls.length) { entry.preferred_share_urls = [...new Set(urls)]; entry.preferred_share_only = true; } }
      return entry;
    }));
    busy = true;
    const pending = runAction(button, output, async () => {
      const response = await api("/api/transfers/batches", { method: "POST", body: JSON.stringify({ ...identity, category: category(), target: "cloud", items, simple_matching: false }) });
      if (response?.ok === false) throw new Error(response.message || "转存未提交");
      targets.forEach((provider) => submittedProviders.add(provider)); await onChanged();
      try { await refreshWorkflow(); } catch { /* Polling keeps the submitted result visible. */ }
      return { ...response, message: response.message || `批次 #${response.id} 已提交，下方显示各网盘的独立链路` };
    });
    updateButtons(); await pending; busy = false; updateButtons();
  }
  transferButton.onclick = () => {
    if (transferButton.disabled) return;
    const fallback = canFallback();
    void submitTransfer(fallback ? ["quark"] : ["quark", "p115"], transferButton, fallback);
  };
  const manualForm = page.querySelector(".md-manual");
  let manualRevision = 0;
  manualForm.querySelector("input").oninput = () => { manualRevision++; manualForm.querySelector("[data-md-manual-target]").replaceChildren(); };
  manualForm.onsubmit = async (event) => {
    event.preventDefault();
    if (busy) return;
    const link = manualForm.querySelector("input").value.trim(), current = ++manualRevision;
    await runAction(manualForm.querySelector('[type="submit"]'), output, async () => {
      const provider = providerForLink(link);
      if (!provider) throw new Error("这里仅接收夸克或 115 分享链接；普通下载和磁力请使用发现页的链接下载");
      if (!providers.includes(provider)) throw new Error(`请先启用${name(provider)}网盘`);
      if (disposed || !page.isConnected || current !== manualRevision) return { message: "链接已更改，请重新核对" };
      const target = manualForm.querySelector("[data-md-manual-target]");
      target.innerHTML = `<p>识别为${name(provider)}分享。确认后由后端按当前作品与季度核验、命名并写入正式媒体库。</p><button class="mini-btn primary" type="button">确认转存到${name(provider)}</button>`;
      target.querySelector("button").onclick = async (click) => {
        if (current !== manualRevision || busy) return;
        await submitTransfer([provider], click.currentTarget, false, link);
        if (submittedProviders.has(provider)) target.replaceChildren();
      };
      return { message: "已识别网盘；分享文件将在提交后核验，不选择云下载目录" };
    });
  };
  try {
    config = await api("/api/config/status");
    if (disposed || !page.isConnected) return;
    providers = (config.enabled_providers || []).filter((provider) => ["p115", "quark"].includes(provider));
    page.querySelector("[data-md-wish]").disabled = !providers.length;
    await Promise.all([search(), poll()]);
  } catch (error) { output.textContent = error.message; }
  return page;
}
