import "./preview.css";
import "./next.css";

const state = {
  user: "",
  config: null,
  route: "discover",
  theme: localStorage.getItem("mi-theme") || "light",
  material: localStorage.getItem("mi-material") || "soft",
  accent: localStorage.getItem("mi-accent") || "blue",
  corner: localStorage.getItem("mi-corner") || "default",
};

const NAV = [
  ["discover", "发现", "探索与搜索", "i-discover"],
  ["subscriptions", "订阅与追更", "愿望与补集", "i-tv"],
  ["workspace", "网盘工作台", "连接、规则与任务", "i-cloud"],
  ["cross-cloud", "跨盘转存", "夸克 → 115 补齐", "i-swap"],
  ["strm", "STRM 与 302", "媒体库播放", "i-play"],
  ["media-server", "媒体服务器", "Emby 数据看板", "i-video"],
];

const SYSTEM_NAV = [
  ["system", "全局设置", "服务与交互", "i-sliders"],
  ["guide", "使用手册", "完整使用说明", "i-book"],
];

const PAGE_META = {
  discover: ["资源入口", "发现"],
  subscriptions: ["持续追踪", "订阅与追更"],
  workspace: ["云端执行", "网盘工作台"],
  "cross-cloud": ["跨盘补齐", "跨盘转存"],
  strm: ["媒体播放", "STRM 与 302"],
  "media-server": ["Emby 看板", "媒体服务器"],
  system: ["系统服务", "全局设置"],
  guide: ["帮助中心", "使用手册"],
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 401) throw new Error("unauthorized");
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json()).detail || ""; } catch { /* ignore */ }
    throw new Error(typeof detail === "string" && detail ? detail : `请求失败 (${response.status})`);
  }
  return response.json();
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function applyAppearance() {
  const root = document.documentElement;
  root.dataset.theme = state.theme;
  root.dataset.material = state.material;
  root.dataset.accent = state.accent;
  root.dataset.corner = state.corner;
}

function posterUrl(item) {
  return item.poster_url || item.poster_path || "";
}

function backdropUrl(item) {
  return item.backdrop_url || item.backdrop_path || "";
}

function formatDate(value) {
  if (!value) return "";
  const text = String(value).replace("T", " ");
  return text.slice(0, 16);
}

function metaLine(item) {
  const parts = [];
  if (item.year) parts.push(item.year);
  const type = item.media_type === "movie" ? "电影" : item.media_type === "tv" ? "电视剧" : item.media_type || "";
  if (type) parts.push(type);
  if (item.vote_average) parts.push(`${Number(item.vote_average).toFixed(1)} 分`);
  return parts.join(" · ");
}

function shell(content) {
  const [context, label] = PAGE_META[state.route] || PAGE_META.discover;
  const navButton = ([page, title, hint, icon]) => `
    <button class="nav-item${page === state.route ? " active" : ""}" data-route="${page}" ${page === state.route ? 'aria-current="page"' : ""}>
      <svg class="ic"><use href="#${icon}"/></svg>
      <span class="label"><strong>${title}</strong><small>${hint}</small></span>
      <svg class="ic ic-sm go"><use href="#i-chev-r"/></svg>
    </button>`;
  return `
  <div class="app">
    <aside class="sidebar" id="sidebar">
      <button class="brand" data-route="discover">
        <svg class="brand-mark" viewBox="0 0 48 48" aria-hidden="true"><use href="#i-brand"/></svg>
        <span class="brand-text"><strong>MediaIndex</strong><small>给好故事，一个家</small></span>
      </button>
      <nav class="nav" aria-label="主导航">
        <span class="nav-label">工作区</span>
        ${NAV.map(navButton).join("")}
        <span class="nav-label">系统</span>
        ${SYSTEM_NAV.map(navButton).join("")}
      </nav>
      <div class="sidebar-spacer"></div>
      <div class="side-note">
        <div class="hint-row"><svg class="ic ic-sm"><use href="#i-search"/></svg><strong>快速检索</strong></div>
        在发现页按 <span class="kbd">/</span> 直接聚焦搜索框，支持电影、剧集与综艺。
      </div>
      <div class="side-foot">
        <div class="avatar">${esc((state.user || "?").slice(0, 1).toUpperCase())}</div>
        <div class="who"><strong>${esc(state.user)}</strong><small>本地工作区</small></div>
        <a class="icon-btn" href="https://github.com/xudong7587/media-index" target="_blank" rel="noreferrer" title="打开 GitHub 仓库"><svg class="ic ic-sm ic-fill"><use href="#i-github"/></svg></a>
        <button class="icon-btn" data-theme-toggle title="切换深浅"><svg class="ic ic-sm"><use href="#i-moon"/></svg></button>
      </div>
      <small class="version" id="version">MediaIndex</small>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <div class="crumb"><span>${context}</span><svg class="ic"><use href="#i-chev-r"/></svg><strong>${label}</strong></div>
        <div class="top-actions">
          <span class="status-chip"><i></i>本地服务运行中</span>
          <button class="chip" data-theme-toggle><svg class="ic ic-sm"><use href="#i-moon"/></svg>外观</button>
          <button class="icon-btn" title="通知"><svg class="ic ic-sm"><use href="#i-bell"/></svg></button>
        </div>
      </header>
      <main class="content" id="content">${content}</main>
    </div>
  </div>`;
}

function loginView(message = "") {
  return `
  <div class="login-shell">
    <form class="login-card" id="loginForm">
      <svg class="brand-mark" viewBox="0 0 48 48" aria-hidden="true"><use href="#i-brand"/></svg>
      <h1>Media Index</h1>
      <p>登录你的 NAS 媒体自动化控制台。</p>
      ${message ? `<div class="login-error">${esc(message)}</div>` : ""}
      <label>用户名<input name="username" autocomplete="username" required /></label>
      <label>密码<input name="password" type="password" autocomplete="current-password" required /></label>
      <button type="submit" class="primary">登录</button>
    </form>
  </div>`;
}

function discoverView() {
  return `
  <div class="mi-page discover-page" id="discoverPage">
    <div class="page-head">
      <div>
        <p class="eyebrow">DISCOVER · 资源入口</p>
        <h1>发现</h1>
        <p class="sub">从 TMDB 挑选想看的作品，核对信息后交给已启用的网盘执行转存。</p>
      </div>
      <form class="search" id="searchForm">
        <svg class="ic"><use href="#i-search"/></svg>
        <input id="searchInput" placeholder="搜索电影、剧集、综艺…" aria-label="搜索" />
        <span class="kbd">/</span>
        <button type="submit" class="icon-btn"><svg class="ic ic-sm"><use href="#i-chev-r"/></svg></button>
      </form>
    </div>
    <div class="chip-row" id="discoverChips"></div>
    <div id="discoverBody"><div class="loading-block">正在读取 TMDB 内容…</div></div>
  </div>`;
}

function placeholderView(title, eyebrow, sub) {
  return `
  <div class="mi-page">
    <div class="page-head"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="sub">${sub}</p></div></div>
    <div class="panel panel-pad"><div class="empty-state"><b>该页面正在迁移</b><span>外壳、导航与外观已接入后端；内容区按页面逐个接入真实数据。</span></div></div>
  </div>`;
}

const PLACEHOLDERS = {
  subscriptions: ["订阅与追更", "SUBSCRIPTIONS · 持续追踪", "按周巡检已播集数，发现缺集就自动检索补集；愿望单只登记想看的作品。"],
  workspace: ["网盘工作台", "CLOUD WORKSPACE · 云端执行", "连接网盘、接入资源来源、维护转存规则，最后都在任务中心收口。"],
  "cross-cloud": ["跨盘转存", "CROSS CLOUD · 跨盘补齐", "这是补偿链路：两盘各自完成发现与转存，需要时再从夸克定向补齐 115。"],
  strm: ["STRM 与 302", "STRM · MEDIA PLAYBACK", "把网盘里的文件映射成 Emby 可播放的 STRM，并用 302 直连播放。"],
  "media-server": ["媒体服务器", "EMBY · 媒体服务器", "Emby 的连接、媒体库规模、播放会话与最近入库都在这里。"],
  system: ["全局设置", "SYSTEM · 系统服务", "服务连接、通知渠道与安全选项都收在这里；改动按页保存。"],
  guide: ["使用手册", "GUIDE · 帮助中心", "按“你现在要完成什么”来查，而不是按功能列表翻。"],
};

/* ---------- discover ---------- */

const discoverState = { mediaType: "movie", region: "", groups: [], tracking: [], wishlist: [], featureIndex: 0, timer: null };

const MEDIA_TYPES = [["movie", "电影"], ["tv", "电视剧"], ["variety", "综艺"], ["concert", "演唱会"], ["documentary", "纪录片"], ["anime", "动漫"]];
const REGIONS = [["", "全部地区"], ["cn", "华语"]];

function renderChips() {
  const chips = document.getElementById("discoverChips");
  if (!chips) return;
  chips.innerHTML = [
    ...MEDIA_TYPES.map(([key, label]) => `<button class="chip${discoverState.mediaType === key ? " active" : ""}" data-media="${key}">${label}</button>`),
    `<span class="chip-sep"></span>`,
    ...REGIONS.map(([key, label]) => `<button class="chip${discoverState.region === key ? " active" : ""}" data-region="${key}">${label}</button>`),
  ].join("");
  chips.querySelectorAll("[data-media]").forEach((button) => button.addEventListener("click", () => {
    discoverState.mediaType = button.dataset.media;
    void loadDiscover();
  }));
  chips.querySelectorAll("[data-region]").forEach((button) => button.addEventListener("click", () => {
    discoverState.region = button.dataset.region;
    void loadDiscover();
  }));
}

function railSection(title, subtitle, items, key) {
  if (!items.length) return "";
  return `
  <section class="discover-rail" data-rail="${key}">
    <header><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div></header>
    <div class="rail-track" data-track="${key}">
      ${items.map((item) => `
        <button class="rail-card" data-media-type="${esc(item.media_type)}" data-tmdb="${esc(item.tmdb_id)}">
          <span class="poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span>
          <strong>${esc(item.title)}</strong>
          <span>${esc(metaLine(item))}</span>
        </button>`).join("")}
    </div>
  </section>`;
}

function sideRail() {
  const active = discoverState.tracking.filter((task) => task.status !== "archived");
  const pending = active.reduce((sum, task) => sum + Math.max(0, (task.episode_count || 0) - (task.saved_count || 0)), 0);
  const review = active.filter((task) => task.decision_state === "pending" || task.status === "needs_review").length;
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return `
  <aside class="discover-side">
    <section class="discover-side-card">
      <header><div><h2>追更看板</h2><p>按巡检周期自动核对集数</p></div><span class="discover-side-pill">${active.length} 部在追</span></header>
      <div class="discover-side-list">
        ${active.slice(0, 3).map((task) => {
          const total = task.episode_count || 0;
          const saved = task.saved_count || 0;
          const percent = total ? Math.min(100, Math.round((saved / total) * 100)) : 0;
          return `<button class="discover-side-item" data-route="subscriptions">
            ${posterUrl(task) ? `<img src="${esc(posterUrl(task))}" alt="" loading="lazy" />` : `<span class="discover-side-thumb"></span>`}
            <span class="discover-side-copy">
              <strong>${esc(task.title)}</strong>
              <small>S${String(task.season_number || 1).padStart(2, "0")} · ${saved} / ${total || "?"}${task.next_check_at ? ` · 下次 ${esc(formatDate(task.next_check_at).slice(5))}` : ""}</small>
              <i><b style="width:${percent}%"></b></i>
            </span>
          </button>`;
        }).join("") || `<p class="discover-side-empty">还没有追更任务，去订阅页添加。</p>`}
      </div>
      <footer><span>共 ${active.length} 部</span><button data-route="subscriptions">查看全部 →</button></footer>
    </section>
    <section class="discover-side-card">
      <header><div><h2>今日概览</h2><p>本地时间 ${now}</p></div></header>
      <div class="discover-side-stats">
        <div><strong>${pending}</strong><span>待补集数</span></div>
        <div><strong>${active.length}</strong><span>在追作品</span></div>
        <div><strong>${review}</strong><span>待确认</span></div>
      </div>
    </section>
  </aside>`;
}

function renderDiscover() {
  const body = document.getElementById("discoverBody");
  if (!body) return;
  const groups = discoverState.groups;
  const features = [];
  for (const group of groups) {
    for (const item of group.items) {
      if (item.backdrop_url && !features.some((entry) => entry.tmdb_id === item.tmdb_id && entry.media_type === item.media_type)) features.push(item);
      if (features.length >= 7) break;
    }
    if (features.length >= 7) break;
  }
  const featured = features[discoverState.featureIndex % Math.max(1, features.length)];
  body.innerHTML = `
  <div class="hero-row">
    ${featured ? `
    <section class="hero" id="hero">
      <div class="hero-slide is-active">
        <div class="hero-art" style="${backdropUrl(featured) ? `background-image:url(${esc(backdropUrl(featured))})` : ""}"></div>
      </div>
      <div class="hero-copy">
        <span class="hero-eyebrow">MEDIA DISCOVERY</span>
        <h2>${esc(featured.title)}</h2>
        <div class="hero-meta">
          <span><svg class="ic"><use href="#i-star"/></svg>${featured.vote_average ? Number(featured.vote_average).toFixed(1) : "待评分"}</span>
          <span>${esc(featured.year || "")}</span>
          <span>${featured.media_type === "movie" ? "电影" : "电视剧"}</span>
        </div>
        <p>${esc(featured.overview || "从推荐内容中选择作品，进入详情核对 TMDB 信息并发起资源任务。")}</p>
        <div class="hero-actions"><button class="btn primary" data-detail="${esc(featured.media_type)}:${esc(featured.tmdb_id)}">查看作品<svg class="ic"><use href="#i-arrow"/></svg></button></div>
      </div>
      <div class="hero-controls">
        <button class="rail-nav" data-hero="-1" aria-label="上一张"><svg class="ic"><use href="#i-chev-l"/></svg></button>
        <span class="hero-index">${String(discoverState.featureIndex + 1).padStart(2, "0")} / ${String(Math.max(1, features.length)).padStart(2, "0")}</span>
        <button class="rail-nav" data-hero="1" aria-label="下一张"><svg class="ic"><use href="#i-chev-r"/></svg></button>
      </div>
    </section>` : `<section class="hero"><div class="hero-copy"><h2>暂无推荐内容</h2><p>请先在全局设置中配置 TMDB API Key。</p></div></section>`}
    ${sideRail()}
  </div>
  ${railSection("正在热播", "近期最受关注的电影与节目", groups.find((group) => group.key === "hot")?.items || [], "hot")}
  ${railSection("口碑精选", "按 TMDB 评分发现值得看的作品", groups.find((group) => group.key === "rating")?.items || [], "rating")}
  ${railSection("最近上线", "浏览最近上映和更新的内容", groups.find((group) => group.key === "latest")?.items || [], "latest")}
  `;
  bindDiscover();
  startHeroTimer(features.length);
}

function bindDiscover() {
  document.querySelectorAll("[data-detail]").forEach((button) => button.addEventListener("click", () => {
    const [type, tmdb] = button.dataset.detail.split(":");
    void openDetail(type, Number(tmdb));
  }));
  document.querySelectorAll("[data-hero]").forEach((button) => button.addEventListener("click", () => {
    discoverState.featureIndex += Number(button.dataset.hero);
    renderDiscover();
  }));
  document.querySelectorAll("[data-track]").forEach((track) => {
    const key = track.dataset.track;
    const prev = document.querySelector(`[data-rail="${key}"] [data-rail-dir="-1"]`);
    const next = document.querySelector(`[data-rail="${key}"] [data-rail-dir="1"]`);
    if (prev) prev.addEventListener("click", () => track.scrollBy({ left: -480, behavior: "smooth" }));
    if (next) next.addEventListener("click", () => track.scrollBy({ left: 480, behavior: "smooth" }));
  });
}

function startHeroTimer(count) {
  window.clearInterval(discoverState.timer);
  if (count < 2) return;
  discoverState.timer = window.setInterval(() => {
    if (document.hidden) return;
    discoverState.featureIndex = (discoverState.featureIndex + 1) % count;
    renderDiscover();
  }, 7000);
}

async function loadDiscover() {
  renderChips();
  const body = document.getElementById("discoverBody");
  if (body) body.innerHTML = `<div class="loading-block">正在读取 TMDB 内容…</div>`;
  const [hot, rating, latest, tracking, wishlist] = await Promise.all([
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=hot&genre=&vote_min=0&page=1&page_size=14&refresh=false&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=rating&genre=&vote_min=0&page=1&page_size=14&refresh=false&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=latest&genre=&vote_min=0&page=1&page_size=14&refresh=false&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api("/api/tracking").catch(() => []),
    api("/api/wishlist").catch(() => []),
  ]);
  discoverState.groups = [
    { key: "hot", items: hot.results || [] },
    { key: "rating", items: rating.results || [] },
    { key: "latest", items: latest.results || [] },
  ];
  discoverState.tracking = Array.isArray(tracking) ? tracking : [];
  discoverState.wishlist = Array.isArray(wishlist) ? wishlist : [];
  discoverState.featureIndex = 0;
  renderDiscover();
}

async function openDetail(mediaType, tmdbId) {
  try {
    const item = await api(`/api/media/${mediaType}/${tmdbId}`);
    const dialog = document.createElement("dialog");
    dialog.className = "detail";
    dialog.innerHTML = `
      <div class="detail-top" style="${backdropUrl(item) ? `background-image:url(${esc(backdropUrl(item))})` : ""}">
        <button class="detail-close" data-close aria-label="关闭"><svg class="ic"><use href="#i-close"/></svg></button>
        <div class="detail-head">
          <span class="poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span>
          <div>
            <p class="eyebrow">TMDB COLLECTION</p>
            <h2>${esc(item.title)}</h2>
            <div class="detail-meta">
              <span>${item.vote_average ? Number(item.vote_average).toFixed(1) : "待评分"}</span>
              <span>${esc(item.year || "")}</span>
              <span>${item.media_type === "movie" ? "电影" : "电视剧"}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="detail-body"><p>${esc(item.overview || "暂无简介。")}</p></div>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove());
    dialog.showModal();
  } catch (error) {
    console.error(error);
  }
}

/* ---------- subscriptions ---------- */

const subsState = { tab: "tracking", provider: "", tasks: [], wishlist: [], review: [], episodes: {}, panels: {}, busy: "", error: "" };

const providerName = (p) => (p === "p115" ? "115" : p === "quark" ? "夸克" : p === "qas" ? "QAS" : p);
const mediaTypeText = (t) => (t === "movie" ? "电影" : t === "tv" ? "电视剧" : t || "作品");

function pillFor(status) {
  const map = { active: ["ok", "追更中"], paused: ["muted", "已暂停"], archived: ["muted", "已归档"], needs_review: ["warn", "待确认"], failed: ["danger", "失败"] };
  const [kind, label] = map[status] || ["muted", status || "未启用"];
  return `<span class="pill ${kind}"><i></i>${label}</span>`;
}

function subsPageView() {
  return `
  <div class="mi-page" id="subsPage">
    <div class="page-head">
      <div><p class="eyebrow">SUBSCRIPTIONS · 持续追踪</p><h1>订阅与追更</h1><p class="sub">按周巡检已播集数，发现缺集就自动检索补集；愿望单只登记想看的作品。</p></div>
      <div class="page-actions"><button class="btn ghost sm" data-subs-refresh><svg class="ic"><use href="#i-refresh"/></svg>刷新</button></div>
    </div>
    <div class="stat-strip" id="subsStats"></div>
    <div class="chip-row" id="subsChips"></div>
    <div class="split split-side" id="subsSplit"><section class="panel panel-pad" id="subsMain"></section><aside class="panel panel-pad" id="subsRail"></aside></div>
  </div>`;
}

function renderSubsStats() {
  const node = document.getElementById("subsStats");
  if (!node) return;
  const active = subsState.tasks.filter((task) => task.status === "active");
  const pending = subsState.review.length;
  const totalEpisodes = active.reduce((sum, task) => sum + (task.episode_count || 0), 0);
  const savedEpisodes = active.reduce((sum, task) => sum + (task.saved_count || 0), 0);
  const rate = totalEpisodes ? Math.round((savedEpisodes / totalEpisodes) * 100) : 100;
  node.innerHTML = `
    <div class="panel stat-tile"><span>追更中</span><b>${active.length}<em>部</em></b><small>共 ${subsState.tasks.length} 个任务</small></div>
    <div class="panel stat-tile"><span>待确认</span><b>${pending}<em>条</em></b><small>匹配置信度不足</small></div>
    <div class="panel stat-tile"><span>愿望单</span><b>${subsState.wishlist.length}<em>部</em></b><small>等资源上线</small></div>
    <div class="panel stat-tile"><span>巡检成功率</span><b>${rate}<em>%</em></b><small>${savedEpisodes} / ${totalEpisodes} 集已确认</small></div>`;
}

function renderSubsChips() {
  const node = document.getElementById("subsChips");
  if (!node) return;
  const providers = [...new Set(subsState.tasks.flatMap((task) => (task.provider_states || []).map((state) => state.provider)))];
  node.innerHTML = `
    ${[["tracking", "智能追更"], ["wishlist", "愿望单"], ["review", "待确认"]].map(([key, label]) => `<button class="chip${subsState.tab === key ? " active" : ""}" data-subs-tab="${key}">${label}</button>`).join("")}
    <span class="divider"></span>
    <button class="chip mini${subsState.provider === "" ? " active" : ""}" data-subs-provider="">全部网盘</button>
    ${providers.map((provider) => `<button class="chip mini${subsState.provider === provider ? " active" : ""}" data-subs-provider="${esc(provider)}">${providerName(provider)}</button>`).join("")}`;
}

function subsRail() {
  const config = state.config || {};
  return `
  <div class="panel-head"><div><h2>巡检设置</h2><small>对所有追更任务生效</small></div></div>
  <div class="form-grid" style="grid-template-columns:1fr 1fr">
    <div class="field"><label>巡检周期（分钟）</label><input class="input" id="subsPoll" type="number" min="1" value="${esc(config.tracking_poll_minutes ?? 30)}" /></div>
    <div class="field"><label>默认追更时间</label><input class="input" id="subsTime" type="time" value="${esc(config.tracking_check_time ?? "20:00")}" /></div>
    <div class="field"><label>失败重试间隔（分钟）</label><input class="input" id="subsRetry" type="number" min="1" value="${esc(config.tracking_retry_interval_minutes ?? 120)}" /></div>
    <div class="field"><label>最大重试次数</label><input class="input" id="subsMax" type="number" min="1" value="${esc(config.tracking_max_retries ?? 5)}" /></div>
  </div>
  <button class="btn primary sm" data-subs-save-settings style="margin-top:10px"><svg class="ic"><use href="#i-download"/></svg>保存巡检设置</button>
  <p class="muted-note">追更时间按本地时区解释；重试间隔用于失败后再次巡检。</p>`;
}

function wishlistPill(status) {
  const map = { pending: ["muted", "等待资源"], retry_wait: ["warn", "重试等待"], found: ["ok", "已找到"], downloading: ["ok", "下载中"], failed: ["danger", "失败"], archived: ["muted", "已归档"] };
  const [kind, label] = map[status] || ["muted", "等待资源"];
  return `<span class="pill ${kind}"><i></i>${label}</span>`;
}

function taskCard(task) {
  const states = (task.provider_states || []).filter((entry) => entry.status !== "disabled");
  const statesForFilter = subsState.provider ? (task.provider_states || []).filter((entry) => entry.provider === subsState.provider) : states;
  if (subsState.provider && !statesForFilter.length) return "";
  const total = task.episode_count || Math.max(0, ...(task.provider_states || []).map((entry) => entry.episode_count || 0));
  const saved = task.saved_count || Math.max(0, ...(task.provider_states || []).map((entry) => entry.saved_count || 0));
  const percent = total ? Math.min(100, Math.round((saved / total) * 100)) : 0;
  const drives = statesForFilter.map((entry) => {
    const open = Boolean(subsState.panels[entry.id]);
    return `
    <div class="drive">
      <label><input type="checkbox" ${entry.status === "active" ? "checked" : ""} data-provider-toggle="${esc(entry.provider)}" data-task="${task.id}" /><b>${providerName(entry.provider)}</b></label>
      <small>已确认 ${entry.saved_count || 0} 集</small>
      ${pillFor(entry.status)}
      <button class="drive-caret" data-episodes="${entry.id}" data-task="${task.id}" aria-expanded="${open}"><svg class="ic"><use href="#i-chev-d"/></svg></button>
    </div>
    ${open ? episodesPanel(task, entry) : ""}`;
  }).join("");
  return `
  <article class="task-card" data-task-card="${task.id}">
    <div class="task-head">
      <span class="thumb" style="${posterUrl(task) ? `background-image:url(${esc(posterUrl(task))})` : ""}"></span>
      <div class="task-title">
        <div><b>${esc(task.title)}</b>${pillFor(task.status)}</div>
        <small>${mediaTypeText(task.media_type)} · ${esc(task.year || "")}${task.overview ? ` · ${esc(task.overview)}` : ""}</small>
      </div>
      <div class="task-progress"><span>S${String(task.season_number || 1).padStart(2, "0")} 共 ${total || "?"} 集</span><div class="progress-line"><span class="progress"><i style="width:${percent}%"></i></span><span>${saved} / ${total || "?"}</span></div></div>
    </div>
    <div class="task-drives">
      ${drives || `<span class="muted-note">未启用网盘，勾选后开始追更。</span>`}
      <div class="task-path"><label>保存路径</label><input class="input" value="${esc(task.save_path || (states[0] && states[0].save_path) || "")}" data-path-input="${task.id}" /><button class="mini-btn" data-save-path="${task.id}">保存</button></div>
    </div>
    <div class="task-actions">
      <div class="ctrl"><label>追更时间</label><input class="input" type="time" value="${esc(task.check_time || "20:00")}" data-time-input="${task.id}" /><button class="mini-btn" data-save-time="${task.id}">保存</button></div>
      <span class="task-next">${task.next_check_at ? `下次巡检 ${esc(formatDate(task.next_check_at))}` : "等待排期"}</span>
      <div class="row-actions">
        <button class="mini-btn primary" data-run="${task.id}">执行</button>
        <button class="mini-btn" data-toggle="${task.id}" data-status="${esc(task.status)}">${task.status === "active" ? "暂停" : "恢复"}</button>
        <button class="mini-btn" data-refresh-storage="${task.id}">刷新已存</button>
        <button class="mini-btn danger" data-delete="${task.id}">移除</button>
      </div>
    </div>
  </article>`;
}

function episodesPanel(task, entry) {
  const data = subsState.episodes[entry.id];
  const head = `<div class="ep-head"><b>${providerName(entry.provider)} · ${esc(task.title)}</b><span>已存 ${entry.saved_count || 0} 集</span></div>`;
  if (!data) return `<div class="drive-episodes"><div class="ep-head"><b>${providerName(entry.provider)} · ${esc(task.title)}</b><span>正在读取分集…</span></div></div>`;
  const episodes = data.episodes || [];
  if (!episodes.length) return `<div class="drive-episodes">${head}<div class="empty-state" style="padding:14px 8px"><b>没有分集数据</b><span>先刷新已存或等待巡检。</span></div></div>`;
  return `<div class="drive-episodes">${head}<div class="ep-grid">${episodes.map((episode) => `<span class="ep ${episode.status === "saved" ? "saved" : episode.aired ? "missing" : ""}" title="${esc(episode.title || "")} ${esc(episode.air_date || "")}">E${String(episode.episode_number).padStart(2, "0")}</span>`).join("")}</div></div>`;
}

function wishlistRows() {
  if (!subsState.wishlist.length) return `<div class="empty-state"><b>愿望单是空的</b><span>在发现页点“加入智能追更”就会出现在这里。</span></div>`;
  return subsState.wishlist.map((item) => `
    <article class="task-card">
      <div class="task-head">
        <span class="thumb" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span>
        <div class="task-title"><div><b>${esc(item.title)}</b>${wishlistPill(item.status)}</div><small>${mediaTypeText(item.media_type)} · ${esc(item.year || "")}${item.season_number ? ` · S${item.season_number}` : ""} · ${providerName(item.provider)}</small></div>
        <div class="task-progress"><span>${item.next_check_at ? `下次检查 ${esc(formatDate(item.next_check_at))}` : "等待排期"}</span></div>
      </div>
      <div class="task-actions"><span class="task-next">${esc(item.overview || "")}</span><div class="row-actions"><button class="mini-btn primary" data-wish-run="${item.id}">立即检查</button><button class="mini-btn danger" data-wish-delete="${item.id}">删除</button></div></div>
    </article>`).join("");
}

function reviewRows() {
  if (!subsState.review.length) return `<div class="empty-state"><b>没有待确认的资源</b><span>匹配不确定的候选会先停在这里。</span></div>`;
  return subsState.review.map((item) => `
    <article class="task-card">
      <div class="task-head">
        <span class="thumb"></span>
        <div class="task-title"><div><b>${esc(item.title || item.resource_title || "待确认资源")}</b><span class="pill warn"><i></i>待确认</span></div><small>${esc(item.message || item.reason || "匹配置信度不足，需要人工确认。")}</small></div>
        <div class="task-progress"><span>${esc(item.stage || "")}</span></div>
      </div>
      <div class="task-actions"><div class="row-actions"><button class="mini-btn primary" data-review-confirm="${item.id}">确认入库</button><button class="mini-btn danger" data-review-delete="${item.id}">忽略</button></div></div>
    </article>`).join("");
}

function renderSubsBody() {
  renderSubsStats();
  renderSubsChips();
  const main = document.getElementById("subsMain");
  const rail = document.getElementById("subsRail");
  if (!main || !rail) return;
  rail.innerHTML = subsRail();
  if (subsState.tab === "wishlist") {
    main.innerHTML = `<div class="panel-head"><div><h2>愿望单</h2><small>暂未找到资源的作品，找到后会转入追更</small></div></div><div class="task-list">${wishlistRows()}</div>`;
  } else if (subsState.tab === "review") {
    main.innerHTML = `<div class="panel-head"><div><h2>待确认</h2><small>匹配不确定的候选，确认后直接入库</small></div></div><div class="task-list">${reviewRows()}</div>`;
  } else {
    const cards = subsState.tasks.map(taskCard).filter(Boolean).join("");
    main.innerHTML = `<div class="panel-head"><div><h2>追更任务</h2><small>每部作品单独设置追更时间、保存路径与启用网盘</small></div><div class="row-actions"><button class="mini-btn" data-subs-refresh>刷新</button></div></div><div class="task-list">${cards || `<div class="empty-state"><b>还没有追更任务</b><span>在发现页对作品点“加入智能追更”。</span></div>`}</div>`;
  }
  bindSubs();
}

async function loadSubs() {
  const main = document.getElementById("subsMain");
  if (main) main.innerHTML = `<div class="loading-block">正在读取追更任务…</div>`;
  const [tasks, wishlist, review] = await Promise.all([
    api("/api/tracking").catch(() => []),
    api("/api/wishlist").catch(() => []),
    api("/api/review").catch(() => []),
  ]);
  subsState.tasks = Array.isArray(tasks) ? tasks : [];
  subsState.wishlist = Array.isArray(wishlist) ? wishlist : [];
  subsState.review = Array.isArray(review) ? review : [];
  renderSubsBody();
}

async function runSubsAction(label, work) {
  if (subsState.busy) return;
  subsState.busy = label;
  try { await work(); } catch (error) { subsState.error = error.message || String(error); } finally { subsState.busy = ""; await loadSubs(); }
}

function bindSubs() {
  document.querySelectorAll("[data-subs-tab]").forEach((button) => button.addEventListener("click", () => { subsState.tab = button.dataset.subsTab; renderSubsBody(); }));
  document.querySelectorAll("[data-subs-provider]").forEach((button) => button.addEventListener("click", () => { subsState.provider = button.dataset.subsProvider; renderSubsBody(); }));
  document.querySelectorAll("[data-subs-refresh]").forEach((button) => button.addEventListener("click", () => void loadSubs()));
  document.querySelector("[data-subs-save-settings]")?.addEventListener("click", () => void runSubsAction("settings", async () => {
    await api("/api/config", { method: "PUT", body: JSON.stringify({
      tracking_poll_minutes: Number(document.getElementById("subsPoll")?.value || 30),
      tracking_check_time: document.getElementById("subsTime")?.value || "20:00",
      tracking_retry_interval_minutes: Number(document.getElementById("subsRetry")?.value || 120),
      tracking_max_retries: Number(document.getElementById("subsMax")?.value || 5),
    }) });
  }));
  document.querySelectorAll("[data-episodes]").forEach((button) => button.addEventListener("click", async () => {
    const id = Number(button.dataset.episodes);
    subsState.panels[id] = !subsState.panels[id];
    if (subsState.panels[id] && !subsState.episodes[id]) {
      try { subsState.episodes[id] = await api(`/api/tracking/${button.dataset.task}/episodes`); } catch { subsState.episodes[id] = { episodes: [] }; }
    }
    renderSubsBody();
  }));
  document.querySelectorAll("[data-run]").forEach((button) => button.addEventListener("click", () => void runSubsAction("run", () => api(`/api/tracking/${button.dataset.run}/run`, { method: "POST" }))));
  document.querySelectorAll("[data-toggle]").forEach((button) => button.addEventListener("click", () => void runSubsAction("toggle", () => api(`/api/tracking/${button.dataset.toggle}/${button.dataset.status === "active" ? "pause" : "resume"}`, { method: "POST" }))));
  document.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => { if (confirm("移除这个追更任务？")) void runSubsAction("delete", () => api(`/api/tracking/${button.dataset.delete}`, { method: "DELETE" })); }));
  document.querySelectorAll("[data-refresh-storage]").forEach((button) => button.addEventListener("click", () => void runSubsAction("refresh", () => api(`/api/tracking/${button.dataset.refreshStorage}/refresh-storage`, { method: "POST" }))));
  document.querySelectorAll("[data-save-time]").forEach((button) => button.addEventListener("click", () => {
    const id = button.dataset.saveTime;
    const value = document.querySelector(`[data-time-input="${id}"]`)?.value || "20:00";
    void runSubsAction("time", () => api(`/api/tracking/${id}/schedule`, { method: "PATCH", body: JSON.stringify({ check_time: value }) }));
  }));
  document.querySelectorAll("[data-save-path]").forEach((button) => button.addEventListener("click", () => {
    const id = button.dataset.savePath;
    const value = document.querySelector(`[data-path-input="${id}"]`)?.value || "";
    void runSubsAction("path", () => api(`/api/tracking/${id}/save-path`, { method: "PATCH", body: JSON.stringify({ save_path: value }) }));
  }));
  document.querySelectorAll("[data-provider-toggle]").forEach((input) => input.addEventListener("change", () => {
    const taskId = input.dataset.task;
    void runSubsAction("provider", () => api(`/api/tracking/${taskId}/provider`, { method: "PATCH", body: JSON.stringify({ provider: input.dataset.providerToggle, enabled: input.checked }) }));
  }));
  document.querySelectorAll("[data-wish-run]").forEach((button) => button.addEventListener("click", () => void runSubsAction("wish-run", () => api(`/api/wishlist/${button.dataset.wishRun}/run`, { method: "POST" }))));
  document.querySelectorAll("[data-wish-delete]").forEach((button) => button.addEventListener("click", () => void runSubsAction("wish-delete", () => api(`/api/wishlist/${button.dataset.wishDelete}`, { method: "DELETE" }))));
  document.querySelectorAll("[data-review-confirm]").forEach((button) => button.addEventListener("click", () => void runSubsAction("confirm", () => api(`/api/review/${button.dataset.reviewConfirm}/confirm`, { method: "POST", body: JSON.stringify({}) }))));
  document.querySelectorAll("[data-review-delete]").forEach((button) => button.addEventListener("click", () => void runSubsAction("review-delete", () => api(`/api/review/${button.dataset.reviewDelete}`, { method: "DELETE" }))));
}
/* ---------- router ---------- */

function routeFromHash() {
  const value = location.hash.replace(/^#/, "").split("/")[0];
  return PAGE_META[value] ? value : "discover";
}

async function render() {
  state.route = routeFromHash();
  const root = document.getElementById("root");
  if (state.route === "discover") {
    root.innerHTML = shell(discoverView());
    bindShell();
    await loadDiscover();
    return;
  }
  if (state.route === "subscriptions") {
    root.innerHTML = shell(subsPageView());
    bindShell();
    await loadSubs();
    return;
  }
  const [title, eyebrow, sub] = PLACEHOLDERS[state.route] || PLACEHOLDERS.discover;
  root.innerHTML = shell(placeholderView(title, eyebrow, sub));
  bindShell();
}

function bindShell() {
  document.querySelectorAll("[data-route]").forEach((element) => element.addEventListener("click", () => {
    const route = element.dataset.route;
    if (location.hash === `#${route}`) { void render(); return; }
    location.hash = route;
  }));
  document.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    localStorage.setItem("mi-theme", state.theme);
    applyAppearance();
  });
  const search = document.getElementById("searchForm");
  if (search) {
    search.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = document.getElementById("searchInput");
      const query = input?.value?.trim();
      if (!query) { void loadDiscover(); return; }
      const body = document.getElementById("discoverBody");
      if (body) body.innerHTML = `<div class="loading-block">正在搜索…</div>`;
      const result = await api(`/api/search?q=${encodeURIComponent(query)}&media_type=all`).catch(() => ({ results: [] }));
      const items = result.results || [];
      if (body) {
        body.innerHTML = `<section class="discover-rail"><header><div><h2>“${esc(query)}” 的搜索结果</h2><p>共 ${items.length} 条</p></div></header>
          <div class="rail-track">${items.map((item) => `<button class="rail-card" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}"><span class="poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span><strong>${esc(item.title)}</strong><span>${esc(metaLine(item))}</span></button>`).join("") || `<div class="empty-state"><b>没有结果</b><span>换个关键词试试。</span></div>`}</div></section>`;
        bindDiscover();
      }
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !(event.target instanceof HTMLInputElement)) {
      event.preventDefault();
      document.getElementById("searchInput")?.focus();
    }
  }, { once: true });
}

async function boot() {
  applyAppearance();
  try {
    const me = await api("/api/auth/me");
    state.user = me.user || "local";
    await render();
  } catch {
    document.getElementById("root").innerHTML = loginView();
    const form = document.getElementById("loginForm");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      try {
        await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: data.get("username"), password: data.get("password") }) });
        location.reload();
      } catch (error) {
        document.getElementById("root").innerHTML = loginView("用户名或密码不正确");
        location.hash = "";
      }
    });
  }
  window.addEventListener("hashchange", () => void render());
  renderVersion();
}

async function renderVersion() {
  try {
    const status = await api("/api/config/status");
    state.config = status;
    const node = document.getElementById("version");
    if (node) node.textContent = `MediaIndex v${status.version || ""} · 本地运行`;
  } catch { /* ignore */ }
}

boot();
