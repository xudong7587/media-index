import { escapeHtml as esc, modal, runAction } from "../../components/native-ui.js";

const providerOptions = (config) => (config.enabled_providers || ["quark", "p115"]).filter((p) => ["quark", "p115"].includes(p));
const providerName = (p) => p === "p115" ? "115" : "夸克";
const identity = (item) => ({
  tmdb_id: item.tmdb_id, media_type: item.media_type, category: item.category || item.media_type,
  title: item.title, year: item.year || "", poster_url: item.poster_url || "", overview: item.overview || "",
});
function seasonField(item) {
  if (item.media_type === "movie") return "";
  const seasons = (item.seasons || []).filter((s) => s.season_number > 0);
  return `<div class="field"><label for="resourceSeason">季度</label>${seasons.length
    ? `<select class="input" id="resourceSeason">${seasons.map((s) => `<option value="${s.season_number}">${esc(s.name || `第 ${s.season_number} 季`)} · ${s.episode_count || 0} 集</option>`).join("")}</select>`
    : '<input class="input" id="resourceSeason" type="number" min="1" value="1">'}</div>`;
}

export async function openResourceSearch(api, item, onSubmitted = () => {}) {
  const dialog = modal(item.title, "按网盘核对候选，命名后直接写入正式媒体库", "resource-dialog");
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  let version = 0;
  let resources = null;
  let busy = false;
  let activeProvider = "";
  let activeSeason;
  let submitted = false;
  try {
    const config = await api("/api/config/status");
    if (!dialog.isConnected) return;
    const providers = providerOptions(config);
    body.innerHTML = `<div class="form-grid native-form"><div class="field"><label for="resourceProvider">网盘</label><select class="input" id="resourceProvider">${providers.map((p) => `<option value="${p}" ${p === config.default_provider ? "selected" : ""}>${providerName(p)}</option>`).join("")}</select></div>${seasonField(item)}</div>
      <div class="row-actions"><button class="mini-btn" data-resource-search ${providers.length ? "" : "disabled"}>重新搜索</button><button class="mini-btn" data-resource-wish ${providers.length ? "" : "disabled"}>加入愿望单</button></div>
      <div data-resource-results></div><p class="muted-note">分享按当前作品身份核验并直接整理入库；磁力仍需先完成 115 下载。</p>`;
    dialog.querySelector(".picker-foot").innerHTML = '<button class="mini-btn primary" data-resource-submit disabled>确认候选并提交转存</button>';
    const submit = dialog.querySelector("[data-resource-submit]");
    const results = body.querySelector("[data-resource-results]");
    const providerInput = body.querySelector("#resourceProvider");
    const seasonInput = body.querySelector("#resourceSeason");
    const getSeason = () => seasonInput ? Number(seasonInput.value) : undefined;
    async function search(refresh = false) {
      if (busy) return;
      const revision = ++version;
      resources = null;
      submitted = false;
      activeProvider = providerInput.value;
      activeSeason = getSeason();
      submit.disabled = true;
      output.textContent = "";
      results.innerHTML = '<div class="loading-block">正在核对资源候选…</div>';
      if (!activeProvider || (seasonInput && (!Number.isInteger(activeSeason) || activeSeason < 1))) {
        results.textContent = "请先启用网盘并选择有效季度";
        return;
      }
      const query = new URLSearchParams({ title: item.title, year: item.year || "", provider: activeProvider, refresh: String(refresh) });
      if (activeSeason) query.set("season_number", String(activeSeason));
      const [resourceResult] = await Promise.allSettled([
        api(`/api/media/${encodeURIComponent(item.media_type)}/${item.tmdb_id}/resources?${query}`),
      ]);
      if (!dialog.isConnected || version !== revision) return;
      if (resourceResult.status === "rejected") {
        results.innerHTML = `<p class="inline-result error">${esc(resourceResult.reason.message)}</p>`;
        return;
      }
      resources = resourceResult.value;
      const candidates = resources.candidates || [];
      results.innerHTML = `<div class="panel-head"><div><h3>资源候选</h3><small>${esc(resources.message || (resources.found ? "已找到资源" : "暂未找到资源"))}</small></div><span class="pill ${resources.requires_review ? "warn" : resources.ready ? "ok" : "muted"}">${esc(resources.stage || "已查询")}</span></div>
        ${candidates.length ? `<div class="list">${candidates.map((candidate, i) => `<label class="list-row"><input type="radio" name="resourceCandidate" value="${i}"><div class="grow"><b>${esc(candidate.title || "候选资源")}</b><small>${esc([candidate.source, ...(candidate.reasons || [])].filter(Boolean).join(" · "))}</small><small>${candidate.files?.length || 0} 个可见文件 · ${esc(candidate.cloud_type || activeProvider)}</small></div></label>`).join("")}</div>` : '<p class="muted-note">没有可单独选择的候选，可在资源就绪后提交后端已核验的方案，或加入愿望单。</p>'}`;
      const update = () => {
        const selected = results.querySelector('input[name="resourceCandidate"]:checked');
        const candidate = selected ? candidates[Number(selected.value)] : null;
        const cloud = candidate?.cloud_type === "115" ? "p115" : candidate?.cloud_type;
        submit.disabled = busy || submitted || (candidate ? !candidate.share_url || Boolean(cloud && cloud !== activeProvider) : !(resources.ready && resources.found && !resources.requires_review));
      };
      results.querySelectorAll('input[name="resourceCandidate"]').forEach((input) => { input.onchange = update; });
      update();
    }
    providerInput.onchange = () => void search();
    if (seasonInput) seasonInput.onchange = () => void search();
    body.querySelector("[data-resource-search]").onclick = () => void search(true);
    body.querySelector("[data-resource-wish]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
      await api("/api/wishlist", { method: "POST", body: JSON.stringify({ ...identity(item), season_number: getSeason(), provider: providerInput.value, save_target: "cloud" }) });
      return { message: "已加入愿望单，可在订阅页设置检查时间" };
    });
    submit.onclick = async () => {
      if (busy || submit.disabled) return;
      const selected = results.querySelector('input[name="resourceCandidate"]:checked');
      const candidate = selected ? resources?.candidates?.[Number(selected.value)] : null;
      if (!resources || submitted) return;
      busy = true;
      const pending = runAction(submit, output, async () => {
        const child = { provider: activeProvider, season_number: activeSeason };
        if (candidate) {
          child.preferred_share_urls = [candidate.share_url];
          child.preferred_share_only = true;
        } else if (resources.plan_reusable && resources.plan) child.media_plan = resources.plan;
        else { const urls = [resources.share_url, resources.source_share_url].filter(Boolean); if (urls.length) { child.preferred_share_urls = [...new Set(urls)]; child.preferred_share_only = true; } }
        const response = await api("/api/transfers/batches", { method: "POST", body: JSON.stringify({ ...identity(item), target: "cloud", items: [child], simple_matching: false }) });
        if (response?.ok === false) throw new Error(response.message || "转存未提交");
        submitted = true;
        await onSubmitted();
        return { ...response, message: response.message || `任务 #${response.id} 已提交，可到任务中心查看核验与执行结果` };
      });
      body.querySelectorAll("input,select,button").forEach((node) => { node.disabled = true; });
      const result = await pending;
      busy = false;
      body.querySelectorAll("input,select,button").forEach((node) => { node.disabled = false; });
      if (result) submit.disabled = true;
    };
    await search();
  } catch (error) { output.textContent = error.message; }
}

export async function openTrackingSetup(api, item, onSubmitted = () => {}) {
  if (item.media_type === "movie") return openResourceSearch(api, item, onSubmitted);
  const dialog = modal("加入智能追更", `${item.title} · 选择季度和网盘`, "tracking-setup-dialog");
  const output = dialog.querySelector('[role="status"]');
  try {
    const config = await api("/api/config/status");
    if (!dialog.isConnected) return;
    const providers = providerOptions(config);
    dialog.querySelector(".native-dialog-body").innerHTML = `<div class="form-grid native-form">${seasonField(item)}<div class="field"><label for="trackingProvider">网盘</label><select class="input" id="trackingProvider">${providers.map((p) => `<option value="${p}" ${p === config.default_provider ? "selected" : ""}>${providerName(p)}</option>`).join("")}</select></div></div><p class="muted-note">自动追更从当前进度继续；历史缺集请在订阅页手动补齐。</p>`;
    dialog.querySelector(".picker-foot").innerHTML = `<button class="mini-btn primary" data-tracking-create ${providers.length ? "" : "disabled"}>确认加入追更</button>`;
    const button = dialog.querySelector("[data-tracking-create]");
    button.onclick = async () => {
      const result = await runAction(button, output, async () => {
        const season = Number(dialog.querySelector("#resourceSeason").value);
        if (!Number.isInteger(season) || season < 1) throw new Error("请选择有效季度");
        const response = await api("/api/tracking", { method: "POST", body: JSON.stringify({ ...identity(item), season_number: season, provider: dialog.querySelector("#trackingProvider").value, save_target: "cloud", backfill_existing: false }) });
        await onSubmitted();
        return { ...response, message: "已加入智能追更" };
      });
      if (result) button.disabled = true;
    };
  } catch (error) { output.textContent = error.message; }
}
