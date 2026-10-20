import "./preview.css";
import "./next.css";
import { GUIDE_HTML } from "./guide.js";
import { OVERVIEW_HTML } from "./overview.js";
import QRCode from "qrcode";

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
    <div class="menu-backdrop" data-menu-close></div>
    <div class="workspace">
      <header class="topbar">
        <button class="menu-btn" data-menu aria-label="打开菜单"><svg class="ic"><use href="#i-menu"/></svg></button>
        <div class="crumb"><span>${context}</span><svg class="ic"><use href="#i-chev-r"/></svg><strong>${label}</strong></div>
        <div class="top-actions">
          <span class="status-chip"><i></i>本地服务运行中</span>
          <div class="appearance-anchor">
            <button class="appearance-btn" id="btnAppearance" aria-expanded="false" aria-controls="appearancePop"><svg class="ic ic-sm"><use href="#i-sun"/></svg><span>外观</span></button>
            <div class="appearance-pop" id="appearancePop">${appearancePopHtml()}</div>
          </div>
          <button class="icon-btn" id="btnTasks" title="任务中心"><svg class="ic ic-sm"><use href="#i-activity"/></svg><span class="notice-badge" id="taskBadge" hidden></span></button>
          <div class="notice-anchor">
            <button class="icon-btn" id="btnNotice" aria-expanded="false" title="通知"><svg class="ic ic-sm"><use href="#i-bell"/></svg><span class="notice-badge" id="noticeBadge" hidden></span></button>
            <div class="notice-pop" id="noticePop"></div>
          </div>
        </div>
      </header>
      <main class="content" id="content">${content}</main>
    </div>
  </div>`;
}

const MATERIALS = [["default", "清晰默认"], ["paper", "纸页档案"], ["aurora", "极光玻璃"], ["soft", "柔软浮雕"], ["outline", "精致描边"], ["duotone", "双色渐层"], ["satin", "缎光瓷面"], ["glass", "iOS 玻璃"], ["linen", "亚麻织纹"], ["frosted", "雾面玻璃"], ["metal", "拉丝金属"], ["clay", "陶土哑光"], ["marble", "大理石纹"], ["neon", "霓虹夜行"], ["cutout", "剪纸拼贴"], ["mesh", "网格渐变"]];
const ACCENT_SWATCHES = [["blue", "晴蓝", "#376bd8"], ["green", "松绿", "#188466"], ["violet", "鸢紫", "#8855cc"], ["rose", "莓红", "#c34278"], ["amber", "琥珀", "#b27a16"], ["slate", "石墨", "#61758f"], ["celadon", "青瓷", "#2f7f76"], ["brick", "砖窑", "#a8433a"], ["mustard", "芥末", "#8f7a12"], ["indigo", "靛蓝", "#3b4fa8"], ["catppuccin", "奶霜花园", "#c14f7c"], ["nord", "北境极光", "#427fa4"], ["iris", "鸢尾暮色", "#7958c8"], ["coast", "海盐日落", "#14869a"], ["macaron", "马卡龙", "#329383"], ["peach", "蜜桃乌龙", "#c16648"], ["lavender", "蓝调花雾", "#467fb2"], ["forest", "雨后花园", "#3d895f"], ["honey", "蜂蜜麦田", "#a17a24"], ["ruby", "红茶玫瑰", "#c04757"], ["deepsea", "深海鎏金", "#1d6f8b"], ["lava", "暮色熔岩", "#b4465e"], ["cedar", "薄荷雪松", "#2e8b74"], ["mist", "海雾晨光", "#4f7fa8"], ["oasis", "沙漠绿洲", "#b07a2e"], ["nightviolet", "紫罗兰夜", "#6c4ab6"]];

function appearancePopHtml() {
  return `
  <div class="pop-head"><div><strong>外观</strong><small>${esc(appearanceLabel())}</small></div><button class="pop-close" data-appearance-close aria-label="关闭外观面板"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="pop-group"><span>明暗</span><div class="seg" data-group="theme">
    <button data-theme-value="light" aria-pressed="${state.theme !== "dark"}">浅色</button>
    <button data-theme-value="dark" aria-pressed="${state.theme === "dark"}">深色</button>
  </div></div>
  <div class="pop-group"><span>圆角</span><div class="seg" data-group="corner">
    ${[["tight", "紧致"], ["default", "标准"], ["round", "圆润"]].map(([value, label]) => `<button data-corner-value="${value}" aria-pressed="${state.corner === value}">${label}</button>`).join("")}
  </div></div>
  <div class="pop-group"><span>质感</span><div class="mat-grid">
    ${MATERIALS.map(([id, label]) => `<button class="mat-opt${state.material === id ? " active" : ""}" data-material-value="${id}" title="${label}">${label}</button>`).join("")}
  </div></div>
  <div class="pop-group"><span>配色</span><div class="color-row">
    ${ACCENT_SWATCHES.map(([id, label, color]) => `<button class="color-dot${state.accent === id ? " active" : ""}" data-accent-value="${id}" title="${label}" style="--dot:${color}" aria-label="${label}"></button>`).join("")}
  </div></div>`;
}

function appearanceLabel() {
  const material = MATERIALS.find(([id]) => id === state.material);
  const accent = ACCENT_SWATCHES.find(([id]) => id === state.accent);
  return `${material ? material[1] : "质感"} · ${accent ? accent[1] : "配色"}`;
}

async function refreshTaskBadge() {
  const badge = document.getElementById("taskBadge");
  if (!badge) return;
  const jobs = await api("/api/transfers").catch(() => []);
  const active = (Array.isArray(jobs) ? jobs : []).filter((job) => ["queued", "running", "retry_wait"].includes(job.status)).length;
  if (active > 0) { badge.hidden = false; badge.textContent = String(Math.min(99, active)); }
  else badge.hidden = true;
}
function bindNotice() {
  const button = document.getElementById("btnNotice");
  const pop = document.getElementById("noticePop");
  if (!button || !pop) return;
  void refreshNoticeBadge();
  button.addEventListener("click", async () => {
    const open = pop.classList.toggle("open");
    button.setAttribute("aria-expanded", String(open));
    if (!open) return;
    pop.innerHTML = `<div class="loading-block" style="padding:16px 8px">正在读取通知…</div>`;
    const feed = await api("/api/notifications").catch(() => ({ items: [], unread_count: 0 }));
    pop.innerHTML = noticePopHtml(feed);
    bindNoticeActions(feed);
  });
}

async function refreshNoticeBadge() {
  const feed = await api("/api/notifications").catch(() => ({ items: [], unread_count: 0 }));
  const badge = document.getElementById("noticeBadge");
  if (!badge) return;
  if (feed.unread_count > 0) { badge.hidden = false; badge.textContent = String(Math.min(99, feed.unread_count)); }
  else badge.hidden = true;
}

function noticePopHtml(feed) {
  const items = feed.items || [];
  return `
  <div class="pop-head"><div><strong>通知</strong><small>${feed.unread_count ? `${feed.unread_count} 条未读` : "全部已读"}</small></div><button class="pop-close" data-notice-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="notice-list">${items.length ? items.map((item) => `<a class="notice-row" href="#${esc(item.action_page || "discover")}"><span class="notice-icon ${esc(item.type)}"></span><span class="notice-copy"><b>${esc(item.title)}</b><small>${esc(item.message)}</small></span><time>${esc(formatDate(item.created_at))}</time></a>`).join("") : `<div class="empty-state" style="padding:18px 8px"><b>暂无通知</b><span>任务完成后会在这里提醒。</span></div>`}</div>
  <div class="pop-foot"><button class="link" data-notice-read>全部已读</button><button class="link" data-notice-clear>清空</button></div>`;
}

function bindNoticeActions(feed) {
  const pop = document.getElementById("noticePop");
  pop.querySelector("[data-notice-close]")?.addEventListener("click", () => pop.classList.remove("open"));
  pop.querySelector("[data-notice-read]")?.addEventListener("click", async () => {
    await api("/api/notifications/read", { method: "POST", body: JSON.stringify({}) }).catch(() => null);
    pop.classList.remove("open");
    void refreshNoticeBadge();
  });
  pop.querySelector("[data-notice-clear]")?.addEventListener("click", async () => {
    await api("/api/notifications", { method: "DELETE" }).catch(() => null);
    pop.classList.remove("open");
    void refreshNoticeBadge();
  });
  void feed;
}
function bindAppearance() {
  const trigger = document.getElementById("btnAppearance");
  const pop = document.getElementById("appearancePop");
  if (!trigger || !pop) return;
  trigger.addEventListener("click", () => {
    const open = pop.classList.toggle("open");
    trigger.setAttribute("aria-expanded", String(open));
  });
  document.querySelector("[data-appearance-close]")?.addEventListener("click", () => {
    pop.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
  });
  pop.querySelectorAll("[data-theme-value]").forEach((button) => button.addEventListener("click", () => {
    state.theme = button.dataset.themeValue;
    localStorage.setItem("mi-theme", state.theme);
    applyAppearance();
    refreshAppearancePop();
  }));
  pop.querySelectorAll("[data-corner-value]").forEach((button) => button.addEventListener("click", () => {
    state.corner = button.dataset.cornerValue;
    localStorage.setItem("mi-corner", state.corner);
    applyAppearance();
    refreshAppearancePop();
  }));
  pop.querySelectorAll("[data-material-value]").forEach((button) => button.addEventListener("click", () => {
    state.material = button.dataset.materialValue;
    localStorage.setItem("mi-material", state.material);
    applyAppearance();
    refreshAppearancePop();
  }));
  pop.querySelectorAll("[data-accent-value]").forEach((button) => button.addEventListener("click", () => {
    state.accent = button.dataset.accentValue;
    localStorage.setItem("mi-accent", state.accent);
    applyAppearance();
    refreshAppearancePop();
  }));
}

function refreshAppearancePop() {
  const pop = document.getElementById("appearancePop");
  if (!pop) return;
  pop.innerHTML = appearancePopHtml();
  bindAppearance();
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
      <button type="submit" class="btn primary">登录</button>
    </form>
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

const discoverState = {
  section: "explore",
  mediaType: "movie",
  region: "",
  kind: "all",
  platform: "netflix",
  groups: [],
  rankings: [],
  tracking: [],
  wishlist: [],
  featureIndex: 0,
  timer: null,
  download: { options: [], link: "", title: "", year: "", category: "movie", busy: false, message: "" },
};

const MEDIA_TYPES = [["movie", "电影"], ["tv", "电视剧"], ["variety", "综艺"], ["concert", "演唱会"], ["documentary", "纪录片"], ["anime", "动漫"]];
const REGIONS = [["", "全部地区"], ["cn", "华语"]];
const RANK_PLATFORMS = [
  ["douban", "豆瓣高分", "豆", ""],
  ["netflix", "Netflix", "N", "8"],
  ["max", "HBO Max", "H", "1899"],
  ["apple", "Apple TV+", "A", "350"],
  ["disney", "Disney+", "D+", "337"],
  ["prime", "Prime Video", "P", "119"],
  ["amazon", "Amazon", "a", "10"],
  ["hulu", "Hulu", "h", "15"],
];
const RANK_REGIONS = [["US", "美国"], ["CN", "中国大陆"], ["HK", "中国香港"], ["TW", "中国台湾"], ["JP", "日本"], ["KR", "韩国"], ["GB", "英国"]];

function discoverView() {
  return `
  <div class="mi-page discover-page" id="discoverPage">
    <div class="page-head">
      <div><p class="eyebrow">DISCOVER · 资源入口</p><h1>发现</h1><p class="sub">从 TMDB 挑选想看的作品，核对信息后交给已启用的网盘执行转存。</p></div>
      <form class="search" id="searchForm">
        <svg class="ic"><use href="#i-search"/></svg>
        <input id="searchInput" placeholder="搜索电影、剧集、综艺…" aria-label="搜索" />
        <span class="kbd">/</span>
        <button type="submit" class="icon-btn"><svg class="ic ic-sm"><use href="#i-arrow"/></svg></button>
      </form>
    </div>
    <div class="chip-row" id="discoverSectionChips">
      ${[["explore", "影视探索"], ["download", "链接下载"]].map(([key, label]) => `<button class="chip${discoverState.section === key ? " active" : ""}" data-discover-section="${key}">${label}</button>`).join("")}
    </div>
    <div id="discoverFilters"></div>
    <div id="discoverBody"><div class="loading-block">正在读取 TMDB 内容…</div></div>
  </div>`;
}

function renderDiscoverFilters() {
  const node = document.getElementById("discoverFilters");
  if (!node) return;
  if (discoverState.section === "download") { node.innerHTML = ""; return; }
  if (discoverState.section === "rankings") {
    node.innerHTML = `<div class="chip-row">
      ${RANK_PLATFORMS.map(([key, label, mark]) => `<button class="chip platform-chip${discoverState.platform === key ? " active" : ""}" data-platform="${key}"><i>${mark}</i>${label}</button>`).join("")}
    </div>
    <div class="chip-row">
      ${[["all", "全部"], ["movie", "电影"], ["tv", "剧集"]].map(([key, label]) => `<button class="chip mini${discoverState.kind === key ? " active" : ""}" data-rank-kind="${key}">${label}</button>`).join("")}
      <span class="divider"></span>
      ${RANK_REGIONS.map(([key, label]) => `<button class="chip mini${discoverState.region === key.toLowerCase() || (discoverState.region === "" && key === "US") ? " active" : ""}" data-rank-region="${key}">${label}</button>`).join("")}
    </div>`;
    bindDiscoverFilters();
    return;
  }
  node.innerHTML = `<div class="chip-row">
    ${MEDIA_TYPES.map(([key, label]) => `<button class="chip${discoverState.mediaType === key ? " active" : ""}" data-media="${key}">${label}</button>`).join("")}
    <span class="divider"></span>
    ${REGIONS.map(([key, label]) => `<button class="chip${discoverState.region === key ? " active" : ""}" data-region="${key}">${label}</button>`).join("")}
  </div>`;
  bindDiscoverFilters();
}

function bindDiscoverFilters() {
  document.querySelectorAll("[data-media]").forEach((button) => button.addEventListener("click", () => { discoverState.mediaType = button.dataset.media; void loadDiscover(); }));
  document.querySelectorAll("[data-region]").forEach((button) => button.addEventListener("click", () => { discoverState.region = button.dataset.region; void loadDiscover(); }));
  document.querySelectorAll("[data-platform]").forEach((button) => button.addEventListener("click", () => { discoverState.platform = button.dataset.platform; void loadRankings(); }));
  document.querySelectorAll("[data-rank-kind]").forEach((button) => button.addEventListener("click", () => { discoverState.kind = button.dataset.rankKind; void loadRankings(); }));
  document.querySelectorAll("[data-rank-region]").forEach((button) => button.addEventListener("click", () => { discoverState.region = button.dataset.rankRegion.toLowerCase(); void loadRankings(); }));
}

function posterCard(item) {
  return `<button class="rail-card" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}">
    <span class="poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span>
    <strong>${esc(item.title)}</strong><span>${esc(metaLine(item))}</span>
  </button>`;
}

function railSection(title, subtitle, items, key) {
  if (!items.length) return "";
  return `<section class="discover-rail" data-rail="${key}">
    <header><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div><div class="rail-actions"><button class="rail-nav" data-rail-dir="-1" aria-label="向左"><svg class="ic"><use href="#i-chev-l"/></svg></button><button class="rail-nav" data-rail-dir="1" aria-label="向右"><svg class="ic"><use href="#i-chev-r"/></svg></button></div></header>
    <div class="rail-track" data-track="${key}">${items.map(posterCard).join("")}</div>
  </section>`;
}

function sideRail() {
  const active = discoverState.tracking.filter((task) => task.status !== "archived");
  const pending = active.reduce((sum, task) => sum + Math.max(0, (task.episode_count || 0) - (task.saved_count || 0)), 0);
  const review = active.filter((task) => task.decision_state === "pending" || task.status === "needs_review").length;
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return `<aside class="discover-side">
    <section class="discover-side-card">
      <header><div><h2>追更看板</h2><p>按巡检周期自动核对集数</p></div><span class="discover-side-pill">${active.length} 部在追</span></header>
      <div class="discover-side-list">${active.slice(0, 3).map((task) => {
        const total = task.episode_count || 0; const saved = task.saved_count || 0;
        const percent = total ? Math.min(100, Math.round((saved / total) * 100)) : 0;
        return `<button class="discover-side-item" data-route="subscriptions">
          ${posterUrl(task) ? `<img src="${esc(posterUrl(task))}" alt="" loading="lazy" />` : `<span class="discover-side-thumb"></span>`}
          <span class="discover-side-copy"><strong>${esc(task.title)}</strong><small>S${String(task.season_number || 1).padStart(2, "0")} · ${saved} / ${total || "?"}${task.next_check_at ? ` · 下次 ${esc(formatDate(task.next_check_at).slice(5))}` : ""}</small><i><b style="width:${percent}%"></b></i></span>
        </button>`;
      }).join("") || `<p class="discover-side-empty">还没有追更任务，去订阅页添加。</p>`}</div>
      <footer><span>共 ${active.length} 部</span><button data-route="subscriptions">查看全部 →</button></footer>
    </section>
    <section class="discover-side-card">
      <header><div><h2>今日概览</h2><p>本地时间 ${now}</p></div></header>
      <div class="discover-side-stats"><div><strong>${pending}</strong><span>待补集数</span></div><div><strong>${active.length}</strong><span>在追作品</span></div><div><strong>${review}</strong><span>待确认</span></div></div>
    </section>
  </aside>`;
}

function renderExplore() {
  const body = document.getElementById("discoverBody");
  const groups = discoverState.groups;
  const features = [];
  for (const group of groups) for (const item of group.items) {
    if (item.backdrop_url && !features.some((entry) => entry.tmdb_id === item.tmdb_id && entry.media_type === item.media_type)) features.push(item);
    if (features.length >= 7) break;
  }
  const featured = features[discoverState.featureIndex % Math.max(1, features.length)];
  body.innerHTML = `
  <div class="hero-row">
    ${featured ? `<section class="hero" id="hero">
      <div class="hero-slide is-active"><div class="hero-art" style="${backdropUrl(featured) ? `background-image:url(${esc(backdropUrl(featured))})` : ""}"></div></div>
      <div class="hero-copy">
        <span class="hero-eyebrow">MEDIA DISCOVERY</span>
        <h2>${esc(featured.title)}</h2>
        <div class="hero-meta"><span><svg class="ic"><use href="#i-star"/></svg>${featured.vote_average ? Number(featured.vote_average).toFixed(1) : "待评分"}</span><span>${esc(featured.year || "")}</span><span>${featured.media_type === "movie" ? "电影" : "电视剧"}</span></div>
        <p>${esc(featured.overview || "从推荐内容中选择作品，进入详情核对 TMDB 信息并发起资源任务。")}</p>
        <div class="hero-actions">
          <button class="btn primary" data-detail="${esc(featured.media_type)}:${esc(featured.tmdb_id)}">查看作品<svg class="ic"><use href="#i-arrow"/></svg></button>
          <button class="btn ghost" data-track="${esc(featured.media_type)}:${esc(featured.tmdb_id)}"><svg class="ic"><use href="#i-plus"/></svg>加入追更</button>
        </div>
      </div>
      <div class="hero-controls"><button class="rail-nav" data-hero="-1" aria-label="上一张"><svg class="ic"><use href="#i-chev-l"/></svg></button><span class="hero-index">${String(discoverState.featureIndex + 1).padStart(2, "0")} / ${String(Math.max(1, features.length)).padStart(2, "0")}</span><button class="rail-nav" data-hero="1" aria-label="下一张"><svg class="ic"><use href="#i-chev-r"/></svg></button></div>
    </section>` : `<section class="hero"><div class="hero-copy"><h2>暂无推荐内容</h2><p>请先在全局设置中配置 TMDB API Key。</p></div></section>`}
    ${sideRail()}
  </div>
  ${railSection("正在热播", "近期最受关注的电影与节目", groups.find((group) => group.key === "hot")?.items || [], "hot")}
  ${railSection("口碑精选", "按 TMDB 评分发现值得看的作品", groups.find((group) => group.key === "rating")?.items || [], "rating")}
  ${railSection("最近上线", "浏览最近上映和更新的内容", groups.find((group) => group.key === "latest")?.items || [], "latest")}
  ${rankingInlineHtml()}`;
  bindDiscover();
  bindRankInline();
  startHeroTimer(features.length);
}

function rankingInlineHtml() {
  const platform = RANK_PLATFORMS.find(([key]) => key === discoverState.platform) || RANK_PLATFORMS[0];
  const regionLabel = (RANK_REGIONS.find(([key]) => key.toLowerCase() === discoverState.region) || RANK_REGIONS[0])[1];
  const items = discoverState.rankings;
  return `<section class="ranking-block">
    <div class="panel-head"><div><h2>流媒体榜单</h2><small>${platform[0] === "douban" ? "基于 TMDB 华语片评分排序的豆瓣高分近似榜" : `按 ${regionLabel} 地区的 TMDB 可观看来源与当前热度`}</small></div><div class="chip-row platform-row">${RANK_PLATFORMS.map(([key, label, mark]) => `<button class="chip platform-chip${discoverState.platform === key ? " active" : ""}" data-platform="${key}"><i>${mark}</i>${label}</button>`).join("")}</div></div>
    <div class="chip-row rank-filter-row">${[["all", "全部"], ["movie", "电影"], ["tv", "剧集"]].map(([key, label]) => `<button class="chip mini${discoverState.kind === key ? " active" : ""}" data-rank-kind="${key}">${label}</button>`).join("")}<span class="divider"></span>${RANK_REGIONS.map(([key, label]) => `<button class="chip mini${(discoverState.region || "us") === key.toLowerCase() ? " active" : ""}" data-rank-region="${key}">${label}</button>`).join("")}</div>
    ${items.length ? `<div class="rank-list">${items.map((item, index) => `<button class="rank-row" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}"><span class="rank-num">${String(index + 1).padStart(2, "0")}</span><span class="poster rank-poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span><span class="rank-copy"><b>${esc(item.title)}</b><small>${esc(metaLine(item))}</small></span><span class="rank-provider">${esc(platform[1])}</span><svg class="ic"><use href="#i-chev-r"/></svg></button>`).join("")}</div>` : `<div class="empty-state"><b>榜单加载中…</b><span>如果长时间没有内容，检查 TMDB 配置。</span></div>`}
  </section>`;
}

async function loadRankingsInline() {
  const platform = RANK_PLATFORMS.find(([key]) => key === discoverState.platform) || RANK_PLATFORMS[0];
  const region = discoverState.region ? discoverState.region.toUpperCase() : "US";
  const types = discoverState.kind === "all" ? ["movie", "tv"] : [discoverState.kind];
  try {
    const responses = await Promise.all(types.map((type) => platform[0] === "douban"
      ? api(`/api/discover?media_type=${type}&region=cn&sort=rating&genre=&vote_min=0&page=1&page_size=${discoverState.kind === "all" ? 10 : 20}&refresh=false&watch_provider=&watch_region=US`)
      : api(`/api/discover?media_type=${type}&region=&sort=hot&genre=&vote_min=0&page=1&page_size=${discoverState.kind === "all" ? 10 : 20}&refresh=false&watch_provider=${platform[3]}&watch_region=${region}`)));
    const merged = discoverState.kind === "all" ? interleave(responses.map((response) => response.results || [])) : (responses[0].results || []);
    discoverState.rankings = Array.from(new Map(merged.map((item) => [`${item.media_type}-${item.tmdb_id}`, item])).values()).slice(0, 20);
  } catch (error) { discoverState.rankings = []; }
  const block = document.querySelector(".ranking-block");
  if (block) { block.outerHTML = rankingInlineHtml(); bindRankInline(); }
}

function bindRankInline() {
  document.querySelectorAll("[data-platform]").forEach((button) => button.addEventListener("click", () => { discoverState.platform = button.dataset.platform; void loadRankingsInline(); }));
  document.querySelectorAll("[data-rank-kind]").forEach((button) => button.addEventListener("click", () => { discoverState.kind = button.dataset.rankKind; void loadRankingsInline(); }));
  document.querySelectorAll("[data-rank-region]").forEach((button) => button.addEventListener("click", () => { discoverState.region = button.dataset.rankRegion.toLowerCase(); void loadRankingsInline(); }));
  document.querySelectorAll("[data-detail]").forEach((button) => button.addEventListener("click", () => { const [type, tmdb] = button.dataset.detail.split(":"); void openDetail(type, Number(tmdb)); }));
}
function renderRankings() {
  const body = document.getElementById("discoverBody");
  const platform = RANK_PLATFORMS.find(([key]) => key === discoverState.platform) || RANK_PLATFORMS[0];
  const regionLabel = (RANK_REGIONS.find(([key]) => key.toLowerCase() === discoverState.region) || RANK_REGIONS[0])[1];
  const items = discoverState.rankings;
  body.innerHTML = `
  <section class="ranking-hero">
    <div class="ranking-brand"><i>${platform[2]}</i><span>${esc(platform[1])} · STREAMING CHART</span></div>
    <h2>${esc(platform[1])} 热映榜</h2>
    <p>按 ${esc(regionLabel)} 地区的 TMDB 可观看来源与当前热度浏览电影和剧集。</p>
  </section>
  ${items.length ? `<div class="rank-list">${items.map((item, index) => `<button class="rank-row" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}">
    <span class="rank-num">${String(index + 1).padStart(2, "0")}</span>
    <span class="poster rank-poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span>
    <span class="rank-copy"><b>${esc(item.title)}</b><small>${esc(metaLine(item))}</small></span>
    <span class="rank-provider">${esc(platform[1])}</span>
    <svg class="ic"><use href="#i-chev-r"/></svg>
  </button>`).join("")}</div>` : `<div class="empty-state"><b>没有榜单数据</b><span>检查 TMDB 配置或稍后重试。</span></div>`}`;
  bindDiscover();
}

function renderDownload() {
  const body = document.getElementById("discoverBody");
  const draft = discoverState.download;
  body.innerHTML = `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>粘贴链接下载</h2><small>夸克分享链接进入夸克云下载目录；115 分享、磁力、电驴和普通下载链接进入 115 云下载目录。</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field" style="grid-column:1 / -1"><label>分享或下载链接</label><input class="input" id="dlLink" value="${esc(draft.link)}" placeholder="https://pan.quark.cn/s/..." /></div>
      <div class="field"><label>资源名（可选）</label><input class="input" id="dlTitle" value="${esc(draft.title)}" placeholder="用于补充身份提示" /></div>
      <div class="field"><label>年份（可选）</label><input class="input" id="dlYear" value="${esc(draft.year)}" placeholder="2024" /></div>
      <div class="field"><label>类型</label><select class="input" id="dlCategory"><option value="movie" ${draft.category === "movie" ? "selected" : ""}>电影</option><option value="tv" ${draft.category === "tv" ? "selected" : ""}>剧集</option></select></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-dl-parse ${draft.busy ? "disabled" : ""}>${draft.busy ? "解析中…" : "解析可用目录"}</button>${draft.message ? `<span class="inline-result ${draft.options.length ? "ok" : "error"}">${esc(draft.message)}</span>` : ""}</div>
    ${draft.options.length ? `<div class="option-list">${draft.options.map((option) => `<button class="option-row" data-dl-option="${esc(option.path)}"><span class="pill ok"><i></i>${esc(option.provider === "p115" ? "115" : "夸克")}</span><b>${esc(option.label || option.path)}</b><small>${esc(option.path)}</small><svg class="ic"><use href="#i-chev-r"/></svg></button>`).join("")}</div>` : ""}
  </section>`;
  bindDiscoverDownload();
}

function bindDiscover() {
  document.querySelectorAll("[data-detail]").forEach((button) => button.addEventListener("click", () => { const [type, tmdb] = button.dataset.detail.split(":"); void openDetail(type, Number(tmdb)); }));
  document.querySelectorAll("[data-hero]").forEach((button) => button.addEventListener("click", () => { discoverState.featureIndex += Number(button.dataset.hero); renderExplore(); }));
  document.querySelectorAll("[data-track]").forEach((button) => button.addEventListener("click", () => { const [type, tmdb] = button.dataset.track.split(":"); void quickTrack(type, Number(tmdb)); }));
  document.querySelectorAll("[data-track]").forEach((track) => {});
  document.querySelectorAll("[data-rail]").forEach((rail) => {
    const track = rail.querySelector("[data-track]");
    rail.querySelectorAll("[data-rail-dir]").forEach((button) => button.addEventListener("click", () => track.scrollBy({ left: Number(button.dataset.railDir) * 480, behavior: "smooth" })));
  });
}

function bindDiscoverDownload() {
  document.querySelector("[data-dl-parse]")?.addEventListener("click", () => void parseDirectLink());
  document.querySelectorAll("[data-dl-option]").forEach((button) => button.addEventListener("click", () => void transferDirectLink(button.dataset.dlOption)));
}

async function quickTrack(type, tmdbId) {
  try {
    const item = await api(`/api/media/${type}/${tmdbId}`);
    await api("/api/tracking", { method: "POST", body: JSON.stringify({ tmdb_id: item.tmdb_id, media_type: item.media_type, category: item.category || item.media_type, title: item.title, year: item.year || "", poster_url: posterUrl(item), overview: item.overview || "", season_number: item.media_type === "tv" ? 1 : undefined }) });
    await loadDiscover();
  } catch (error) {
    alert(`加入追更失败：${error.message}`);
  }
}

async function parseDirectLink() {
  const draft = discoverState.download;
  draft.link = document.getElementById("dlLink")?.value?.trim() || "";
  draft.title = document.getElementById("dlTitle")?.value?.trim() || "";
  draft.year = document.getElementById("dlYear")?.value?.trim() || "";
  draft.category = document.getElementById("dlCategory")?.value || "movie";
  draft.options = [];
  draft.message = "";
  if (!draft.link) { draft.message = "请先粘贴链接"; renderDownload(); return; }
  draft.busy = true;
  renderDownload();
  try {
    const result = await api("/api/transfers/direct-link/options", { method: "POST", body: JSON.stringify({ link: draft.link, title: draft.title, year: draft.year, category: draft.category }) });
    draft.options = result.options || [];
    draft.message = draft.options.length ? "选择目标目录后开始转存" : (result.message || "没有可用目录");
  } catch (error) { draft.message = error.message; }
  draft.busy = false;
  renderDownload();
}

async function transferDirectLink(path) {
  const draft = discoverState.download;
  draft.busy = true;
  renderDownload();
  try {
    const result = await api("/api/transfers/direct-link", { method: "POST", body: JSON.stringify({ link: draft.link, save_path: path, title: draft.title, year: draft.year, category: draft.category }) });
    draft.options = [];
    draft.message = result.message || "已提交转存任务";
  } catch (error) { draft.message = error.message; }
  draft.busy = false;
  renderDownload();
}

async function loadDiscover() {
  renderDiscoverFilters();
  const body = document.getElementById("discoverBody");
  if (discoverState.section === "download") { renderDownload(); return; }
  if (body) body.innerHTML = `<div class="loading-block">正在读取 TMDB 内容…</div>`;
  if (discoverState.section === "rankings") return loadRankings();
  const [hot, rating, latest, tracking] = await Promise.all([
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=hot&genre=&vote_min=0&page=1&page_size=14&refresh=false&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=rating&genre=&vote_min=0&page=1&page_size=14&refresh=false&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=latest&genre=&vote_min=0&page=1&page_size=14&refresh=false&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api("/api/tracking").catch(() => []),
  ]);
  discoverState.groups = [{ key: "hot", items: hot.results || [] }, { key: "rating", items: rating.results || [] }, { key: "latest", items: latest.results || [] }];
  discoverState.tracking = Array.isArray(tracking) ? tracking : [];
  discoverState.featureIndex = 0;
  renderExplore();
  void loadRankingsInline();
}

async function loadRankings() {
  renderDiscoverFilters();
  const body = document.getElementById("discoverBody");
  if (body) body.innerHTML = `<div class="loading-block">正在读取榜单…</div>`;
  const platform = RANK_PLATFORMS.find(([key]) => key === discoverState.platform) || RANK_PLATFORMS[0];
  const region = discoverState.region ? discoverState.region.toUpperCase() : "US";
  const types = discoverState.kind === "all" ? ["movie", "tv"] : [discoverState.kind];
  try {
    const responses = await Promise.all(types.map((type) => platform[0] === "douban"
    ? api(`/api/discover?media_type=${type}&region=cn&sort=rating&genre=&vote_min=0&page=1&page_size=${discoverState.kind === "all" ? 10 : 20}&refresh=false&watch_provider=&watch_region=US`)
    : api(`/api/discover?media_type=${type}&region=&sort=hot&genre=&vote_min=0&page=1&page_size=${discoverState.kind === "all" ? 10 : 20}&refresh=false&watch_provider=${platform[3]}&watch_region=${region}`)));
    const merged = discoverState.kind === "all" ? interleave(responses.map((response) => response.results || [])) : (responses[0].results || []);
    discoverState.rankings = Array.from(new Map(merged.map((item) => [`${item.media_type}-${item.tmdb_id}`, item])).values()).slice(0, 20);
  } catch (error) {
    discoverState.rankings = [];
  }
  renderRankings();
}

function interleave(lists) {
  const output = [];
  const max = Math.max(0, ...lists.map((list) => list.length));
  for (let index = 0; index < max; index += 1) for (const list of lists) if (list[index]) output.push(list[index]);
  return output;
}

function startHeroTimer(count) {
  window.clearInterval(discoverState.timer);
  if (count < 2) return;
  discoverState.timer = window.setInterval(() => {
    if (document.hidden) return;
    discoverState.featureIndex = (discoverState.featureIndex + 1) % count;
    renderExplore();
  }, 7000);
}

async function openDetail(mediaType, tmdbId) {
  try {
    const item = await api(`/api/media/${mediaType}/${tmdbId}`);
    const dialog = document.createElement("dialog");
    dialog.className = "detail";
    dialog.innerHTML = `
      <div class="detail-top" style="${backdropUrl(item) ? `background-image:url(${esc(backdropUrl(item))})` : ""}">
        <button class="detail-close" data-close aria-label="关闭"><svg class="ic"><use href="#i-close"/></svg></button>
        <div class="detail-head"><span class="poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span>
          <div><p class="eyebrow">TMDB COLLECTION</p><h2>${esc(item.title)}</h2><div class="detail-meta"><span>${item.vote_average ? Number(item.vote_average).toFixed(1) : "待评分"}</span><span>${esc(item.year || "")}</span><span>${item.media_type === "movie" ? "电影" : "电视剧"}</span></div></div>
        </div>
      </div>
      <div class="detail-body"><p>${esc(item.overview || "暂无简介。")}</p><div class="row-actions"><button class="mini-btn primary" data-detail-track="${esc(item.media_type)}:${esc(item.tmdb_id)}">加入智能追更</button></div></div>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
    dialog.querySelector("[data-detail-track]").addEventListener("click", () => { void quickTrack(item.media_type, item.tmdb_id); dialog.close(); });
    dialog.addEventListener("close", () => dialog.remove());
    dialog.showModal();
  } catch (error) { console.error(error); }
}

/* ---------- directory picker ---------- */

const pickerState = { taskId: 0, provider: "", providers: [], parentId: "0", crumbs: [{ id: "0", name: "根目录" }], entries: [], loading: false };

async function openPathPicker(taskId, providers) {
  pickerState.taskId = Number(taskId);
  pickerState.providers = providers.filter(Boolean);
  pickerState.provider = pickerState.providers[0] || "quark";
  pickerState.parentId = "0";
  pickerState.crumbs = [{ id: "0", name: "根目录" }];
  pickerState.entries = [];
  const dialog = document.createElement("dialog");
  dialog.className = "picker-dialog";
  dialog.id = "pathPicker";
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  renderPicker();
  await loadPickerDirectory();
}

function renderPicker() {
  const dialog = document.getElementById("pathPicker");
  if (!dialog) return;
  const path = pickerState.crumbs.map((item) => item.name).join(" / ");
  dialog.innerHTML = `
  <div class="picker-head"><div><h2>选择保存目录</h2><small>${esc(pickerState.provider === "p115" ? "115" : "夸克")} · ${esc(path)}</small></div><button class="icon-btn" data-picker-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="picker-tabs">${pickerState.providers.map((provider) => `<button class="chip${provider === pickerState.provider ? " active" : ""}" data-picker-provider="${provider}">${provider === "p115" ? "115" : "夸克"}</button>`).join("")}</div>
  <div class="picker-crumbs">${pickerState.crumbs.map((crumb, index) => `<button class="crumb-btn" data-picker-crumb="${index}">${esc(crumb.name)}</button>`).join("<span>/</span>")}</div>
  <div class="picker-list">${pickerState.loading ? `<div class="loading-block" style="padding:24px 0">正在读取目录…</div>` : (pickerState.entries.length ? pickerState.entries.map((entry) => `<button class="picker-row" data-picker-enter="${esc(entry.file_id)}" data-picker-name="${esc(entry.name)}"><svg class="ic"><use href="#i-folder"/></svg><span>${esc(entry.name)}</span><svg class="ic ic-sm"><use href="#i-chev-r"/></svg></button>`).join("") : `<div class="empty-state" style="padding:20px 8px"><b>这里没有子目录</b><span>可以直接选择当前目录。</span></div>`)}</div>
  <div class="picker-foot"><button class="mini-btn" data-picker-close>取消</button><button class="mini-btn primary" data-picker-choose>选择当前目录</button></div>`;
  dialog.showModal();
  dialog.querySelectorAll("[data-picker-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  dialog.querySelectorAll("[data-picker-provider]").forEach((button) => button.addEventListener("click", async () => {
    pickerState.provider = button.dataset.pickerProvider;
    pickerState.parentId = "0";
    pickerState.crumbs = [{ id: "0", name: "根目录" }];
    renderPicker();
    await loadPickerDirectory();
  }));
  dialog.querySelectorAll("[data-picker-crumb]").forEach((button) => button.addEventListener("click", async () => {
    const index = Number(button.dataset.pickerCrumb);
    pickerState.crumbs = pickerState.crumbs.slice(0, index + 1);
    pickerState.parentId = pickerState.crumbs[index].id;
    renderPicker();
    await loadPickerDirectory();
  }));
  dialog.querySelectorAll("[data-picker-enter]").forEach((button) => button.addEventListener("click", async () => {
    pickerState.crumbs = [...pickerState.crumbs, { id: button.dataset.pickerEnter, name: button.dataset.pickerName }];
    pickerState.parentId = button.dataset.pickerEnter;
    renderPicker();
    await loadPickerDirectory();
  }));
  dialog.querySelector("[data-picker-choose]")?.addEventListener("click", () => void choosePickerPath());
}

async function loadPickerDirectory() {
  pickerState.loading = true;
  renderPicker();
  try {
    const endpoint = pickerState.provider === "p115"
      ? `/api/cloud/p115/directory?parent_id=${encodeURIComponent(pickerState.parentId)}`
      : `/api/cloud/quark/directory?parent_id=${encodeURIComponent(pickerState.parentId)}`;
    const data = await api(endpoint);
    const entries = Array.isArray(data) ? data : (data.entries || []);
    pickerState.entries = entries.filter((entry) => entry.is_dir);
  } catch (error) {
    pickerState.entries = [];
    console.error(error);
  }
  pickerState.loading = false;
  renderPicker();
}

async function choosePickerPath() {
  const dialog = document.getElementById("pathPicker");
  const path = pickerState.crumbs.map((item) => item.name).filter((name) => name !== "根目录").join("/");
  const value = path ? `/${path}` : "/";
  const input = document.querySelector(`[data-path-input="${pickerState.taskId}"]`);
  if (input) input.value = value;
  dialog?.close();
  try {
    await api(`/api/tracking/${pickerState.taskId}/save-path`, { method: "PATCH", body: JSON.stringify({ save_path: value }) });
  } catch (error) { console.error(error); }
}
/* ---------- QR login ---------- */

const qrState = { sessionId: "", timer: 0, provider: "" };

async function openQrLogin(provider) {
  qrState.provider = provider;
  qrState.sessionId = "";
  window.clearInterval(qrState.timer);
  const dialog = document.createElement("dialog");
  dialog.className = "qr-dialog";
  dialog.id = "qrDialog";
  dialog.innerHTML = `<div class="qr-head"><h2>${provider === "p115" ? "115" : "夸克"}扫码登录</h2><button class="icon-btn" data-qr-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div><div class="qr-body"><div class="loading-block">正在获取二维码…</div></div>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => { window.clearInterval(qrState.timer); dialog.remove(); });
  dialog.querySelector("[data-qr-close]").addEventListener("click", () => dialog.close());
  dialog.showModal();
  try {
    if (provider === "p115") {
      await startP115Qr(dialog, "");
    } else {
      const data = await api("/api/config/quark/qr/start", { method: "POST" });
      if (!data.ok || !data.session_id) throw new Error(data.message || "获取二维码失败");
      qrState.sessionId = data.session_id;
      await renderQrImage(dialog, data.qr_url, "请用夸克 App 扫码");
    }    qrState.timer = window.setInterval(() => void pollQr(dialog), 2000);
  } catch (error) {
    dialog.querySelector(".qr-body").innerHTML = `<div class="empty-state"><b>无法获取二维码</b><span>${esc(error.message)}</span></div>`;
  }
}

async function startP115Qr(dialog, app) {
  window.clearInterval(qrState.timer);
  qrState.sessionId = "";
  const data = await api("/api/cloud/p115/cookie/qrcode", { method: "POST", body: JSON.stringify({ app: app || null }) });
  if (!data.ok || !data.session_id) throw new Error(data.message || "获取二维码失败");
  qrState.sessionId = data.session_id;
  await renderQrImage(dialog, data.qr_image, data.device_notice || "请用 115 App 扫码");
  const body = dialog.querySelector(".qr-body");
  const apps = data.apps || [];
  if (apps.length > 1) {
    const box = document.createElement("div");
    box.className = "qr-apps";
    box.innerHTML = `<span>登录渠道</span>${apps.map((item) => `<button class="chip mini${(app || data.default_app || apps[0]) === item ? " active" : ""}" data-qr-app="${esc(item)}">${esc(item)}</button>`).join("")}`;
    body.appendChild(box);
    box.querySelectorAll("[data-qr-app]").forEach((button) => button.addEventListener("click", () => void startP115Qr(dialog, button.dataset.qrApp).then(() => { qrState.timer = window.setInterval(() => void pollQr(dialog), 2000); })));
  }
  qrState.timer = window.setInterval(() => void pollQr(dialog), 2000);
}
async function renderQrImage(dialog, src, hint) {
  let image = src;
  if (!String(src || "").startsWith("data:")) {
    try { image = await QRCode.toDataURL(String(src), { width: 440, margin: 1, errorCorrectionLevel: "M" }); }
    catch (error) { dialog.querySelector(".qr-body").innerHTML = `<div class="empty-state"><b>二维码生成失败</b><span>${esc(error.message)}</span></div>`; return; }
  }
  dialog.querySelector(".qr-body").innerHTML = `<img class="qr-image" src="${esc(image)}" alt="登录二维码" /><p class="qr-hint">${esc(hint)}</p><p class="qr-status" data-qr-status>等待扫码…</p>`;
}

async function pollQr(dialog) {
  if (!qrState.sessionId) return;
  try {
    const status = qrState.provider === "p115"
      ? await api(`/api/cloud/p115/cookie/qrcode/${encodeURIComponent(qrState.sessionId)}`, { cache: "no-store" })
      : await api("/api/config/quark/qr/poll", { method: "POST", body: JSON.stringify({ session_id: qrState.sessionId }) });
    const node = dialog.querySelector("[data-qr-status]");
    if (node) node.textContent = status.message || status.status || "";
    if (status.status === "done" || status.status === "success") {
      window.clearInterval(qrState.timer);
      dialog.close();
      wsState.result = { ok: true, message: `${qrState.provider === "p115" ? "115" : "夸克"}登录成功，Cookie 已保存。` };
      await loadWs();
    } else if (["expired", "failed", "canceled"].includes(status.status)) {
      window.clearInterval(qrState.timer);
      if (node) node.textContent = status.message || "二维码已失效，请重新获取。";
    }
  } catch (error) { /* keep polling */ }
}
/* ---------- channel subscriptions ---------- */

async function loadChannels() {
  const panel = document.getElementById("wsChannels");
  if (!panel) return;
  const channels = await api("/api/cloud/channels").catch(() => []);
  window.__channels = Array.isArray(channels) ? channels : [];
  renderChannels();
}

function renderChannels() {
  const panel = document.getElementById("wsChannels");
  if (!panel) return;
  const channels = window.__channels || [];
  panel.innerHTML = `
  <div class="panel-head"><div><h2>频道订阅</h2><small>每个频道有独立的规则；同步会按频道规则抓取资源</small></div><div class="row-actions"><button class="mini-btn" data-channel-import>从 PanSou 导入</button><button class="mini-btn" data-channel-sync-all>立即同步全部</button></div></div>
  ${channels.length ? `<div class="channel-list">${channels.map((item) => `
    <div class="channel-row" data-channel="${esc(item.channel_id)}">
      <div class="channel-main"><b>${esc(item.display_name || item.channel_id)}</b><small>${esc(item.channel_id)}${item.last_checked_at ? ` · 上次 ${esc(formatDate(item.last_checked_at))}` : ""}${item.last_error ? ` · ${esc(item.last_error)}` : ""}</small></div>
      <span class="pill ${item.enabled ? "ok" : "muted"}"><i></i>${item.enabled ? "已启用" : "已停用"}</span>
      <button class="switch" data-channel-toggle="${esc(item.channel_id)}" aria-checked="${item.enabled ? "true" : "false"}" aria-label="启用频道"></button>
      <button class="mini-btn" data-channel-sync="${esc(item.channel_id)}">同步</button>
      <button class="mini-btn danger" data-channel-delete="${esc(item.channel_id)}">删除</button>
    </div>`).join("")}</div>` : `<div class="empty-state"><b>还没有频道订阅</b><span>可以从 PanSou 导入，或先在 Telegram 里收集频道。</span></div>`}`;
  bindChannels();
}

function channelPayload(item, overrides = {}) {
  return {
    channel_id: item.channel_id,
    display_name: item.display_name || item.channel_id,
    enabled: item.enabled,
    auto_transfer: item.auto_transfer,
    auto_save_resources: item.auto_save_resources,
    positive_keywords: item.positive_keywords || [],
    negative_keywords: item.negative_keywords || [],
    auto_classify: item.auto_classify,
    cloud_download_child: item.cloud_download_child || "",
    require_douban_match: item.require_douban_match,
    douban_titles: item.douban_titles || [],
    ...overrides,
  };
}

function bindChannels() {
  const channels = window.__channels || [];
  document.querySelectorAll("[data-channel-toggle]").forEach((button) => button.addEventListener("click", async () => {
    const item = channels.find((entry) => entry.channel_id === button.dataset.channelToggle);
    if (!item) return;
    try { await api("/api/cloud/channels", { method: "PUT", body: JSON.stringify(channelPayload(item, { enabled: !item.enabled })) }); }
    catch (error) { wsState.result = { ok: false, message: error.message }; }
    await loadChannels();
  }));
  document.querySelectorAll("[data-channel-sync]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true; button.textContent = "同步中…";
    try { const result = await api(`/api/cloud/channels/sync?channel_id=${encodeURIComponent(button.dataset.channelSync)}`, { method: "POST" }); wsState.result = { ok: Boolean(result.ok), message: result.message || "同步完成" }; }
    catch (error) { wsState.result = { ok: false, message: error.message }; }
    await loadChannels();
  }));
  document.querySelectorAll("[data-channel-delete]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("删除这个频道订阅？")) return;
    const item = channels.find((entry) => entry.channel_id === button.dataset.channelDelete);
    if (!item) return;
    try { await api("/api/cloud/channels", { method: "DELETE", body: JSON.stringify({ subscription_ids: [item.id] }) }); }
    catch (error) { wsState.result = { ok: false, message: error.message }; }
    await loadChannels();
  }));
  document.querySelector("[data-channel-sync-all]")?.addEventListener("click", async () => {
    try { const result = await api("/api/cloud/channels/sync", { method: "POST" }); wsState.result = { ok: Boolean(result.ok), message: result.message || "同步完成" }; }
    catch (error) { wsState.result = { ok: false, message: error.message }; }
    await loadChannels();
  });
  document.querySelector("[data-channel-import]")?.addEventListener("click", () => void openPansouImport());
}

async function openPansouImport() {
  const data = await api("/api/cloud/channels/pansou").catch(() => ({ candidates: [], message: "读取失败" }));
  const candidates = data.candidates || [];
  const dialog = document.createElement("dialog");
  dialog.className = "picker-dialog";
  dialog.innerHTML = `
  <div class="picker-head"><div><h2>从 PanSou 导入频道</h2><small>${esc(data.message || "")}</small></div><button class="icon-btn" data-import-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="picker-list">${candidates.length ? candidates.map((item) => `<label class="picker-row check"><input type="checkbox" data-import-id="${esc(item.channel_id)}" /><span>${esc(item.display_name || item.channel_id)}<small>${esc(item.channel_id)}</small></span></label>`).join("") : `<div class="empty-state"><b>没有可导入的频道</b><span>先在 PanSou 中配置频道。</span></div>`}</div>
  <div class="picker-foot"><button class="mini-btn" data-import-close>取消</button><button class="mini-btn primary" data-import-confirm>导入所选</button></div>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.querySelectorAll("[data-import-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  dialog.querySelector("[data-import-confirm]")?.addEventListener("click", async () => {
    const ids = [...dialog.querySelectorAll("[data-import-id]")].filter((input) => input.checked).map((input) => input.dataset.importId);
    if (!ids.length) { dialog.close(); return; }
    try { const result = await api("/api/cloud/channels/import-pansou", { method: "POST", body: JSON.stringify({ channel_ids: ids }) }); wsState.result = { ok: true, message: result.message || `已导入 ${(result.imported || []).length} 个频道` }; }
    catch (error) { wsState.result = { ok: false, message: error.message }; }
    dialog.close();
    await loadChannels();
  });
  dialog.showModal();
}
/* ---------- job detail ---------- */

function openJobDetail(jobId) {
  const job = (wsState.jobs || []).find((item) => Number(item.id) === Number(jobId));
  if (!job) return;
  const rows = [
    ["状态", job.status], ["阶段", job.stage], ["网盘", job.provider], ["目标", job.target],
    ["保存路径", job.save_path], ["源文件", job.source_file], ["重命名", job.renamed_file],
    ["标题", job.display_title], ["媒体类型", job.media_type], ["季", job.season_number],
    ["来源", job.request_source], ["消息", job.message], ["创建", formatDate(job.created_at)], ["完成", formatDate(job.finished_at)],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  const dialog = document.createElement("dialog");
  dialog.className = "job-dialog";
  dialog.innerHTML = `
  <div class="picker-head"><div><h2>任务 #${esc(job.id)} 详情</h2><small>${esc(job.display_title || job.title || job.media_title || "")}</small></div><button class="icon-btn" data-close-job aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="job-grid">${rows.map(([label, value]) => `<div class="job-row"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join("")}</div>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.querySelector("[data-close-job]").addEventListener("click", () => dialog.close());
  dialog.showModal();
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
      <div class="task-path"><label>保存路径</label><input class="input" value="${esc(task.save_path || (states[0] && states[0].save_path) || "")}" data-path-input="${task.id}" /><button class="mini-btn" data-pick-path="${task.id}" data-providers="${states.map((entry) => entry.provider).join(",")}">选择</button><button class="mini-btn" data-save-path="${task.id}">保存</button></div>
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
  document.querySelectorAll("[data-pick-path]").forEach((button) => button.addEventListener("click", () => void openPathPicker(button.dataset.pickPath, (button.dataset.providers || "").split(","))));
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
/* ---------- workspace ---------- */

const wsState = { section: sessionStorage.getItem("mi-ws-section") || "connections", provider: "quark", busy: "", result: null, config: null };

const WS_SECTIONS = [["connections", "网盘链接"], ["sources", "资源获取"], ["rules", "转存和整理规则"], ["cloud-download", "云下载"], ["webhook", "Webhook"], ["tasks", "任务中心"]];

function wsPageView() {
  return `
  <div class="mi-page" id="wsPage">
    <div class="page-head">
      <div><p class="eyebrow">CLOUD WORKSPACE · 云端执行</p><h1>网盘工作台</h1><p class="sub">连接网盘、接入资源来源、维护转存规则，最后都在任务中心收口。</p></div>
    </div>
    <div class="chip-row" id="wsChips">${WS_SECTIONS.map(([key, label]) => `<button class="chip${wsState.section === key ? " active" : ""}" data-ws-section="${key}">${label}</button>`).join("")}</div>
    <div id="wsBody"><div class="loading-block">正在读取网盘配置…</div></div>
  </div>`;
}

function wsConnectionsView(config) {
  const enabled = (config && config.enabled_providers) || [];
  const quarkOn = enabled.includes("quark");
  const p115On = enabled.includes("p115");
  const provider = wsState.provider;
  const connected = provider === "quark" ? Boolean(config?.has_quark_cookie) : Boolean(config?.has_p115_cookie);
  const cookieLabel = provider === "quark" ? "夸克 Cookie" : "115 Cookie";
  return `
  <section class="panel panel-pad provider-switch">
    <div class="panel-head"><div><h2>网盘执行开关</h2><small>关闭后不会参与发现转存、愿望单或智能追更；连接凭据和历史任务不会删除。</small></div></div>
    <div class="provider-switch-grid">
      <button class="provider-tile${quarkOn ? " is-on" : ""}" data-ws-toggle="quark" ${wsState.busy ? "disabled" : ""}>
        <svg class="ic"><use href="#i-cloud"/></svg>
        <strong>夸克</strong>
        <small>${quarkOn ? "已启用" : "已停用"}</small>
      </button>
      <button class="provider-tile${p115On ? " is-on" : ""}" data-ws-toggle="p115" ${wsState.busy ? "disabled" : ""}>
        <svg class="ic"><use href="#i-db"/></svg>
        <strong>115</strong>
        <small>${p115On ? "已启用" : "已停用"}</small>
      </button>
    </div>
  </section>
  <div class="chip-row provider-tabs">
    <button class="chip${provider === "quark" ? " active" : ""}" data-ws-provider="quark">夸克网盘</button>
    <button class="chip${provider === "p115" ? " active" : ""}" data-ws-provider="p115">115 网盘</button>
  </div>
  <div class="split split-even">
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>${cookieLabel}</h2><small>${provider === "quark" ? "从已登录的夸克网页复制 Cookie 后粘贴。仅保存在本机服务端，保存后输入框会清空。" : "115 原生统一使用 Cookie 读取目录、验真和执行操作。"}</small></div></div>
      <div class="field"><label>${cookieLabel}</label><input class="input" id="wsCookie" type="password" placeholder="${connected ? "已保存，如需更换请重新粘贴" : "未配置"}" /></div>
      <div class="row-actions" style="margin-top:10px"><button class="mini-btn primary" data-ws-save-cookie ${wsState.busy ? "disabled" : ""}>保存 Cookie</button><button class="mini-btn" data-ws-qr>扫码登录</button></div>
      ${wsState.result ? `<p class="inline-result ${wsState.result.ok ? "ok" : "error"}">${esc(wsState.result.message)}</p>` : ""}
    </section>
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>连接验证</h2><small>会读取账号资料和根目录前 50 项，不修改网盘文件。</small></div></div>
      <div class="connection-status ${connected ? "ok" : ""}">
        <span class="pill ${connected ? "ok" : "muted"}"><i></i>${connected ? "凭据已保存" : "尚未连接"}</span>
        <p class="muted-note">${provider === "quark" ? "验证成功后会读取根目录，确认 Cookie 可用。" : "验证成功后会读取账号资料和根目录前 50 项。"}</p>
      </div>
      <button class="btn primary sm" data-ws-test ${wsState.busy ? "disabled" : ""}><svg class="ic"><use href="#i-check"/></svg>验证连接</button>
    </section>
  </div>`;
}

function wsSourcesView(config) {
  return `
  <div class="split split-even">
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>PanSou 资源接口</h2><small>发现页与追更通过 PanSou 检索网盘资源</small></div><button class="mini-btn" data-ws-test="pansou">测试 PanSou</button></div>
      <div class="field"><label>PanSou 地址</label><input class="input" id="wsPansou" value="${esc(config.pansou_url || "")}" placeholder="https://pansou.example.com" /></div>
      <div class="field" style="margin-top:10px"><label>排除关键词</label><textarea class="input" id="wsPansouExclude" rows="3" placeholder="预告,花絮">${esc(config.pansou_exclude_keywords || "")}</textarea></div>
      <div class="row-actions" style="margin-top:10px"><button class="mini-btn primary" data-ws-save="sources">保存来源设置</button>${wsStateResult()}</div>
    </section>
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>Telegram 频道</h2><small>频道订阅会按轮询周期抓取新资源</small></div></div>
      <div class="switch-row"><div><b>启用频道来源</b><small>需要先配置 Telegram Bot</small></div><button class="switch" id="wsTgEnabled" aria-checked="${config.telegram_channel_source_enabled ? "true" : "false"}" aria-label="启用频道来源"></button></div>
      <div class="form-grid" style="grid-template-columns:1fr">
        <div class="field"><label>轮询周期（分钟）</label><input class="input" id="wsTgPoll" type="number" min="1" value="${esc(config.telegram_channel_poll_minutes ?? 10)}" /></div>
      </div>
      <p class="muted-note">当前已订阅 ${config.telegram_channel_subscription_count ?? 0} 个频道。</p>
      <div class="row-actions"><button class="mini-btn" data-ws-save="telegram">保存频道设置</button></div>
    </section>
  </div>`;
}

function wsRulesView(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>命名规则</h2><small>入库前会按这些规则生成目录与文件名</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>媒体文件夹命名</label><input class="input" id="wsRuleMedia" value="${esc(config.media_folder_naming_rule || "")}" /></div>
      <div class="field"><label>季文件夹命名</label><input class="input" id="wsRuleSeason" value="${esc(config.season_folder_naming_rule || "")}" /></div>
      <div class="field"><label>电影命名</label><input class="input" id="wsRuleMovie" value="${esc(config.movie_naming_rule || "")}" /></div>
      <div class="field"><label>剧集命名</label><input class="input" id="wsRuleEpisode" value="${esc(config.episode_naming_rule || "")}" /></div>
    </div>
    <div class="switch-row"><div><b>季子目录</b><small>电视剧按季建立子目录</small></div><button class="switch" id="wsSeasonDir" aria-checked="${config.season_subdirectory_enabled ? "true" : "false"}" aria-label="季子目录"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-top:10px">
      <div class="field"><label>质量优先关键词</label><input class="input" id="wsQuality" value="${esc((config.quality_priority_keywords || []).join(","))}" placeholder="1080p,4K,HDR" /></div>
      <div class="field"><label>资源排除关键词</label><input class="input" id="wsExclude" value="${esc((config.resource_excluded_keywords || []).join(","))}" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="rules">保存整理规则</button>${wsStateResult()}</div>
  </section>`;
}

function wsCloudView(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>云下载整理</h2><small>云下载完成后由整理器识别、改名并落盘到正式媒体库</small></div></div>
    <div class="switch-row"><div><b>启用云下载整理</b><small>总开关</small></div><button class="switch" id="wsCloudEnabled" aria-checked="${config.cloud_download_organizer_enabled ? "true" : "false"}" aria-label="启用云下载整理"></button></div>
    <div class="switch-row"><div><b>115 云下载</b><small>处理 115 云下载目录</small></div><button class="switch" id="wsCloudP115" aria-checked="${config.p115_cloud_download_organizer_enabled ? "true" : "false"}" aria-label="115 云下载"></button></div>
    <div class="switch-row"><div><b>夸克云下载</b><small>处理夸克云下载目录</small></div><button class="switch" id="wsCloudQuark" aria-checked="${config.quark_cloud_download_organizer_enabled ? "true" : "false"}" aria-label="夸克云下载"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>整理间隔（分钟）</label><input class="input" id="wsCloudInterval" type="number" min="1" value="${esc(config.cloud_download_organizer_interval_minutes ?? 10)}" /></div>
      <div class="field"><label>稳定等待（分钟）</label><input class="input" id="wsCloudStable" type="number" min="0" value="${esc(config.cloud_download_organizer_stable_minutes ?? 3)}" /></div>
      <div class="field"><label>115 暂存目录</label><input class="input" id="wsStagingP115" value="${esc(config.p115_staging_path || "")}" /></div>
      <div class="field"><label>夸克暂存目录</label><input class="input" id="wsStagingQuark" value="${esc(config.quark_staging_path || "")}" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="cloud">保存云下载设置</button>${wsStateResult()}</div>
  </section>`;
}

function wsWebhookView(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>MoviePilot / MDC Webhook</h2><small>接收外部下载完成事件，按规则入库</small></div></div>
    <div class="switch-row"><div><b>启用 Webhook</b><small>开启后需要配置访问令牌</small></div><button class="switch" id="wsWebhookEnabled" aria-checked="${config.mdc_webhook_enabled ? "true" : "false"}" aria-label="启用 Webhook"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>Webhook Token</label><input class="input" id="wsWebhookToken" type="password" placeholder="${config.has_mdc_webhook_token ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>执行网盘</label><select class="input" id="wsWebhookProvider"><option value="p115" ${config.mdc_webhook_provider !== "quark" ? "selected" : ""}>115</option><option value="quark" ${config.mdc_webhook_provider === "quark" ? "selected" : ""}>夸克</option></select></div>
      <div class="field"><label>根路径</label><input class="input" id="wsWebhookRoot" value="${esc(config.mdc_webhook_root_path || "")}" /></div>
      <div class="field"><label>扫描路径</label><input class="input" id="wsWebhookScan" value="${esc(config.mdc_webhook_scan_path || "")}" /></div>
      <div class="field"><label>防抖秒数</label><input class="input" id="wsWebhookDebounce" type="number" min="0" value="${esc(config.mdc_webhook_debounce_seconds ?? 5)}" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="webhook">保存 Webhook 设置</button>${wsStateResult()}</div>
  </section>`;
}

function wsTasksView(jobs) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>任务中心</h2><small>最近 20 条转存任务</small></div><button class="mini-btn" data-ws-refresh>刷新</button></div>
    ${jobs.length ? `<div class="task-list">${jobs.slice(0, 20).map((job) => `
      <article class="task-card" data-job-detail="${job.id}" style="cursor:pointer">
        <div class="task-head">
          <span class="thumb"></span>
          <div class="task-title"><div><b>${esc(job.display_title || job.title || job.media_title || `任务 #${job.id}`)}</b><span class="pill ${job.status === "failed" ? "danger" : job.status === "done" ? "ok" : "warn"}"><i></i>${esc(job.status || "")}</span></div><small>${esc(job.message || job.stage || "")}</small></div>
          <div class="task-progress"><span>${esc(job.provider || "")}</span><small>${esc(job.created_at ? formatDate(job.created_at) : "")}</small></div>
        </div>
      </article>`).join("")}</div>` : `<div class="empty-state"><b>没有任务</b><span>发现页发起转存后，这里会出现记录。</span></div>`}
  </section>`;
}

function wsStateResult() {
  return wsState.result ? `<span class="inline-result ${wsState.result.ok ? "ok" : "error"}">${esc(wsState.result.message)}</span>` : "";
}
function wsPlaceholder(section) {
  const [key, label] = WS_SECTIONS.find(([k]) => k === section) || ["", ""];
  return `<section class="panel panel-pad"><div class="panel-head"><div><h2>${label}</h2><small>这一分区正在接入真实数据。</small></div></div><div class="empty-state"><b>即将上线</b><span>外壳与导航已就绪，内容区下一轮接入接口。</span></div></section>`;
}

async function loadWs() {
  const body = document.getElementById("wsBody");
  if (!body) return;
  const config = await api("/api/config/status").catch(() => null);
  wsState.config = config;
  state.config = config || state.config;
  if (wsState.section === "connections") body.innerHTML = wsConnectionsView(config);
  else if (wsState.section === "sources") { body.innerHTML = wsSourcesView(config); body.insertAdjacentHTML("beforeend", `<section class="panel panel-pad" id="wsChannels"><div class="loading-block">正在读取频道订阅…</div></section>`); setTimeout(() => void loadChannels(), 0); }
  else if (wsState.section === "rules") body.innerHTML = wsRulesView(config);
  else if (wsState.section === "cloud-download") body.innerHTML = wsCloudView(config);
  else if (wsState.section === "webhook") body.innerHTML = wsWebhookView(config);
  else if (wsState.section === "tasks") { const jobs = await api("/api/transfers").catch(() => []); wsState.jobs = Array.isArray(jobs) ? jobs : []; body.innerHTML = wsTasksView(wsState.jobs); }
  else body.innerHTML = wsPlaceholder(wsState.section);
  bindWs();
}

function bindWs() {
  document.querySelectorAll("[data-ws-section]").forEach((button) => button.addEventListener("click", () => { wsState.section = button.dataset.wsSection; document.querySelectorAll("[data-ws-section]").forEach((chip) => chip.classList.toggle("active", chip.dataset.wsSection === wsState.section)); void loadWs(); }));
  document.querySelectorAll("[data-ws-provider]").forEach((button) => button.addEventListener("click", () => { wsState.provider = button.dataset.wsProvider; wsState.result = null; void loadWs(); }));
  document.querySelectorAll("[data-ws-toggle]").forEach((button) => button.addEventListener("click", () => void toggleWsProvider(button.dataset.wsToggle)));
  document.querySelector("[data-ws-qr]")?.addEventListener("click", () => void openQrLogin(wsState.provider));
  document.querySelector("[data-ws-save-cookie]")?.addEventListener("click", () => void saveWsCookie());
  document.querySelector("[data-ws-test]")?.addEventListener("click", () => void testWsConnection());
  document.querySelectorAll(".switch").forEach((button) => button.addEventListener("click", () => button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true")));
  document.querySelectorAll("[data-ws-save]").forEach((button) => button.addEventListener("click", () => void saveWsSection(button.dataset.wsSave)));
  document.querySelectorAll("[data-ws-test]").forEach((button) => button.addEventListener("click", () => void testWsSection(button.dataset.wsTest)));
  document.querySelector("[data-ws-refresh]")?.addEventListener("click", () => void loadWs());
  document.querySelectorAll("[data-job-detail]").forEach((card) => card.addEventListener("click", () => openJobDetail(card.dataset.jobDetail)));
}

async function saveWsSection(scope) {
  const payload = {};
  if (scope === "sources") {
    payload.pansou_url = document.getElementById("wsPansou")?.value || "";
    payload.pansou_exclude_keywords = document.getElementById("wsPansouExclude")?.value || "";
  } else if (scope === "telegram") {
    payload.telegram_channel_source_enabled = document.getElementById("wsTgEnabled")?.getAttribute("aria-checked") === "true";
    payload.telegram_channel_poll_minutes = Number(document.getElementById("wsTgPoll")?.value || 10);
  } else if (scope === "rules") {
    payload.media_folder_naming_rule = document.getElementById("wsRuleMedia")?.value || "";
    payload.season_folder_naming_rule = document.getElementById("wsRuleSeason")?.value || "";
    payload.movie_naming_rule = document.getElementById("wsRuleMovie")?.value || "";
    payload.episode_naming_rule = document.getElementById("wsRuleEpisode")?.value || "";
    payload.season_subdirectory_enabled = document.getElementById("wsSeasonDir")?.getAttribute("aria-checked") === "true";
    payload.quality_priority_keywords = (document.getElementById("wsQuality")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
    payload.resource_excluded_keywords = (document.getElementById("wsExclude")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
  } else if (scope === "cloud") {
    payload.cloud_download_organizer_enabled = document.getElementById("wsCloudEnabled")?.getAttribute("aria-checked") === "true";
    payload.p115_cloud_download_organizer_enabled = document.getElementById("wsCloudP115")?.getAttribute("aria-checked") === "true";
    payload.quark_cloud_download_organizer_enabled = document.getElementById("wsCloudQuark")?.getAttribute("aria-checked") === "true";
    payload.cloud_download_organizer_interval_minutes = Number(document.getElementById("wsCloudInterval")?.value || 10);
    payload.cloud_download_organizer_stable_minutes = Number(document.getElementById("wsCloudStable")?.value || 3);
    payload.p115_staging_path = document.getElementById("wsStagingP115")?.value || "";
    payload.quark_staging_path = document.getElementById("wsStagingQuark")?.value || "";
  } else if (scope === "webhook") {
    payload.mdc_webhook_enabled = document.getElementById("wsWebhookEnabled")?.getAttribute("aria-checked") === "true";
    payload.mdc_webhook_provider = document.getElementById("wsWebhookProvider")?.value || "p115";
    payload.mdc_webhook_root_path = document.getElementById("wsWebhookRoot")?.value || "";
    payload.mdc_webhook_scan_path = document.getElementById("wsWebhookScan")?.value || "";
    payload.mdc_webhook_debounce_seconds = Number(document.getElementById("wsWebhookDebounce")?.value || 5);
    const token = document.getElementById("wsWebhookToken")?.value?.trim();
    if (token) payload.mdc_webhook_token = token;
  }
  try { await api("/api/config", { method: "PUT", body: JSON.stringify(payload) }); wsState.result = { ok: true, message: "设置已保存" }; }
  catch (error) { wsState.result = { ok: false, message: error.message }; }
  await loadWs();
}

async function testWsSection(kind) {
  const endpoints = { pansou: "/api/config/test-pansou", tmdb: "/api/config/test-tmdb", openlist: "/api/openlist/test" };
  try { const result = await api(endpoints[kind], { method: "POST" }); wsState.result = { ok: Boolean(result.ok), message: result.message || "验证完成" }; }
  catch (error) { wsState.result = { ok: false, message: error.message }; }
  await loadWs();
}

async function toggleWsProvider(target) {
  if (wsState.busy) return;
  const config = wsState.config;
  if (!config) return;
  const current = ["quark", "p115"].filter((item) => (config.enabled_providers || []).includes(item));
  const next = current.includes(target) ? current.filter((item) => item !== target) : [...current, target];
  if (!next.length) { wsState.result = { ok: false, message: "至少保留一个网盘作为执行端" }; await loadWs(); return; }
  wsState.busy = target;
  try {
    await api("/api/config", { method: "PUT", body: JSON.stringify({ enabled_providers: next, default_provider: next.includes(config.default_provider) ? config.default_provider : next[0] }) });
    wsState.result = { ok: true, message: `${target === "p115" ? "115" : "夸克"}已${current.includes(target) ? "停用" : "启用"}；发现、愿望单和追更会按新状态执行。` };
  } catch (error) { wsState.result = { ok: false, message: error.message }; }
  wsState.busy = "";
  await loadWs();
}

async function saveWsCookie() {
  const input = document.getElementById("wsCookie");
  const value = input?.value?.trim();
  if (!value) return;
  wsState.busy = "cookie";
  try {
    const payload = wsState.provider === "quark" ? { quark_cookie: value } : { p115_cookie: value, p115_auth_mode: "cookie" };
    await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
    wsState.result = { ok: true, message: `${wsState.provider === "quark" ? "夸克" : "115"} Cookie 已保存在本机服务端。` };
  } catch (error) { wsState.result = { ok: false, message: error.message }; }
  wsState.busy = "";
  await loadWs();
}

async function testWsConnection() {
  wsState.busy = "test";
  try {
    const result = await api(wsState.provider === "quark" ? "/api/config/test-quark" : "/api/config/test-p115", { method: "POST" });
    wsState.result = { ok: Boolean(result.ok), message: result.message || "验证完成" };
  } catch (error) { wsState.result = { ok: false, message: error.message }; }
  wsState.busy = "";
  await loadWs();
}
/* ---------- cross cloud ---------- */

const crossState = { config: null, transfers: [], result: null, busy: "", open: false };

function crossPageView() {
  return `
  <div class="mi-page" id="crossPage">
    <div class="page-head">
      <div><p class="eyebrow">CROSS CLOUD · 跨盘补齐</p><h1>跨盘转存</h1><p class="sub">这是补偿链路：两盘各自完成发现与转存，需要时再从夸克定向补齐 115。</p></div>
      <div class="page-actions"><button class="btn ghost sm" data-cross-open><svg class="ic"><use href="#i-swap"/></svg>跨盘补齐</button></div>
    </div>
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>补偿链路，不是发现入口</h2><small>先由两个网盘分别完成发现与转存；需要时再从夸克定向补齐 115。</small></div></div>
      <div class="row-actions"><a class="mini-btn" href="#workspace">查看任务中心</a></div>
    </section>
    <div id="crossBody"><div class="loading-block">正在读取跨盘配置…</div></div>
  </div>`;
}

function crossRulesView(config) {
  if (crossState.open) return crossOpenForm(config);
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>跨盘通路与补齐规则</h2><small>OpenList 与 CD2 二选一；两条通路共用缺失文件筛选、落盘核验和 STRM / Emby 入库流程。</small></div></div>
    <div class="callout"><b>自动补齐会在什么时候启动？</b><p>夸克文件完成标准命名和正式落盘后，系统先检查 115 目标，再搜索并验真 115 原生分享。只有仍缺失的精确文件会交给所选跨盘通路。</p><p>云下载暂存内容须先由整理器完成正式落盘。智能追更还需在对应季度开启自动补齐。</p></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px">
      <div class="field"><label>复制通路</label><select class="input" id="crossTransport"><option value="openlist" ${config.cross_copy_transport !== "cd2" ? "selected" : ""}>OpenList</option><option value="cd2" ${config.cross_copy_transport === "cd2" ? "selected" : ""}>CD2</option></select></div>
      <div class="field"><label>OpenList 地址</label><input class="input" id="crossUrl" value="${esc(config.openlist_url || "")}" placeholder="http://openlist:5244" /></div>
      <div class="field"><label>OpenList Token</label><input class="input" id="crossToken" type="password" placeholder="${config.has_openlist_token ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>夸克库路径</label><input class="input" id="crossQuarkPath" value="${esc(config.openlist_qas_library_path || "")}" placeholder="/夸克/媒体库" /></div>
      <div class="field"><label>115 库路径</label><input class="input" id="crossP115Path" value="${esc(config.openlist_p115_library_path || "")}" placeholder="/115/媒体库" /></div>
      <div class="field"><label>同步方向</label><select class="input" id="crossDirection"><option value="qas_to_p115" ${config.openlist_auto_sync_direction !== "bidirectional" && config.openlist_auto_sync_direction !== "p115_to_qas" ? "selected" : ""}>夸克 → 115</option><option value="p115_to_qas" ${config.openlist_auto_sync_direction === "p115_to_qas" ? "selected" : ""}>115 → 夸克</option><option value="bidirectional" ${config.openlist_auto_sync_direction === "bidirectional" ? "selected" : ""}>双向</option></select></div>
    </div>
    <div class="switch-row"><div><b>启用跨盘复制</b><small>开启后，缺失文件会交由所选通路补齐</small></div><button class="switch" data-cross-enabled aria-checked="${config.openlist_enabled ? "true" : "false"}" aria-label="启用跨盘复制"></button></div>
    <div class="row-actions" style="margin-top:12px">
      <button class="mini-btn primary" data-cross-save>保存跨盘设置</button>
      <button class="mini-btn" data-cross-test>测试 OpenList</button>
      ${crossState.result ? `<span class="inline-result ${crossState.result.ok ? "ok" : "error"}">${esc(crossState.result.message)}</span>` : ""}
    </div>
  </section>
  ${crossTransfersView()}`;
}

function crossOpenForm(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>手动跨盘补齐</h2><small>选择一段夸克路径，补齐到 115 对应目录。</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>来源（夸克）</label><input class="input" id="crossFrom" placeholder="/夸克/媒体库/电影/片名 (2024)" /></div>
      <div class="field"><label>目标（115）</label><input class="input" id="crossTo" value="${esc(config.openlist_p115_library_path || "")}" placeholder="/115/媒体库" /></div>
    </div>
    <div class="row-actions"><button class="mini-btn primary" data-cross-create>创建补齐任务</button><button class="mini-btn" data-cross-cancel>返回</button></div>
    ${crossState.result ? `<p class="inline-result ${crossState.result.ok ? "ok" : "error"}">${esc(crossState.result.message)}</p>` : ""}
  </section>`;
}

function crossTransfersView() {
  const rows = crossState.transfers.slice(0, 8);
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>最近跨盘任务</h2><small>只展示补偿链路产生的任务</small></div><button class="mini-btn" data-cross-reload>刷新</button></div>
    ${rows.length ? `<div class="task-list">${rows.map((item) => `
      <article class="task-card">
        <div class="task-head">
          <span class="thumb"></span>
          <div class="task-title"><div><b>${esc(item.title || item.source_path || `任务 #${item.id}`)}</b><span class="pill ${item.state === "failed" ? "danger" : item.state === "done" ? "ok" : "warn"}"><i></i>${esc(item.state || "")}</span></div><small>${esc(item.source_path || "")} → ${esc(item.target_path || "")}</small></div>
          <div class="task-progress"><span>${esc(item.message || "")}</span></div>
        </div>
      </article>`).join("")}</div>` : `<div class="empty-state"><b>没有跨盘任务</b><span>当追更或补齐触发跨盘通路时，这里会出现记录。</span></div>`}
  </section>`;
}

async function loadCross() {
  const body = document.getElementById("crossBody");
  if (!body) return;
  const [config, transfers] = await Promise.all([
    api("/api/config/status").catch(() => null),
    api("/api/cloud/cross-transfers").catch(() => []),
  ]);
  crossState.config = config;
  crossState.transfers = Array.isArray(transfers) ? transfers : [];
  body.innerHTML = config ? crossRulesView(config) : `<section class="panel panel-pad"><div class="empty-state"><b>配置读取失败</b><span>请稍后重试</span></div></section>`;
  bindCross();
}

function bindCross() {
  document.querySelector("[data-cross-open]")?.addEventListener("click", () => { crossState.open = true; void loadCross(); });
  document.querySelector("[data-cross-cancel]")?.addEventListener("click", () => { crossState.open = false; void loadCross(); });
  document.querySelector("[data-cross-reload]")?.addEventListener("click", () => void loadCross());
  document.querySelector("[data-cross-enabled]")?.addEventListener("click", (event) => {
    const el = event.currentTarget;
    el.setAttribute("aria-checked", el.getAttribute("aria-checked") === "true" ? "false" : "true");
  });
  document.querySelector("[data-cross-save]")?.addEventListener("click", () => void saveCross());
  document.querySelector("[data-cross-test]")?.addEventListener("click", () => void testCross());
  document.querySelector("[data-cross-create]")?.addEventListener("click", () => void createCrossTransfer());
}

async function saveCross() {
  const payload = {
    cross_copy_transport: document.getElementById("crossTransport")?.value || "openlist",
    openlist_url: document.getElementById("crossUrl")?.value || "",
    openlist_qas_library_path: document.getElementById("crossQuarkPath")?.value || "",
    openlist_p115_library_path: document.getElementById("crossP115Path")?.value || "",
    openlist_auto_sync_direction: document.getElementById("crossDirection")?.value || "qas_to_p115",
    openlist_enabled: document.querySelector("[data-cross-enabled]")?.getAttribute("aria-checked") === "true",
  };
  const token = document.getElementById("crossToken")?.value?.trim();
  if (token) payload.openlist_token = token;
  try { await api("/api/config", { method: "PUT", body: JSON.stringify(payload) }); crossState.result = { ok: true, message: "跨盘设置已保存" }; }
  catch (error) { crossState.result = { ok: false, message: error.message }; }
  await loadCross();
}

async function testCross() {
  crossState.busy = "test";
  try { const result = await api("/api/openlist/test", { method: "POST" }); crossState.result = { ok: Boolean(result.ok), message: result.message || "验证完成" }; }
  catch (error) { crossState.result = { ok: false, message: error.message }; }
  crossState.busy = "";
  await loadCross();
}

async function createCrossTransfer() {
  const from = document.getElementById("crossFrom")?.value?.trim();
  const to = document.getElementById("crossTo")?.value?.trim();
  if (!from || !to) { crossState.result = { ok: false, message: "请填写来源和目标路径" }; await loadCross(); return; }
  try {
    await api("/api/cloud/cross-transfers", { method: "POST", body: JSON.stringify({ source_path: from, target_path: to, transport: crossState.config?.cross_copy_transport || "openlist" }) });
    crossState.result = { ok: true, message: "补齐任务已创建" };
    crossState.open = false;
  } catch (error) { crossState.result = { ok: false, message: error.message }; }
  await loadCross();
}
/* ---------- strm ---------- */

const strmState = { section: "common", config: null, result: null, entries: [] };

function strmPageView() {
  return `
  <div class="mi-page" id="strmPage">
    <div class="page-head">
      <div><p class="eyebrow">STRM · MEDIA PLAYBACK</p><h1>STRM 与 302</h1><p class="sub">把网盘里的文件映射成 Emby 可播放的 STRM，并用 302 直连播放。</p></div>
      <div class="page-actions"><span class="pill ${state.config && state.config.has_emby_api_key ? "ok" : "muted"}"><i></i>${state.config && state.config.has_emby_api_key ? "Emby 已配置" : "Emby 未连接"}</span></div>
    </div>
    <div class="chip-row" id="strmChips">
      <button class="chip${strmState.section === "common" ? " active" : ""}" data-strm-section="common">STRM 通用设置</button>
      <button class="chip${strmState.section === "p115" ? " active" : ""}" data-strm-section="p115">115 STRM</button>
      <button class="chip${strmState.section === "quark" ? " active" : ""}" data-strm-section="quark">夸克 STRM</button>
    </div>
    <div id="strmBody"><div class="loading-block">正在读取 STRM 配置…</div></div>
  </div>`;
}

function strmCommonView(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>302 播放地址</h2><small>容器监听端口与 STRM 实际播放入口</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>容器内部监听端口</label><input class="input" value="8097" readonly /></div>
      <div class="field"><label>STRM 播放地址</label><input class="input" id="strmPlayback" value="${esc(config.strm_playback_base_url || "")}" placeholder="https://你的域名:666" /></div>
      <div class="field"><label>STRM 输出目录</label><input class="input" id="strmOutput" value="${esc(config.strm_output_root || "")}" placeholder="/strm" /></div>
      <div class="field"><label>视频扩展名</label><input class="input" id="strmExt" value="${esc((config.strm_video_extensions || []).join(","))}" placeholder="mp4,mkv,ts" /></div>
    </div>
    <p class="muted-note">NAS 播放端口只在 Compose 的 ports 左侧设置；MediaIndex 不读取也不修改宿主机端口。</p>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>Emby 入库</h2><small>生成 STRM 后让 Emby 自动扫描对应媒体库</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>Emby 内网地址</label><input class="input" id="strmEmbyUrl" value="${esc(config.emby_base_url || "")}" placeholder="http://emby:8096" /></div>
      <div class="field"><label>Emby API Key</label><input class="input" id="strmEmbyKey" type="password" placeholder="${config.has_emby_api_key ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>STRM 库根路径</label><input class="input" id="strmEmbyRoot" value="${esc(config.emby_strm_library_root || "")}" /></div>
      <div class="field"><label>STRM 媒体库 ID</label><input class="input" id="strmLibrary" value="${esc(config.strm_library_root_id || "")}" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-strm-save="common">保存本页设置</button>${strmState.result ? `<span class="inline-result ${strmState.result.ok ? "ok" : "error"}">${esc(strmState.result.message)}</span>` : ""}</div>
  </section>`;
}

function strmProviderView(config, provider) {
  const isP115 = provider === "p115";
  const enabled = isP115 ? config.p115_strm_enabled : config.quark_strm_enabled;
  const root = isP115 ? config.p115_strm_source_root : config.quark_strm_source_root;
  const cron = isP115 ? config.p115_strm_incremental_cron : config.quark_strm_incremental_cron;
  const scrape = isP115 ? config.p115_strm_scrape_enabled : config.quark_strm_scrape_enabled;
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>${isP115 ? "115" : "夸克"} STRM 生成</h2><small>从网盘目录生成 STRM，并按增量计划执行</small></div><span class="pill ${enabled ? "ok" : "muted"}"><i></i>${enabled ? "已开启" : "未开启"}</span></div>
    <div class="switch-row"><div><b>启用 ${isP115 ? "115" : "夸克"} STRM</b><small>关闭后不会再生成新的 STRM</small></div><button class="switch" id="strmEnabled" data-checked="${enabled ? "true" : "false"}" aria-checked="${enabled ? "true" : "false"}" aria-label="启用 STRM"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>源目录</label><input class="input" id="strmRoot" value="${esc(root || "")}" placeholder="/媒体库" /></div>
      <div class="field"><label>增量计划（Cron）</label><input class="input" id="strmCron" value="${esc(cron || "")}" placeholder="0 3 * * *" /></div>
      <div class="field"><label>最小文件大小（MB）</label><input class="input" id="strmMinSize" type="number" value="${esc(config.strm_min_file_size_mb ?? 0)}" /></div>
      <div class="field"><label>排除关键词</label><input class="input" id="strmExclude" value="${esc((config.strm_excluded_name_tokens || []).join(","))}" /></div>
    </div>
    <div class="switch-row"><div><b>生成后刮削</b><small>让 Emby 读取 nfo 与图片</small></div><button class="switch" id="strmScrape" aria-checked="${scrape ? "true" : "false"}" aria-label="生成后刮削"></button></div>
    ${isP115 ? `<div class="switch-row"><div><b>生命周期监控</b><small>监听网盘文件变化，自动补生成</small></div><button class="switch" id="strmLife" aria-checked="${config.p115_strm_life_monitor_enabled ? "true" : "false"}" aria-label="生命周期监控"></button></div>` : ""}
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-strm-save="${provider}">保存 ${isP115 ? "115" : "夸克"} 设置</button>${strmState.result ? `<span class="inline-result ${strmState.result.ok ? "ok" : "error"}">${esc(strmState.result.message)}</span>` : ""}</div>
  </section>`;
}

async function loadStrm() {
  const body = document.getElementById("strmBody");
  if (!body) return;
  const config = await api("/api/config/status").catch(() => null);
  strmState.config = config;
  if (!config) { body.innerHTML = `<section class="panel panel-pad"><div class="empty-state"><b>配置读取失败</b><span>请稍后重试</span></div></section>`; return; }
  body.innerHTML = strmState.section === "common" ? strmCommonView(config) : strmProviderView(config, strmState.section);
  bindStrm();
}

function bindStrm() {
  document.querySelectorAll("[data-strm-section]").forEach((button) => button.addEventListener("click", () => {
    strmState.section = button.dataset.strmSection;
    document.querySelectorAll("[data-strm-section]").forEach((chip) => chip.classList.toggle("active", chip.dataset.strmSection === strmState.section));
    void loadStrm();
  }));
  document.querySelectorAll(".switch").forEach((button) => button.addEventListener("click", () => {
    button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true");
  }));
  document.querySelectorAll("[data-strm-save]").forEach((button) => button.addEventListener("click", () => void saveStrm(button.dataset.strmSave)));
}

async function saveStrm(scope) {
  const payload = {};
  if (scope === "common") {
    payload.strm_playback_base_url = document.getElementById("strmPlayback")?.value || "";
    payload.strm_output_root = document.getElementById("strmOutput")?.value || "";
    payload.strm_video_extensions = (document.getElementById("strmExt")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
    payload.emby_base_url = document.getElementById("strmEmbyUrl")?.value || "";
    payload.emby_strm_library_root = document.getElementById("strmEmbyRoot")?.value || "";
    payload.strm_library_root_id = document.getElementById("strmLibrary")?.value || "";
    const key = document.getElementById("strmEmbyKey")?.value?.trim();
    if (key) payload.emby_api_key = key;
  } else {
    const prefix = scope === "p115" ? "p115_strm" : "quark_strm";
    payload[`${prefix}_enabled`] = document.getElementById("strmEnabled")?.getAttribute("aria-checked") === "true";
    payload[`${prefix}_source_root`] = document.getElementById("strmRoot")?.value || "";
    payload[`${prefix}_incremental_cron`] = document.getElementById("strmCron")?.value || "";
    payload[`${prefix}_scrape_enabled`] = document.getElementById("strmScrape")?.getAttribute("aria-checked") === "true";
    payload.strm_min_file_size_mb = Number(document.getElementById("strmMinSize")?.value || 0);
    payload.strm_excluded_name_tokens = (document.getElementById("strmExclude")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
    if (scope === "p115") payload.p115_strm_life_monitor_enabled = document.getElementById("strmLife")?.getAttribute("aria-checked") === "true";
  }
  try { await api("/api/config", { method: "PUT", body: JSON.stringify(payload) }); strmState.result = { ok: true, message: "设置已保存" }; }
  catch (error) { strmState.result = { ok: false, message: error.message }; }
  await loadStrm();
}
/* ---------- media server ---------- */

const mediaState = { dashboard: null, error: "" };

function mediaPageView() {
  return `
  <div class="mi-page" id="mediaPage">
    <div class="page-head">
      <div><p class="eyebrow">EMBY · 媒体服务器</p><h1>媒体服务器</h1><p class="sub">Emby 的连接、媒体库规模、播放会话与最近入库都在这里。</p></div>
      <div class="page-actions"><button class="btn ghost sm" data-media-refresh><svg class="ic"><use href="#i-refresh"/></svg>刷新</button></div>
    </div>
    <div id="mediaBody"><div class="loading-block">正在读取 Emby 数据…</div></div>
  </div>`;
}

function mediaBodyView() {
  const dashboard = mediaState.dashboard;
  if (!dashboard) {
    return `<section class="panel panel-pad"><div class="empty-state"><b>暂时无法读取 Emby</b><span>${esc(mediaState.error || "请先在全局设置里填写 Emby 地址与 API Key。")}</span><button class="mini-btn primary" data-emby-config>配置 Emby 连接</button></div></section>`;
  }
  const libraries = dashboard.libraries || [];
  const sessions = dashboard.sessions || [];
  const latest = dashboard.latest_items || [];
  return `
  <div class="stat-strip">
    <div class="panel stat-tile"><span>服务器</span><b>${esc(dashboard.server?.name || "-")}</b><small>v${esc(dashboard.server?.version || "-")}</small></div>
    <div class="panel stat-tile"><span>媒体库</span><b>${libraries.length}<em>个</em></b><small>共 ${latest.length} 条最近入库</small></div>
    <div class="panel stat-tile"><span>播放会话</span><b>${sessions.filter((item) => item.is_playing).length}<em>路</em></b><small>${sessions.length} 个在线会话</small></div>
    <div class="panel stat-tile"><span>最近入库</span><b>${latest.length}<em>条</em></b><small>来自 Emby 最新列表</small></div>
  </div>
  <div class="split split-even">
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>媒体库</h2><small>${esc(dashboard.server?.operating_system || "")}</small></div></div>
      ${libraries.length ? `<div class="media-lib-list">${libraries.map((lib) => `<div class="media-lib-row"><b>${esc(lib.name)}</b><span>${esc(lib.collection_type || "")}</span></div>`).join("")}</div>` : `<div class="empty-state"><b>还没有媒体库</b><span>在 Emby 里创建后刷新。</span></div>`}
    </section>
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>正在播放</h2><small>实时会话</small></div></div>
      ${sessions.length ? `<div class="media-lib-list">${sessions.map((item) => `<div class="media-lib-row"><b>${esc(item.item_name || "")}</b><span>${esc(item.user_name || "")} · ${esc(item.device_name || "")}${item.is_playing ? " · 播放中" : ""}</span></div>`).join("")}</div>` : `<div class="empty-state"><b>当前没有播放</b><span>有会话时会出现在这里。</span></div>`}
    </section>
  </div>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>媒体库封面</h2><small>按媒体库生成拼贴封面，可定时刷新</small></div><button class="mini-btn" data-cover-refresh>立即刷新封面</button></div>
    <div class="form-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="field"><label>封面风格</label><select class="input" id="coverStyle">${[["collage", "拼贴"], ["showcase", "陈列"], ["mosaic", "马赛克"], ["minimal", "极简"]].map(([value, label]) => `<option value="${value}" ${(state.config?.emby_cover_style || "collage") === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>
      <div class="field"><label>刷新计划（Cron）</label><input class="input" id="coverCron" value="${esc(state.config?.emby_cover_refresh_cron || "")}" placeholder="0 4 * * *" /></div>
      <div class="field"><label>刷新间隔（小时）</label><input class="input" id="coverHours" type="number" min="1" value="${esc(state.config?.emby_cover_refresh_hours ?? 24)}" /></div>
    </div>
    <div class="field"><label>参与刷新的媒体库</label><div class="cover-libs">${libraries.map((lib) => `<label class="check"><input type="checkbox" data-cover-lib="${esc(lib.id)}" ${(state.config?.emby_cover_library_ids || []).includes(lib.id) ? "checked" : ""} />${esc(lib.name)}</label>`).join("") || `<span class="muted-note">没有可选媒体库</span>`}</div></div>
    <div class="row-actions" style="margin-top:10px"><button class="mini-btn primary" data-cover-save>保存封面设置</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>最近入库</h2><small>Emby 最近添加的内容</small></div></div>
    ${latest.length ? `<div class="media-latest-grid">${latest.map((item) => `<div class="media-latest"><b>${esc(item.name)}</b><span>${esc(item.type || "")}${item.year ? ` · ${item.year}` : ""}${item.rating ? ` · ${Number(item.rating).toFixed(1)}` : ""}</span></div>`).join("")}</div>` : `<div class="empty-state"><b>暂无最近入库</b><span>Emby 有新内容时会显示。</span></div>`}
  </section>`;
}

async function loadMedia() {
  const body = document.getElementById("mediaBody");
  if (!body) return;
  const config = await api("/api/config/status").catch(() => null);
  state.config = config || state.config;
  if (config && !config.has_emby_api_key && !config.emby_base_url) {
    mediaState.dashboard = null;
    mediaState.error = "请先在全局设置里填写 Emby 地址与 API Key。";
    body.innerHTML = mediaBodyView();
    bindMedia();
    return;
  }
  try { mediaState.dashboard = await api("/api/integrations/emby/dashboard"); mediaState.error = ""; }
  catch (error) { mediaState.dashboard = null; mediaState.error = error.message; }
  body.innerHTML = mediaBodyView();
  bindMedia();
}

async function openEmbyConfig() {
  const config = state.config || await api("/api/config/status").catch(() => ({}));
  const dialog = document.createElement("dialog");
  dialog.className = "picker-dialog";
  dialog.innerHTML = `
  <div class="picker-head"><div><h2>Emby 连接</h2><small>填写 Emby 地址与 API Key 后即可读取媒体库、会话与最近入库</small></div><button class="icon-btn" data-emby-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="form-grid" style="grid-template-columns:1fr;padding:4px 18px 0">
    <div class="field"><label>Emby 地址</label><input class="input" id="embyUrl" value="${esc(config.emby_base_url || "")}" placeholder="http://emby:8096" /></div>
    <div class="field"><label>API Key</label><input class="input" id="embyKey" type="password" placeholder="${config.has_emby_api_key ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
  </div>
  <p class="inline-result" id="embyResult" style="padding:6px 18px 0"></p>
  <div class="picker-foot"><button class="mini-btn" data-emby-test>测试连接</button><button class="mini-btn primary" data-emby-save>保存并刷新</button></div>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.querySelector("[data-emby-close]").addEventListener("click", () => dialog.close());
  const result = dialog.querySelector("#embyResult");
  const payload = () => {
    const data = { emby_base_url: dialog.querySelector("#embyUrl").value.trim() };
    const key = dialog.querySelector("#embyKey").value.trim();
    if (key) data.emby_api_key = key;
    return data;
  };
  dialog.querySelector("[data-emby-test]").addEventListener("click", async () => {
    result.textContent = "正在测试…";
    try {
      await api("/api/config", { method: "PUT", body: JSON.stringify(payload()) });
      const test = await api("/api/integrations/emby/test", { method: "POST" });
      result.textContent = test.message || (test.ok ? "连接成功" : "连接失败");
    } catch (error) { result.textContent = error.message; }
  });
  dialog.querySelector("[data-emby-save]").addEventListener("click", async () => {
    try {
      await api("/api/config", { method: "PUT", body: JSON.stringify(payload()) });
      dialog.close();
      await loadMedia();
    } catch (error) { result.textContent = error.message; }
  });
  dialog.showModal();
}
function bindMedia() {
  document.querySelector("[data-media-refresh]")?.addEventListener("click", () => void loadMedia());
  document.querySelector("[data-emby-config]")?.addEventListener("click", () => void openEmbyConfig());
  document.querySelector("[data-cover-save]")?.addEventListener("click", () => void saveCoverSettings());
  document.querySelector("[data-cover-refresh]")?.addEventListener("click", async () => {
    const button = document.querySelector("[data-cover-refresh]");
    if (button) { button.disabled = true; button.textContent = "刷新中…"; }
    try { const result = await api("/api/integrations/emby/libraries/covers/refresh", { method: "POST", body: JSON.stringify({}) }); mediaState.error = result.message || ""; }
    catch (error) { mediaState.error = error.message; }
    await loadMedia();
  });
}

async function saveCoverSettings() {
  const payload = {
    emby_cover_style: document.getElementById("coverStyle")?.value || "collage",
    emby_cover_refresh_cron: document.getElementById("coverCron")?.value || "",
    emby_cover_refresh_hours: Number(document.getElementById("coverHours")?.value || 24),
    emby_cover_refresh_enabled: Boolean(document.getElementById("coverCron")?.value),
    emby_cover_library_ids: [...document.querySelectorAll("[data-cover-lib]")].filter((input) => input.checked).map((input) => input.dataset.coverLib),
  };
  try { await api("/api/config", { method: "PUT", body: JSON.stringify(payload) }); }
  catch (error) { mediaState.error = error.message; }
  await loadMedia();
}
/* ---------- settings ---------- */

const settingsState = { tab: "overview", config: null, result: null };

const SETTINGS_TABS = [["overview", "链路概览"], ["basic", "全局设置"], ["notifications", "通知和交互"], ["network", "网络代理"], ["developer", "开发者选项"]];

function settingsPageView() {
  return `
  <div class="mi-page" id="settingsPage">
    <div class="page-head">
      <div><p class="eyebrow">SYSTEM · 系统服务</p><h1>全局设置</h1><p class="sub">服务连接、通知渠道与安全选项都收在这里；改动按页保存。</p></div>
    </div>
    <div class="chip-row" id="settingsTabs">${SETTINGS_TABS.map(([key, label]) => `<button class="chip${settingsState.tab === key ? " active" : ""}" data-settings-tab="${key}">${label}</button>`).join("")}</div>
    <div id="settingsBody"><div class="loading-block">正在读取配置…</div></div>
  </div>`;
}

function settingsOverview(config) {
  const readiness = {
    discover: Boolean(config.has_tmdb_key && config.has_pansou),
    subscriptions: Boolean(config.tracking_scheduler_enabled),
    workspace: (config.enabled_providers || []).some((item) => item === "quark" || item === "p115"),
    "cross-cloud": Boolean(config.has_openlist_token),
    strm: Boolean(config.strm_output_root && config.strm_playback_base_url),
    "media-server": Boolean(config.has_emby_api_key),
    system: Boolean(config.notification_external_enabled || config.has_telegram_token),
  };
  const ready = Object.values(readiness).filter(Boolean).length;
  const total = Object.keys(readiness).length;
  setTimeout(() => decorateOverview(readiness, ready, total), 0);
  return `<div class="chain-wrap">${OVERVIEW_HTML}</div>`;
}

function decorateOverview(readiness, ready, total) {
  const root = document.getElementById("settingsBody");
  if (!root) return;
  const isReady = (route) => readiness[route] !== false;
  root.querySelectorAll("[data-route]").forEach((node) => {
    const route = node.dataset.route;
    if (!(route in readiness)) return;
    const pill = node.querySelector(".pill") || node.parentElement?.querySelector(".pill");
    if (pill) {
      pill.className = `pill ${isReady(route) ? "ok" : "warn"}`;
      pill.innerHTML = `<i></i>${isReady(route) ? "已配置" : "待配置"}`;
    }
    if (node.tagName === "ARTICLE") {
      node.style.cursor = "pointer";
      node.addEventListener("click", (event) => {
        if (event.target.closest("button, a")) return;
        location.hash = route;
      });
    }
  });
  const score = root.querySelector(".chain-score strong");
  if (score) score.innerHTML = `${ready}<small>/${total}</small>`;
  const note = root.querySelector(".chain-score span");
  if (note) note.textContent = ready === total ? "所有关键环节均已配置" : `还有 ${total - ready} 个环节待配置`;
}
function settingsBasic(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>影视资料服务</h2><small>TMDB 提供发现、搜索和详情数据</small></div><button class="mini-btn" data-settings-test="tmdb">测试 TMDB</button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>TMDB API Key</label><input class="input" id="setTmdbKey" type="password" placeholder="${config.has_tmdb_key ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>默认执行网盘</label><select class="input" id="setDefaultProvider">${["quark", "p115"].map((p) => `<option value="${p}" ${config.default_provider === p ? "selected" : ""}>${p === "quark" ? "夸克" : "115"}</option>`).join("")}</select></div>
      <div class="field"><label>云端媒体库根路径</label><input class="input" id="setCloudRoot" value="${esc(config.cloud_root || "")}" placeholder="/媒体库" /></div>
      <div class="field"><label>QAS 根路径</label><input class="input" id="setQasRoot" value="${esc(config.qas_root || "")}" placeholder="/媒体库" /></div>
      <div class="field"><label>本地根路径</label><input class="input" id="setLocalRoot" value="${esc(config.local_root || "")}" /></div>
    </div>
    <div class="switch-row"><div><b>包含成人内容</b><small>仅影响发现页的筛选结果</small></div><button class="switch" id="setAdult" aria-checked="${config.tmdb_adult_content_enabled ? "true" : "false"}" aria-label="包含成人内容"></button></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="basic">保存本页设置</button>${settingsResult()}</div>
  </section>`;
}

function settingsNotifications(config) {
  const events = [["transfer_success", "转存完成"], ["library", "Emby 入库完成"], ["review", "需要确认"], ["no_resource", "暂无资源"], ["failure", "处理失败"], ["playback", "播放事件"]];
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>推送总开关</h2><small>启用后，新产生的转存结果和待处理事项会发送到已启用的渠道</small></div></div>
    <div class="switch-row"><div><b>外部消息推送</b><small>总开关</small></div><button class="switch" id="setPushEnabled" aria-checked="${config.notification_external_enabled ? "true" : "false"}" aria-label="外部消息推送"></button></div>
    <div class="field"><label>公网访问地址</label><input class="input" id="setPublicUrl" value="${esc(config.public_base_url || "")}" placeholder="https://media.example.com" /></div>
    <div class="push-event-list">${events.map(([key, label]) => `<label class="check"><input type="checkbox" data-event="${key}" ${(config.notification_event_types || []).includes(key) ? "checked" : ""} />${label}</label>`).join("")}</div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="notifications">保存推送设置</button>${settingsResult()}</div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>Telegram</h2><small>通过 Bot API 发送通知，也能接收资源名与按钮操作</small></div><button class="mini-btn" data-settings-test="telegram">测试 Telegram</button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>Bot Token</label><input class="input" id="setTelegramToken" type="password" placeholder="${config.has_telegram_token ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>Chat ID</label><input class="input" id="setTelegramChat" value="${esc(config.telegram_chat_id || "")}" /></div>
      <div class="field"><label>API 地址</label><input class="input" id="setTelegramHost" value="${esc(config.telegram_api_host || "")}" placeholder="https://api.telegram.org" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="telegram">保存 Telegram</button></div>
  </section>`;
}

function settingsNetwork(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>网络代理</h2><small>用于访问 TMDB 等外部服务</small></div><button class="mini-btn" data-settings-test="proxy">测试代理</button></div>
    <div class="field"><label>代理地址</label><input class="input" id="setProxy" value="${esc(config.proxy_url || "")}" placeholder="http://127.0.0.1:7890" /></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="network">保存代理</button>${settingsResult()}</div>
  </section>`;
}

function settingsDeveloper(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>配置导出</h2><small>导出设置与任务数据，便于迁移或备份</small></div></div>
    <div class="row-actions"><button class="mini-btn primary" data-settings-export>导出配置 JSON</button><label class="mini-btn">导入配置<input type="file" accept="application/json,.json" data-settings-import hidden /></label></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>运行状态</h2><small>当前后端配置快照</small></div></div>
    <pre class="code-block" id="settingsSnapshot">${esc(JSON.stringify(config, null, 2).slice(0, 4000))}</pre>
  </section>`;
}

function settingsWecom(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>企业微信应用</h2><small>通过自建应用定向发送消息，可开启成员交互指令</small></div><button class="mini-btn" data-settings-test="wecom_app">测试企业微信</button></div>
    <div class="switch-row"><div><b>启用自建应用</b><small>需要企业微信后台的应用凭据</small></div><button class="switch" id="setWecomAppEnabled" aria-checked="${config.wecom_app_enabled ? "true" : "false"}" aria-label="启用企业微信应用"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>企业 ID（CorpID）</label><input class="input" id="setWecomCorp" value="${esc(config.wecom_corp_id || "")}" /></div>
      <div class="field"><label>应用 Secret</label><input class="input" id="setWecomSecret" type="password" placeholder="${config.has_wecom_app_secret ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>应用 AgentID</label><input class="input" id="setWecomAgent" type="number" value="${esc(config.wecom_app_agent_id ?? "")}" /></div>
      <div class="field"><label>接收成员（UserID）</label><input class="input" id="setWecomUser" value="${esc(config.wecom_app_to_user || "")}" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="wecom_app">保存企业微信</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>企微机器人</h2><small>使用群聊机器人 Webhook，消息固定发送到机器人所在群聊</small></div><button class="mini-btn" data-settings-test="wecom">测试机器人</button></div>
    <div class="switch-row"><div><b>启用群机器人</b><small>只需 Webhook Key</small></div><button class="switch" id="setWecomEnabled" aria-checked="${config.wecom_enabled ? "true" : "false"}" aria-label="启用企微机器人"></button></div>
    <div class="field"><label>机器人 Webhook Key</label><input class="input" id="setWecomKey" type="password" placeholder="${config.has_wecom_key ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="wecom_bot">保存机器人</button></div>
  </section>`;
}
function settingsResult() {
  return settingsState.result ? `<span class="inline-result ${settingsState.result.ok ? "ok" : "error"}">${esc(settingsState.result.message)}</span>` : "";
}

function renderSettingsBody() {
  const body = document.getElementById("settingsBody");
  if (!body || !settingsState.config) return;
  const config = settingsState.config;
  const views = { overview: settingsOverview, basic: settingsBasic, notifications: settingsNotifications, network: settingsNetwork, developer: settingsDeveloper };
  body.innerHTML = (views[settingsState.tab] || settingsOverview)(config);
  if (settingsState.tab === "notifications") body.insertAdjacentHTML("beforeend", settingsWecom(config));
  bindSettings();
}

async function loadSettings() {
  const body = document.getElementById("settingsBody");
  if (body) body.innerHTML = `<div class="loading-block">正在读取配置…</div>`;
  settingsState.config = await api("/api/config/status").catch(() => null);
  state.config = settingsState.config || state.config;
  if (!settingsState.config) { body.innerHTML = `<section class="panel panel-pad"><div class="empty-state"><b>配置读取失败</b><span>请稍后重试</span></div></section>`; return; }
  renderSettingsBody();
}

function bindSettings() {
  document.querySelectorAll("[data-settings-tab]").forEach((button) => button.addEventListener("click", () => {
    settingsState.tab = button.dataset.settingsTab;
    settingsState.result = null;
    document.querySelectorAll("[data-settings-tab]").forEach((chip) => chip.classList.toggle("active", chip.dataset.settingsTab === settingsState.tab));
    renderSettingsBody();
  }));
  document.querySelectorAll(".switch").forEach((button) => button.addEventListener("click", () => button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true")));
  document.querySelectorAll("[data-settings-save]").forEach((button) => button.addEventListener("click", () => void saveSettings(button.dataset.settingsSave)));
  document.querySelectorAll("[data-settings-test]").forEach((button) => button.addEventListener("click", () => void testSettings(button.dataset.settingsTest)));
  document.querySelector("[data-settings-export]")?.addEventListener("click", () => void exportSettings());
  document.querySelector("[data-settings-import]")?.addEventListener("change", (event) => { const file = event.target.files?.[0]; if (file) void importSettingsFile(file); });
}

async function importSettingsFile(file) {
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    if (!payload || typeof payload !== "object") throw new Error("文件不是有效的配置 JSON");
    if (!confirm("导入会覆盖当前设置与任务数据，确定继续？")) return;
    const result = await api("/api/config/import", { method: "POST", body: JSON.stringify(payload) });
    settingsState.result = { ok: Boolean(result.ok), message: result.message || "配置已导入" };
  } catch (error) { settingsState.result = { ok: false, message: error.message }; }
  await loadSettings();
}

async function saveSettings(scope) {
  const payload = {};
  if (scope === "basic") {
    const key = document.getElementById("setTmdbKey")?.value?.trim();
    if (key) payload.tmdb_api_key = key;
    payload.default_provider = document.getElementById("setDefaultProvider")?.value || "quark";
    payload.cloud_root = document.getElementById("setCloudRoot")?.value || "";
    payload.qas_root = document.getElementById("setQasRoot")?.value || "";
    payload.local_root = document.getElementById("setLocalRoot")?.value || "";
    payload.tmdb_adult_content_enabled = document.getElementById("setAdult")?.getAttribute("aria-checked") === "true";
  } else if (scope === "notifications") {
    payload.notification_external_enabled = document.getElementById("setPushEnabled")?.getAttribute("aria-checked") === "true";
    payload.public_base_url = document.getElementById("setPublicUrl")?.value || "";
    payload.notification_event_types = [...document.querySelectorAll("[data-event]")].filter((input) => input.checked).map((input) => input.dataset.event);
  } else if (scope === "telegram") {
    const token = document.getElementById("setTelegramToken")?.value?.trim();
    if (token) payload.telegram_token = token;
    payload.telegram_chat_id = document.getElementById("setTelegramChat")?.value || "";
    payload.telegram_api_host = document.getElementById("setTelegramHost")?.value || "";
    payload.telegram_enabled = true;
  } else if (scope === "wecom_app") {
    payload.wecom_app_enabled = document.getElementById("setWecomAppEnabled")?.getAttribute("aria-checked") === "true";
    payload.wecom_corp_id = document.getElementById("setWecomCorp")?.value || "";
    payload.wecom_app_agent_id = Number(document.getElementById("setWecomAgent")?.value || 0);
    payload.wecom_app_to_user = document.getElementById("setWecomUser")?.value || "";
    const secret = document.getElementById("setWecomSecret")?.value?.trim();
    if (secret) payload.wecom_app_secret = secret;
  } else if (scope === "wecom_bot") {
    payload.wecom_enabled = document.getElementById("setWecomEnabled")?.getAttribute("aria-checked") === "true";
    const key = document.getElementById("setWecomKey")?.value?.trim();
    if (key) payload.wecom_key = key;
  } else if (scope === "network") {
    payload.proxy_url = document.getElementById("setProxy")?.value || "";
  }
  try { await api("/api/config", { method: "PUT", body: JSON.stringify(payload) }); settingsState.result = { ok: true, message: "设置已保存" }; }
  catch (error) { settingsState.result = { ok: false, message: error.message }; }
  await loadSettings();
}

async function testSettings(kind) {
  if (kind === "wecom_app" || kind === "wecom") {
    try { const result = await api(`/api/notifications/test/${kind}`, { method: "POST" }); settingsState.result = { ok: Boolean(result.ok), message: result.message || "验证完成" }; }
    catch (error) { settingsState.result = { ok: false, message: error.message }; }
    await loadSettings();
    return;
  }
  const endpoints = { tmdb: "/api/config/test-tmdb", telegram: "/api/config/test-telegram-bot", proxy: "/api/config/test-proxy" };
  try {
    const result = await api(endpoints[kind], { method: "POST", body: kind === "proxy" ? JSON.stringify({ proxy_url: document.getElementById("setProxy")?.value || "" }) : undefined });
    settingsState.result = { ok: Boolean(result.ok), message: result.message || "验证完成" };
  } catch (error) { settingsState.result = { ok: false, message: error.message }; }
  await loadSettings();
}

async function exportSettings() {
  try {
    const data = await api("/api/config/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `mediaindex-config-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
    settingsState.result = { ok: true, message: "配置已导出" };
  } catch (error) { settingsState.result = { ok: false, message: error.message }; }
  renderSettingsBody();
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
  if (state.route === "workspace") {
    root.innerHTML = shell(wsPageView());
    bindShell();
    await loadWs();
    return;
  }
  if (state.route === "cross-cloud") {
    root.innerHTML = shell(crossPageView());
    bindShell();
    await loadCross();
    return;
  }
  if (state.route === "strm") {
    root.innerHTML = shell(strmPageView());
    bindShell();
    await loadStrm();
    return;
  }
  if (state.route === "media-server") {
    root.innerHTML = shell(mediaPageView());
    bindShell();
    await loadMedia();
    return;
  }
  if (state.route === "guide") {
    root.innerHTML = shell(`<section class="page active">${GUIDE_HTML}</section>`);
    bindShell();
    bindGuide();
    return;
  }
  if (state.route === "system") {
    root.innerHTML = shell(settingsPageView());
    bindShell();
    await loadSettings();
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

function bindGuide() {
  const toc = document.getElementById("guideToc");
  if (!toc) return;
  toc.querySelectorAll("[data-chapter]").forEach((button) => button.addEventListener("click", () => {
    const chapter = button.dataset.chapter;
    toc.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".guide-chapter").forEach((panel) => panel.classList.toggle("active", panel.dataset.chapter === chapter));
  }));
}

function bindShell() {
  bindAppearance();
  bindNotice();
  document.querySelector("[data-menu]")?.addEventListener("click", () => document.querySelector(".app")?.classList.toggle("menu-open"));
  document.querySelector("[data-menu-close]")?.addEventListener("click", () => document.querySelector(".app")?.classList.remove("menu-open"));
  document.querySelectorAll("[data-discover-section]").forEach((button) => button.addEventListener("click", () => { discoverState.section = button.dataset.discoverSection; document.querySelectorAll("[data-discover-section]").forEach((chip) => chip.classList.toggle("active", chip.dataset.discoverSection === discoverState.section)); void loadDiscover(); }));
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
