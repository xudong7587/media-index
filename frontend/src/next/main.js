import "./preview.css";
const WEBHOOK_CHAIN_HTML = `
<section class="panel chain-block">
  <header class="chain-head"><div class="chain-num alt">03</div><div><h2>Webhook 与通知</h2><p>外部事件进入后触发入库，并按事件类型推送通知</p></div><span class="chain-tag">可选链路</span></header>
  <div class="chain-body">
    <div class="chain-entries">
      <article class="entry-card"><div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-cloud"/></svg></span><span class="pill ok"><i></i>可配置</span></div><small>Webhook</small><b>MDC-NG 推送</b><p>接收下载完成事件，进入转存与入库队列。</p><button class="link" type="button" data-route="workspace" data-ws-section="webhook">打开 Webhook<svg class="ic"><use href="#i-arrow"/></svg></button></article>
      <article class="entry-card"><div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-bell"/></svg></span><span class="pill ok"><i></i>可配置</span></div><small>通知</small><b>事件推送</b><p>转存完成、入库完成、失败与待确认事件推送到 Telegram / 企业微信。</p><button class="link" type="button" data-route="system">打开通知<svg class="ic"><use href="#i-arrow"/></svg></button></article>
    </div>
  </div>
</section>`;

import "./next.css";
import { GUIDE_HTML } from "./guide.js";
import { OVERVIEW_HTML } from "./overview.js";
import QRCode from "qrcode";
import { THEME_DATA } from "./theme-data.js";

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
  root.dataset.color = state.accent;
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
  const theme = state.theme;
  return `
  <div class="pop-head"><div><strong>外观</strong><small>${esc(appearanceLabel())}</small></div><button class="pop-close" data-appearance-close aria-label="关闭外观面板"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="pop-group"><span>明暗</span><div class="seg" data-group="theme">
    <button data-theme-value="light" aria-pressed="${theme !== "dark"}">浅色</button>
    <button data-theme-value="dark" aria-pressed="${theme === "dark"}">深色</button>
  </div></div>
  <div class="pop-group"><span>圆角</span><div class="seg" data-group="corner">
    ${[["tight", "紧致"], ["default", "标准"], ["round", "圆润"]].map(([value, label]) => `<button data-corner-value="${value}" aria-pressed="${state.corner === value}">${label}</button>`).join("")}
  </div></div>
  <div class="pop-group"><span>质感 · ${THEME_DATA.MATERIALS.length} 种</span><div class="mat-grid">
    ${THEME_DATA.MATERIALS.map((item) => `<button class="mat-opt" type="button" role="radio" aria-checked="${state.material === item.id}" data-material-value="${item.id}" title="${esc(item.note || item.name)}"><span class="ms" style="${item.sample}"></span><b>${esc(item.name)}</b></button>`).join("")}
  </div></div>
  <div class="pop-group"><span>单色 · 主色决定强调与选中</span><div class="col-row">
    ${THEME_DATA.SINGLE.map((item) => {
      const from = theme === "dark" ? item.dark : item.light;
      const to = theme === "dark" ? item.light : item.dark;
      return `<button class="sw" type="button" data-accent-value="${item.id}" aria-checked="${state.accent === item.id}" title="${esc(item.name)}" aria-label="${esc(item.name)}" style="--sw:linear-gradient(135deg,${from},${to})"></button>`;
    }).join("")}
  </div></div>
  <div class="pop-group"><span>多色 · 主色 / 辅色 / 点缀</span><div class="col-row">
    ${THEME_DATA.MULTI.map((item) => {
      const colors = theme === "dark" ? item.dark : item.light;
      const [a, b, c] = Array.isArray(colors) ? colors : [colors, colors, colors];
      return `<button class="sw wheel" type="button" data-accent-value="${item.id}" aria-checked="${state.accent === item.id}" title="${esc(item.name)}" aria-label="${esc(item.name)}" style="--sw:conic-gradient(${a},${b},${c},${a})"></button>`;
    }).join("")}
  </div></div>
  <p class="pop-foot">质感换表面，配色换颜料，两者互不覆盖。</p>`;
}

function appearanceLabel() {
  const material = THEME_DATA.MATERIALS.find((item) => item.id === state.material);
  const accent = [...THEME_DATA.SINGLE, ...THEME_DATA.MULTI].find((item) => item.id === state.accent);
  return `${material ? material.name : "质感"} · ${accent ? accent.name : "配色"}`;
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
  kind: "movie",
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
  ["douban", "豆瓣高分", "豆", "", "#2e7d32"],
  ["netflix", "Netflix", "N", "8", "#e50914"],
  ["max", "HBO Max", "H", "1899", "#5b21b6"],
  ["apple", "Apple TV+", "A", "350", "#3a3a3c"],
  ["disney", "Disney+", "D+", "337", "#1a4b8c"],
  ["prime", "Prime Video", "P", "119", "#0f7fbf"],
  ["amazon", "Amazon", "a", "10", "#ff9900"],
  ["hulu", "Hulu", "h", "15", "#1ce783"],
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
    <div id="discoverBody"><div class="loading-block">正在读取 TMDB 内容…</div></div>
  </div>`;
}

function renderDiscoverFilters() {
  const node = document.getElementById("discoverFilters");
  if (!node) return;
  if (discoverState.section !== "explore") { node.innerHTML = ""; return; }
  node.innerHTML = `<div class="filter-row">
    <div class="chip-row">
      ${MEDIA_TYPES.map(([key, label]) => `<button class="chip${discoverState.mediaType === key ? " active" : ""}" data-media="${key}">${label}</button>`).join("")}
      <span class="divider"></span>
      ${REGIONS.map(([key, label]) => `<button class="chip${discoverState.region === key ? " active" : ""}" data-region="${key}">${label}</button>`).join("")}
    </div>
    <button class="chip mini" data-discover-download><svg class="ic ic-sm" style="vertical-align:-3px;margin-right:5px"><use href="#i-link"/></svg>链接下载</button>
    <button class="chip mini" data-discover-refresh><svg class="ic ic-sm" style="vertical-align:-3px;margin-right:5px"><use href="#i-refresh"/></svg>刷新内容</button>
  </div>`;
  bindDiscoverFilters();
}

function bindDiscoverFilters() {
  document.querySelector("[data-discover-refresh]")?.addEventListener("click", () => void loadDiscover(true));
  document.querySelector("[data-discover-download]")?.addEventListener("click", () => { discoverState.section = "download"; void loadDiscover(); });
  document.querySelector("[data-discover-back]")?.addEventListener("click", () => { discoverState.section = "explore"; void loadDiscover(); });
  document.querySelectorAll("[data-media]").forEach((button) => button.addEventListener("click", () => { discoverState.mediaType = button.dataset.media; void loadDiscover(); }));
  document.querySelectorAll("[data-region]").forEach((button) => button.addEventListener("click", () => { discoverState.region = button.dataset.region; void loadDiscover(); }));
  document.querySelectorAll("[data-platform]").forEach((button) => button.addEventListener("click", () => { discoverState.platform = button.dataset.platform; void loadRankings(); }));
  document.querySelectorAll("[data-rank-kind]").forEach((button) => button.addEventListener("click", () => { discoverState.kind = button.dataset.rankKind; void loadRankings(); }));
  document.querySelectorAll("[data-rank-region]").forEach((button) => button.addEventListener("click", () => { discoverState.region = button.dataset.rankRegion.toLowerCase(); void loadRankings(); }));
}

function canTrackMedia(item) { return item.media_type !== "movie"; }

function posterCard(item) {
  return `<button class="rail-card" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}">
    <span class="poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}"></span>
    <strong>${esc(item.title)}</strong><span>${esc(metaLine(item))}</span>
  </button>`;
}

function railSection(title, subtitle, items, key) {
  if (!items.length) return "";
  return `<section class="discover-rail" data-rail="${key}">
    <header><div><h2>${esc(title)}</h2></div></header>
    <div class="rail-track" data-track="${key}">${items.map(posterCard).join("")}</div>
  </section>`;
}

function sideRail() {
  const active = discoverState.tracking.filter((task) => task.status !== "archived");
  const pending = active.reduce((sum, task) => sum + Math.max(0, (task.episode_count || 0) - (task.saved_count || 0)), 0);
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  const items = active.slice(0, 3).map((task) => {
    const total = task.episode_count || 0;
    const saved = task.saved_count || 0;
    const percent = total ? Math.min(100, Math.round((saved / total) * 100)) : 0;
    const art = ["art-teal", "art-rose", "art-violet"][active.indexOf(task) % 3];
    return `<div class="track-item">
      <span class="thumb ${posterUrl(task) ? "" : art}" style="${posterUrl(task) ? `background-image:url(${esc(posterUrl(task))});background-size:cover;background-position:center` : ""}"></span>
      <div class="track-copy">
        <strong>${esc(task.title)}</strong>
        <small>S${String(task.season_number || 1).padStart(2, "0")}E${String(task.last_saved_episode || saved).padStart(2, "0")} / ${total || "?"}${task.next_check_at ? ` · 下次巡检 ${esc(formatDate(task.next_check_at).slice(11, 16))}` : ""}</small>
        <div class="bar"><i style="width:${percent}%"></i></div>
      </div>
    </div>`;
  }).join("");
  return `<div class="side-stack">
    <section class="panel track-card">
      <div class="card-head"><div><h2>追更看板</h2><small>按巡检周期自动核对集数</small></div><span class="count-pill"><i></i>${active.length} 部在追</span></div>
      <div class="track-list">${items || `<p class="muted-note">还没有追更任务</p>`}</div>
      <div class="track-more"><span>待补 ${pending} 集</span><button class="link" type="button" data-route="subscriptions">查看全部<svg class="ic"><use href="#i-arrow"/></svg></button></div>
    </section>
    <section class="panel stat-card">
      <div class="card-head" style="margin-bottom:4px"><div><h2>今日概览</h2><small>本地时间 ${now}</small></div></div>
      <div class="stat-grid">
        <div class="stat"><b>${pending}</b><span>待补集数</span></div>
        <div class="stat"><b>${active.length}</b><span>在追作品</span></div>
        <div class="stat"><b>${discoverState.wishlist.length}</b><span>愿望单</span></div>
      </div>
    </section>
  </div>`;
}

function renderExplore() {
  const body = document.getElementById("discoverBody");
  const groups = discoverState.groups;
  const features = [];
  for (const group of groups) for (const item of group.items) {
    if (item.backdrop_url && !features.some((entry) => entry.tmdb_id === item.tmdb_id && entry.media_type === item.media_type)) features.push(item);
    if (features.length >= 7) break;
  }
  const index = features.length ? discoverState.featureIndex % features.length : 0;
  body.innerHTML = `
  <div class="hero-row">
    ${features.length ? `<section class="hero" id="hero" aria-roledescription="轮播" aria-label="精选推荐">
      ${features.map((item, i) => `<article class="hero-slide ${i === index ? "is-active" : ""}" aria-hidden="${i !== index}">
        <div class="hero-art" style="${backdropUrl(item) ? `background-image:url(${esc(backdropUrl(item))})` : ""}"></div>
        <div class="hero-index"><b>${String(i + 1).padStart(2, "0")}</b>/ ${String(features.length).padStart(2, "0")}</div>
        <div class="hero-copy">
          <span class="hero-eyebrow">MEDIA DISCOVERY</span>
          <h2>${esc(item.title)}</h2>
          <div class="hero-meta">
            <span class="score"><svg class="ic ic-fill ic-sm"><use href="#i-star"/></svg>${item.vote_average ? Number(item.vote_average).toFixed(1) : "待评分"}</span>
            <span>${esc(item.year || "")}</span><span>${item.media_type === "movie" ? "电影" : "电视剧"}</span>
          </div>
          <p>${esc(item.overview || "从推荐内容中选择作品，进入详情核对 TMDB 信息并发起资源任务。")}</p>
          <div class="hero-actions">
            <button class="btn primary on-hero" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}">查看作品<svg class="ic"><use href="#i-arrow"/></svg></button>
            <button class="btn ghost on-hero" data-track="${esc(item.media_type)}:${esc(item.tmdb_id)}"><svg class="ic"><use href="#i-plus"/></svg>加入智能追更</button>
          </div>
        </div>
      </article>`).join("")}
      <div class="hero-controls">
        <button class="hero-nav" data-hero="-1" aria-label="上一张"><svg class="ic ic-sm"><use href="#i-chev-l"/></svg></button>
        <div class="dots" role="tablist" aria-label="选择推荐">${features.map((_, i) => `<button class="dot" role="tab" aria-selected="${i === index}" aria-label="第 ${i + 1} 张" data-hero-dot="${i}"></button>`).join("")}</div>
        <button class="hero-nav" data-hero="1" aria-label="下一张"><svg class="ic ic-sm"><use href="#i-chev-r"/></svg></button>
      </div>
    </section>` : `<section class="hero"><div class="hero-copy"><h2>暂无推荐内容</h2><p>请先在全局设置中配置 TMDB API Key。</p></div></section>`}
    ${sideRail()}
  </div>
  <div class="toolbar">
    <div class="chips" role="tablist" aria-label="内容类型">
      ${MEDIA_TYPES.map(([key, label]) => `<button class="chip${discoverState.mediaType === key ? " active" : ""}" data-media="${key}">${label}</button>`).join("")}
      <span class="divider"></span>
      ${REGIONS.map(([key, label]) => `<button class="chip${discoverState.region === key ? " active" : ""}" data-region="${key}">${label}</button>`).join("")}
    </div>
    <span class="spacer"></span>
    <button class="chip mini" data-discover-download><svg class="ic ic-sm" style="vertical-align:-3px;margin-right:5px"><use href="#i-link"/></svg>链接下载</button>
    <button class="chip mini" data-discover-refresh><svg class="ic ic-sm" style="vertical-align:-3px;margin-right:5px"><use href="#i-refresh"/></svg>刷新内容</button>
  </div>
  ${railSection("正在热播", "近期最受关注的电影与节目", groups.find((group) => group.key === "hot")?.items || [], "hot")}
  ${railSection("口碑精选", "按 TMDB 评分发现值得看的作品", groups.find((group) => group.key === "rating")?.items || [], "rating")}
  ${railSection("最近上线", "浏览最近上映和更新的内容", groups.find((group) => group.key === "latest")?.items || [], "latest")}
  ${rankingInlineHtml()}`;
  bindDiscover();
  bindRankInline();
  bindDiscoverFilters();
  startHeroTimer(features.length);
}

function rankingInlineHtml() {
  const items = discoverState.rankings;
  return `<section class="panel ranking">
    <header class="rank-head">
      <div><p class="eyebrow">STREAMING CHART</p><h2>流媒体热映榜</h2><p>按地区与平台查看 TMDB 当前热度，直接加入追更或发起转存。</p></div>
      <div class="rank-source"><span>本次榜单</span><strong>${items.length}<em>部</em></strong></div>
    </header>
    <div class="rank-body">
      <div class="platforms" role="tablist" aria-label="流媒体平台">
        ${RANK_PLATFORMS.map(([key, label, mark, provider, brand]) => `<button class="platform${discoverState.platform === key ? " active" : ""}" role="tab" aria-selected="${discoverState.platform === key}" data-platform="${key}"><i style="--brand:${brand || "#3b4fa8"}">${mark}</i><span>${label}<small>${provider === "douban" ? "华语 · 评分" : "TMDB · 热度"}</small></span></button>`).join("")}
      </div>
      <div class="rank-list">
        ${items.map((item, index) => `<div class="rank-row" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}">
          <span class="n">${String(index + 1).padStart(2, "0")}</span>
          <span class="rank-art" style="${(backdropUrl(item) || posterUrl(item)) ? `background-image:url(${esc(backdropUrl(item) || posterUrl(item))})` : ""}"></span>
          <span class="rank-copy"><strong>${esc(item.title)}</strong><small>${esc(metaLine(item))}</small><span class="heat"><i style="width:${item.vote_average ? Math.min(96, Math.round(Number(item.vote_average) * 10)) : 45}%"></i></span></span>
          <span class="rank-score"><svg class="ic ic-fill"><use href="#i-star"/></svg>${item.vote_average ? Number(item.vote_average).toFixed(1) : "-"}</span>
          ${canTrackMedia(item) ? `<button class="rank-act" data-track="${esc(item.media_type)}:${esc(item.tmdb_id)}">追更</button>` : `<button class="rank-act" data-detail="${esc(item.media_type)}:${esc(item.tmdb_id)}">资源</button>`}
        </div>`).join("") || `<div class="empty-state"><b>榜单加载中…</b><span>如果长时间没有内容，检查 TMDB 配置。</span></div>`}
      </div>
    </div>
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
  const block = document.querySelector("section.ranking");
  if (block) { block.outerHTML = rankingInlineHtml(); bindRankInline(); }
}

function bindRankInline() {
  document.querySelectorAll("[data-platform]").forEach((button) => button.addEventListener("click", () => { discoverState.platform = button.dataset.platform; void loadRankingsInline(); }));
  document.querySelectorAll("[data-detail]").forEach((button) => button.addEventListener("click", () => { const [type, tmdb] = button.dataset.detail.split(":"); void openDetail(type, Number(tmdb)); }));
  document.querySelectorAll(".rank-act[data-track]").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); const [type, tmdb] = button.dataset.track.split(":"); void quickTrack(type, Number(tmdb)); }));
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
    <span class="poster rank-poster${posterUrl(item) ? "" : " poster-fallback"}" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))})` : ""}">${posterUrl(item) ? "" : esc((item.title || "?").slice(0, 1))}</span>
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
    <div class="panel-head"><div><button class="link" type="button" data-discover-back>← 返回发现</button><h2>粘贴链接下载</h2><small>夸克分享链接进入夸克云下载目录；115 分享、磁力、电驴和普通下载链接进入 115 云下载目录。</small></div></div>
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
  bindDiscoverFilters();
}

function bindDiscover() {
  document.querySelectorAll("[data-detail]").forEach((button) => button.addEventListener("click", () => { const [type, tmdb] = button.dataset.detail.split(":"); void openDetail(type, Number(tmdb)); }));
  document.querySelectorAll("[data-hero]").forEach((button) => button.addEventListener("click", () => { discoverState.featureIndex += Number(button.dataset.hero); renderExplore(); }));
  document.querySelectorAll("[data-hero-dot]").forEach((dot) => dot.addEventListener("click", () => { discoverState.featureIndex = Number(dot.dataset.heroDot); renderExplore(); }));
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

async function loadDiscover(refresh = false) {
  const body = document.getElementById("discoverBody");
  if (discoverState.section === "download") { renderDownload(); return; }
  if (body) body.innerHTML = `<div class="loading-block">正在读取 TMDB 内容…</div>`;
  if (discoverState.section === "rankings") return loadRankings();
  const [hot, rating, latest, tracking] = await Promise.all([
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=hot&genre=&vote_min=0&page=1&page_size=14&refresh=${refresh}&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=rating&genre=&vote_min=0&page=1&page_size=14&refresh=${refresh}&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api(`/api/discover?media_type=${discoverState.mediaType}&region=${discoverState.region}&sort=latest&genre=&vote_min=0&page=1&page_size=14&refresh=${refresh}&watch_provider=&watch_region=US`).catch(() => ({ results: [] })),
    api("/api/tracking").catch(() => []),
  ]);
  discoverState.groups = [{ key: "hot", items: hot.results || [] }, { key: "rating", items: rating.results || [] }, { key: "latest", items: latest.results || [] }];
  discoverState.tracking = Array.isArray(tracking) ? tracking : [];
  discoverState.featureIndex = 0;
  renderExplore();
  void loadRankingsInline();
}

async function loadRankings() {
  const body = document.getElementById("discoverBody");
  if (body) body.innerHTML = `<div class="loading-block">正在读取榜单…</div>`;
  const platform = RANK_PLATFORMS.find(([key]) => key === discoverState.platform) || RANK_PLATFORMS[0];
  const region = discoverState.region ? discoverState.region.toUpperCase() : "US";
  const types = discoverState.kind === "all" ? ["movie", "tv"] : [discoverState.kind];
  try {
    const responses = await Promise.all(types.map((type) => platform[0] === "douban"
    ? api(`/api/discover?media_type=${type}&region=cn&sort=rating&genre=&vote_min=0&page=1&page_size=${discoverState.kind === "all" ? 10 : 20}&refresh=${refresh}&watch_provider=&watch_region=US`)
    : api(`/api/discover?media_type=${type}&region=&sort=hot&genre=&vote_min=0&page=1&page_size=${discoverState.kind === "all" ? 10 : 20}&refresh=${refresh}&watch_provider=${platform[3]}&watch_region=${region}`)));
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
      <button class="icon-btn close-btn" data-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button>
      <div class="detail-body">
        <div class="detail-poster" style="${posterUrl(item) ? `background-image:url(${esc(posterUrl(item))});background-size:cover;background-position:center` : ""}">
          <span class="hero-eyebrow">TMDB · COLLECTION</span>
        </div>
        <div class="detail-copy">
          <h2>${esc(item.title)}</h2>
          <div class="detail-meta">
            <span class="score"><svg class="ic ic-fill ic-sm"><use href="#i-star"/></svg>${item.vote_average ? Number(item.vote_average).toFixed(1) : "待评分"}</span>
            <span>${esc(item.year || "")}</span><span>${item.media_type === "movie" ? "电影" : "电视剧"}</span>
          </div>
          <p>${esc(item.overview || "暂无简介。")}</p>
          <div class="detail-facts">
            <div><span>媒体类型</span><strong>${item.media_type === "movie" ? "电影" : "电视剧"}</strong></div>
            <div><span>资源状态</span><strong class="ok"><i></i>可发起资源检索</strong></div>
          </div>
          <div class="detail-actions">
            ${canTrackMedia(item) ? `<button class="btn primary" data-detail-track><svg class="ic"><use href="#i-cloud"/></svg>加入智能追更</button>` : `<button class="btn primary" data-detail-resource><svg class="ic"><use href="#i-search"/></svg>搜索资源</button>`}
            <button class="btn ghost" data-close><svg class="ic"><use href="#i-close"/></svg>关闭</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    dialog.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    dialog.querySelector("[data-detail-track]")?.addEventListener("click", () => { void quickTrack(item.media_type, item.tmdb_id); dialog.close(); });
    dialog.querySelector("[data-detail-resource]")?.addEventListener("click", () => { const input = document.getElementById("searchInput"); if (input) input.value = item.title; dialog.close(); });
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
  ${channels.length ? `<div class="list">${channels.map((item) => `
    <div class="list-row" data-channel="${esc(item.channel_id)}">
      <div class="grow"><b>${esc(item.display_name || item.channel_id)}</b><small>${esc(item.channel_id)}${item.last_checked_at ? ` · 上次 ${esc(formatDate(item.last_checked_at))}` : ""}${item.last_error ? ` · ${esc(item.last_error)}` : ""}</small></div>
      <span class="pill ${item.enabled ? "ok" : "muted"}"><i></i>${item.enabled ? "已启用" : "已停用"}</span>
      <button class="switch" data-channel-toggle="${esc(item.channel_id)}" aria-checked="${item.enabled ? "true" : "false"}" aria-label="启用频道"></button>
      <button class="mini-btn" data-channel-edit="${esc(item.channel_id)}">设置</button><button class="mini-btn" data-channel-sync="${esc(item.channel_id)}">同步</button>
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

function openChannelEditor(item) {
  const dialog = document.createElement("dialog");
  dialog.className = "picker-dialog channel-editor";
  dialog.innerHTML = `
  <div class="picker-head"><div><h2>频道规则</h2><small>${esc(item.display_name || item.channel_id)} · 修改只影响当前频道</small></div><button class="icon-btn" data-editor-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr));padding:0 18px">
    <div class="field"><label>显示名称</label><input class="input" id="chName" value="${esc(item.display_name || "")}" /></div>
    <div class="field"><label>云下载子目录</label><input class="input" id="chChild" value="${esc(item.cloud_download_child || "")}" /></div>
    <div class="field"><label>必须包含（正向词）</label><input class="input" id="chPositive" value="${esc((item.positive_keywords || []).join(","))}" /></div>
    <div class="field"><label>必须排除（反向词）</label><input class="input" id="chNegative" value="${esc((item.negative_keywords || []).join(","))}" /></div>
    <div class="field"><label>豆瓣标题匹配</label><input class="input" id="chDouban" value="${esc((item.douban_titles || []).join("\n"))}" placeholder="每行一个标题" /></div>
  </div>
  <div class="switch-row" style="padding:0 18px"><div><b>启用频道</b><small>关闭后不再抓取</small></div><button class="switch" id="chEnabled" aria-checked="${item.enabled}" aria-label="启用频道"></button></div>
  <div class="switch-row" style="padding:0 18px"><div><b>自动转存</b><small>命中规则后直接转存</small></div><button class="switch" id="chAutoTransfer" aria-checked="${item.auto_transfer}" aria-label="自动转存"></button></div>
  <div class="switch-row" style="padding:0 18px"><div><b>自动保存资源</b><small>保存原始分享链接</small></div><button class="switch" id="chAutoSave" aria-checked="${item.auto_save_resources}" aria-label="自动保存资源"></button></div>
  <div class="switch-row" style="padding:0 18px"><div><b>自动识别分类</b><small>按标题判断电影/剧集</small></div><button class="switch" id="chAutoClassify" aria-checked="${item.auto_classify}" aria-label="自动识别分类"></button></div>
  <div class="switch-row" style="padding:0 18px"><div><b>要求豆瓣匹配</b><small>仅处理豆瓣榜单内的标题</small></div><button class="switch" id="chDoubanMatch" aria-checked="${item.require_douban_match}" aria-label="要求豆瓣匹配"></button></div>
  <div class="picker-foot"><button class="mini-btn" data-editor-close>取消</button><button class="mini-btn primary" data-editor-save>保存当前频道</button></div>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.querySelectorAll("[data-editor-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  dialog.querySelectorAll(".switch").forEach((button) => button.addEventListener("click", () => button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true")));
  dialog.querySelector("[data-editor-save]").addEventListener("click", async () => {
    const value = (id) => dialog.querySelector(id)?.value?.trim() || "";
    const checked = (id) => dialog.querySelector(id)?.getAttribute("aria-checked") === "true";
    const payload = {
      channel_id: item.channel_id,
      display_name: value("#chName") || item.channel_id,
      enabled: checked("#chEnabled"),
      auto_transfer: checked("#chAutoTransfer"),
      auto_save_resources: checked("#chAutoSave"),
      auto_classify: checked("#chAutoClassify"),
      cloud_download_child: value("#chChild"),
      require_douban_match: checked("#chDoubanMatch"),
      positive_keywords: value("#chPositive").split(",").map((part) => part.trim()).filter(Boolean),
      negative_keywords: value("#chNegative").split(",").map((part) => part.trim()).filter(Boolean),
      douban_titles: value("#chDouban").split("\n").map((part) => part.trim()).filter(Boolean),
    };
    try { await api("/api/cloud/channels", { method: "PUT", body: JSON.stringify(payload) }); } catch (error) { console.error(error); }
    dialog.close();
    await loadChannels();
  });
  dialog.showModal();
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
  document.querySelectorAll("[data-channel-edit]").forEach((button) => button.addEventListener("click", () => { const item = channels.find((entry) => entry.channel_id === button.dataset.channelEdit); if (item) openChannelEditor(item); }));
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
  node.className = "subnav";
  node.innerHTML = `
    ${[["tracking", "智能追更"], ["wishlist", "愿望单"], ["review", "待确认"], ["archived", "已归档"]].map(([key, label]) => `<button role="tab" aria-selected="${subsState.tab === key}" class="${subsState.tab === key ? "active" : ""}" data-subs-tab="${key}">${label}</button>`).join("")}
    <span class="divider"></span>
    <button role="tab" aria-selected="${subsState.provider === ""}" class="chip mini${subsState.provider === "" ? " active" : ""}" data-subs-provider="">全部网盘</button>
    ${providers.map((provider) => `<button role="tab" aria-selected="${subsState.provider === provider}" class="chip mini${subsState.provider === provider ? " active" : ""}" data-subs-provider="${esc(provider)}">${providerName(provider)}</button>`).join("")}`;
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
  if (subsState.tab === "archived") {
    const archived = subsState.tasks.filter((task) => task.status === "archived");
    main.innerHTML = `<div class="panel-head"><div><h2>已归档</h2><small>已完结或不再巡检的任务</small></div></div><div class="task-list">${archived.map(taskCard).filter(Boolean).join("") || `<div class="empty-state"><b>没有归档任务</b><span>完结的追更会自动归档。</span></div>`}</div>`;
  } else if (subsState.tab === "wishlist") {
    main.innerHTML = `<div class="panel-head"><div><h2>愿望单</h2><small>暂未找到资源的作品，找到后会转入追更</small></div></div><div class="task-list">${wishlistRows()}</div>`;
  } else if (subsState.tab === "review") {
    main.innerHTML = `<div class="panel-head"><div><h2>待确认</h2><small>匹配不确定的候选，确认后直接入库</small></div></div><div class="task-list">${reviewRows()}</div>`;
  } else {
    const cards = subsState.tasks.map(taskCard).filter(Boolean).join("");
    main.innerHTML = `<div class="panel-head"><div><h2>追更任务</h2><small>每部作品单独设置追更时间、保存路径与启用网盘</small></div><div class="row-actions"><button class="mini-btn" data-subs-refresh>刷新已存</button><button class="mini-btn" data-subs-pause-all>批量暂停</button></div></div><div class="task-list">${cards || `<div class="empty-state"><b>还没有追更任务</b><span>在发现页对作品点“加入智能追更”。</span></div>`}</div>`;
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

async function openEpisodesDialog(taskId, stateId) {
  const task = subsState.tasks.find((item) => String(item.id) === String(taskId));
  if (!task) return;
  let data = null;
  try { data = await api(`/api/tracking/${task.id}/episodes`); } catch (error) { data = { episodes: [] }; }
  const episodes = data.episodes || [];
  const provider = data.provider || "";
  const selected = new Set();
  const dialog = document.createElement("dialog");
  dialog.className = "picker-dialog episodes-dialog";
  const render = () => {
    const savedCount = episodes.filter((episode) => episode.status === "saved").length;
    dialog.innerHTML = `
    <div class="picker-head"><div><h2>${esc(task.title)} · 分集</h2><small>${provider === "p115" ? "115" : provider === "quark" ? "夸克" : esc(provider)} · 已存 ${savedCount} / ${episodes.length} 集${data.season_number ? ` · S${String(data.season_number).padStart(2, "0")}` : ""}</small></div><button class="icon-btn" data-ep-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
    <div class="ep-grid ep-dialog-grid">${episodes.map((episode) => {
      const state = episode.status === "saved" ? "saved" : episode.aired ? "missing" : "unaired";
      const number = Number(episode.episode_number);
      return `<button class="ep ${state}${selected.has(number) ? " selected" : ""}" data-ep-num="${number}" data-ep-state="${state}" title="${esc(episode.title || "")} ${esc(episode.air_date || "")}">E${String(number).padStart(2, "0")}</button>`;
    }).join("") || `<div class="empty-state"><b>没有分集数据</b><span>先刷新已存或等待巡检。</span></div>`}</div>
    <div class="picker-foot"><span class="muted-note">${selected.size ? `已选 ${selected.size} 集` : "点选未入库的集数"}</span><button class="mini-btn" data-ep-close>关闭</button><button class="mini-btn primary" data-ep-fill ${selected.size ? "" : "disabled"}>补齐所选</button></div>`;
    dialog.querySelectorAll("[data-ep-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    dialog.querySelectorAll("[data-ep-num]").forEach((button) => button.addEventListener("click", () => {
      if (button.dataset.epState === "saved") return;
      const number = Number(button.dataset.epNum);
      if (selected.has(number)) selected.delete(number); else selected.add(number);
      render();
    }));
    dialog.querySelector("[data-ep-fill]")?.addEventListener("click", async () => {
      const button = dialog.querySelector("[data-ep-fill]");
      if (button) { button.disabled = true; button.textContent = "提交中…"; }
      try { await api(`/api/tracking/${task.id}/fill`, { method: "POST", body: JSON.stringify({ episode_numbers: [...selected] }) }); }
      catch (error) { console.error(error); }
      dialog.close();
      await loadSubs();
    });
  };
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  render();
  dialog.showModal();
}
function bindSubs() {
  document.querySelectorAll("[data-subs-tab]").forEach((button) => button.addEventListener("click", () => { subsState.tab = button.dataset.subsTab; renderSubsBody(); }));
  document.querySelectorAll("[data-subs-provider]").forEach((button) => button.addEventListener("click", () => { subsState.provider = button.dataset.subsProvider; renderSubsBody(); }));
  document.querySelectorAll("[data-subs-refresh]").forEach((button) => button.addEventListener("click", () => void loadSubs()));
  document.querySelector("[data-subs-pause-all]")?.addEventListener("click", async () => { for (const task of subsState.tasks.filter((item) => item.status === "active")) { try { await api(`/api/tracking/${task.id}/pause`, { method: "POST" }); } catch (error) { console.error(error); } } await loadSubs(); });
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
    const willOpen = !subsState.panels[id];
    Object.keys(subsState.panels).forEach((key) => { subsState.panels[key] = false; });
    subsState.panels[id] = willOpen;
    if (subsState.panels[id] && !subsState.episodes[id]) {
      try { subsState.episodes[id] = await api(`/api/tracking/${button.dataset.task}/episodes`); } catch { subsState.episodes[id] = { episodes: [] }; }
    }
    renderSubsBody();
  }));
  document.querySelectorAll("[data-ep-pick]").forEach((button) => button.addEventListener("click", () => { if (button.dataset.epSaved === "true") return; button.classList.toggle("selected"); }));
  document.querySelectorAll("[data-fill-share]").forEach((button) => button.addEventListener("click", async () => {
    const panel = button.closest(".drive-episodes");
    const share = panel ? panel.querySelector("[data-share-input]")?.value?.trim() : "";
    const numbers = [...(panel ? panel.querySelectorAll("[data-ep-pick].selected") : [])].map((item) => Number(item.dataset.epPick));
    if (!share || !numbers.length) return;
    try { await api(`/api/tracking/${button.dataset.fillShare}/fill-from-share`, { method: "POST", body: JSON.stringify({ episode_numbers: numbers, share_url: share }) }); } catch (error) { console.error(error); }
    await loadSubs();
  }));
  document.querySelectorAll("[data-sync-selected]").forEach((button) => button.addEventListener("click", async () => {
    const panel = button.closest(".drive-episodes");
    const numbers = [...(panel ? panel.querySelectorAll("[data-ep-pick].selected") : [])].map((item) => Number(item.dataset.epPick));
    if (!numbers.length) return;
    try { await api(`/api/tracking/${button.dataset.syncSelected}/sync-selected`, { method: "POST", body: JSON.stringify({ episode_numbers: numbers }) }); } catch (error) { console.error(error); }
    await loadSubs();
  }));
  document.querySelectorAll("[data-ep-fill]").forEach((button) => button.addEventListener("click", async () => {
    const panel = button.closest(".drive-episodes");
    const numbers = [...(panel ? panel.querySelectorAll("[data-ep-pick].selected") : [])].map((item) => Number(item.dataset.epPick));
    if (!numbers.length) return;
    try { await api(`/api/tracking/${button.dataset.epFill}/fill`, { method: "POST", body: JSON.stringify({ episode_numbers: numbers }) }); } catch (error) { console.error(error); }
    await loadSubs();
  }));
  document.querySelectorAll("[data-run]").forEach((button) => button.addEventListener("click", () => void runSubsAction("run", () => api(`/api/tracking/${button.dataset.run}/run`, { method: "POST" }))));
  document.querySelectorAll("[data-toggle]").forEach((button) => button.addEventListener("click", () => void runSubsAction("toggle", () => api(`/api/tracking/${button.dataset.toggle}/${button.dataset.status === "active" ? "pause" : "resume"}`, { method: "POST" }))));
  document.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => { if (confirm("移除这个追更任务？")) void runSubsAction("delete", () => api(`/api/tracking/${button.dataset.delete}`, { method: "DELETE" })); }));
  document.querySelectorAll("[data-refresh-storage]").forEach((button) => button.addEventListener("click", () => void runSubsAction("refresh", () => api(`/api/tracking/${button.dataset.refreshStorage}/refresh-storage`, { method: "POST" }))));
  document.querySelectorAll("[data-sync-storage]").forEach((button) => button.addEventListener("click", () => void runSubsAction("sync", () => api(`/api/tracking/${button.dataset.syncStorage}/sync-storage`, { method: "POST" }))));
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
    <div class="subnav" role="tablist" aria-label="网盘工作台分区">${WS_SECTIONS.map(([key, label]) => `<button role="tab" aria-selected="${wsState.section === key}" class="${wsState.section === key ? "active" : ""}" data-ws-section="${key}">${label}${key === "tasks" ? ` <b style="font-weight:600;opacity:.6" id="wsTaskCount"></b>` : ""}</button>`).join("")}</div>
    <div id="wsBody"><div class="loading-block">正在读取网盘配置…</div></div>
  </div>`;
}

function wsConnectionsView(config) {
  const enabled = (config && config.enabled_providers) || [];
  const quarkOn = enabled.includes("quark");
  const p115On = enabled.includes("p115");
  const quarkConnected = Boolean(config && config.has_quark_cookie);
  const p115Connected = Boolean(config && config.has_p115_cookie);
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>执行开关</h2><small>至少保留一个网盘，关闭后不再派发新任务</small></div><span class="pill ${quarkOn || p115On ? "ok" : "warn"}"><i></i>${[quarkOn, p115On].filter(Boolean).length} 个已启用</span></div>
    <div class="switch-row"><div><b>夸克网盘</b><small>电影与部分剧集默认落在这里</small></div><button class="switch" data-ws-toggle="quark" aria-checked="${quarkOn}" aria-label="夸克网盘"></button></div>
    <div class="switch-row"><div><b>115 网盘</b><small>剧集、动漫与跨盘补齐的目标端</small></div><button class="switch" data-ws-toggle="p115" aria-checked="${p115On}" aria-label="115 网盘"></button></div>
  </section>
  <div class="card-grid">
    <div class="panel conn-card">
      <div class="conn-top"><span class="conn-logo" style="--brand:#2f6bd8">Q</span><div><b>夸克网盘</b><small>${quarkConnected ? "凭证已保存" : "未配置凭证"}</small></div><span class="pill ${quarkConnected ? "ok" : "muted"}" style="margin-left:auto"><i></i>${quarkConnected ? "已连接" : "未连接"}</span></div>
      <div class="field"><label>Cookie</label><input class="input" id="wsCookie-quark" type="password" placeholder="${quarkConnected ? "已保存，如需更换请重新粘贴" : "未配置"}" /></div>
      <div class="row-actions" style="justify-content:flex-start"><button class="mini-btn primary" data-ws-save-cookie="quark">保存凭证</button><button class="mini-btn" data-ws-test="quark">验证连接</button><button class="mini-btn" data-ws-qr="quark">扫码登录</button></div>
      <div class="kv"><div><span>媒体库</span><strong>${esc((config && config.qas_root) || (config && config.cloud_root) || "/")}</strong></div><div><span>执行端</span><strong>${quarkOn ? "已启用" : "已停用"}</strong></div></div>
    </div>
    <div class="panel conn-card">
      <div class="conn-top"><span class="conn-logo" style="--brand:#1f9e6a">115</span><div><b>115 网盘</b><small>${p115Connected ? "凭证已保存" : "扫码登录或粘贴 Cookie"}</small></div><span class="pill ${p115Connected ? "ok" : "muted"}" style="margin-left:auto"><i></i>${p115Connected ? "已连接" : "未连接"}</span></div>
      <div class="field"><label>Cookie</label><input class="input" id="wsCookie-p115" type="password" placeholder="${p115Connected ? "已保存，如需更换请重新粘贴" : "未配置"}" /></div>
      <div class="row-actions" style="justify-content:flex-start"><button class="mini-btn primary" data-ws-save-cookie="p115">保存凭证</button><button class="mini-btn" data-ws-test="p115">验证连接</button><button class="mini-btn" data-ws-qr="p115">扫码登录</button></div>
      <div class="kv"><div><span>接收目录</span><strong>${esc((config && config.p115_root_path) || "/")}</strong></div><div><span>执行端</span><strong>${p115On ? "已启用" : "已停用"}</strong></div></div>
    </div>
  </div>
  ${wsState.result ? `<p class="inline-result ${wsState.result.ok ? "ok" : "error"}">${esc(wsState.result.message)}</p>` : ""}`;
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

const CATEGORY_LABELS = [["movie", "电影"], ["tv", "剧集"], ["variety", "综艺"], ["concert", "演唱会"], ["documentary", "纪录片"], ["anime", "动漫"]];

function categoryFields(prefix, paths) {
  return CATEGORY_LABELS.map(([key, label]) => `<div class="field"><label>${label}</label><input class="input" data-cat="${prefix}:${key}" value="${esc((paths || {})[key] || "")}" placeholder="/${key}" /></div>`).join("");
}

function wsRulesView(config) {
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>通用规则</h2><small>命名、关键词与季目录，写入正式媒体库前生效</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>媒体文件夹命名</label><input class="input" id="wsRuleMedia" value="${esc(config.media_folder_naming_rule || "")}" /></div>
      <div class="field"><label>季文件夹命名</label><input class="input" id="wsRuleSeason" value="${esc(config.season_folder_naming_rule || "")}" /></div>
      <div class="field"><label>电影命名</label><input class="input" id="wsRuleMovie" value="${esc(config.movie_naming_rule || "")}" /></div>
      <div class="field"><label>剧集命名</label><input class="input" id="wsRuleEpisode" value="${esc(config.episode_naming_rule || "")}" /></div>
      <div class="field"><label>质量优先关键词</label><input class="input" id="wsQuality" value="${esc((config.quality_priority_keywords || []).join(","))}" placeholder="1080p,4K,HDR" /></div>
      <div class="field"><label>资源排除关键词</label><input class="input" id="wsExclude" value="${esc((config.resource_excluded_keywords || []).join(","))}" /></div>
    </div>
    <div class="switch-row"><div><b>季子目录</b><small>电视剧按季建立子目录</small></div><button class="switch" id="wsSeasonDir" aria-checked="${config.season_subdirectory_enabled ? "true" : "false"}" aria-label="季子目录"></button></div>
    <div class="panel-head" style="margin-top:6px"><div><h3>通用分类路径</h3><small>未单独配置网盘规则时使用</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">${categoryFields("base", config.category_paths)}</div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="rules">保存通用规则</button>${wsStateResult()}</div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>115 规则</h2><small>115 根目录、云下载、暂存与分类路径</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>根目录</label><input class="input" id="p115Root" value="${esc(config.p115_root_path || "")}" /></div>
      <div class="field"><label>云下载目录</label><input class="input" id="p115Cloud" value="${esc(config.p115_cloud_download_path || "")}" /></div>
      <div class="field"><label>暂存目录</label><input class="input" id="p115Staging" value="${esc(config.p115_staging_path || "")}" /></div>
      <div class="field"><label>本地挂载路径</label><input class="input" id="p115Local" value="${esc(config.p115_local_path || "")}" /></div>
    </div>
    <div class="panel-head" style="margin-top:6px"><div><h3>115 分类路径</h3><small>留空则继承通用分类路径</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">${categoryFields("p115", config.p115_category_paths)}</div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="p115rules">保存 115 规则</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>夸克规则</h2><small>夸克根目录、云下载、暂存与分类路径</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>根目录</label><input class="input" id="quarkRoot" value="${esc(config.quark_root_path || "")}" /></div>
      <div class="field"><label>云下载目录</label><input class="input" id="quarkCloud" value="${esc(config.quark_cloud_download_path || "")}" /></div>
      <div class="field"><label>暂存目录</label><input class="input" id="quarkStaging" value="${esc(config.quark_staging_path || "")}" /></div>
    </div>
    <div class="panel-head" style="margin-top:6px"><div><h3>夸克分类路径</h3><small>留空则继承通用分类路径</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">${categoryFields("quark", config.quark_category_paths)}</div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="quarkrules">保存夸克规则</button></div>
  </section>`;
}

function wsCloudView(config) {
  const triggers = config.cloud_download_organizer_triggers || [];
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>整理方式</h2><small>云下载完成后由整理器识别、改名并落盘到正式媒体库</small></div><span class="pill ${config.cloud_download_organizer_enabled ? "ok" : "muted"}"><i></i>${config.cloud_download_organizer_enabled ? "已启用" : "未启用"}</span></div>
    <div class="switch-row"><div><b>启用云下载整理</b><small>总开关，关闭后两个网盘都不整理</small></div><button class="switch" id="wsCloudEnabled" aria-checked="${config.cloud_download_organizer_enabled ? "true" : "false"}" aria-label="启用云下载整理"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="field"><label>整理方式</label><select class="input" id="wsCloudMode"><option value="move" ${config.cloud_download_organizer_mode !== "copy" ? "selected" : ""}>移动（move）</option><option value="copy" ${config.cloud_download_organizer_mode === "copy" ? "selected" : ""}>复制（copy）</option></select></div>
      <div class="field"><label>整理间隔（分钟）</label><input class="input" id="wsCloudInterval" type="number" min="1" value="${esc(config.cloud_download_organizer_interval_minutes ?? 10)}" /></div>
      <div class="field"><label>稳定等待（分钟）</label><input class="input" id="wsCloudStable" type="number" min="0" value="${esc(config.cloud_download_organizer_stable_minutes ?? 3)}" /></div>
    </div>
    <div class="field"><label>触发方式</label><div class="chip-row">${[["event", "事件触发"], ["interval", "定时轮询"], ["manual", "手动整理"]].map(([key, label]) => `<button class="chip mini${triggers.includes(key) ? " active" : ""}" data-cloud-trigger="${key}">${label}</button>`).join("")}</div></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="cloud">保存整理方式</button>${wsStateResult()}</div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>115 云下载</h2><small>115 云下载目录、暂存与分类子目录</small></div><span class="pill ${config.p115_cloud_download_organizer_enabled ? "ok" : "muted"}"><i></i>${config.p115_cloud_download_organizer_enabled ? "已启用" : "未启用"}</span></div>
    <div class="switch-row"><div><b>整理 115 云下载</b><small>只处理 115 云下载目录</small></div><button class="switch" id="wsCloudP115" aria-checked="${config.p115_cloud_download_organizer_enabled ? "true" : "false"}" aria-label="115 云下载整理"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>云下载目录</label><input class="input" id="p115CloudPath" value="${esc(config.p115_cloud_download_path || "")}" /></div>
      <div class="field"><label>整理范围</label><select class="input" id="p115CloudScope"><option value="all" ${config.p115_cloud_download_organizer_scope_mode !== "selected" ? "selected" : ""}>整个云下载目录</option><option value="selected" ${config.p115_cloud_download_organizer_scope_mode === "selected" ? "selected" : ""}>仅勾选的一级子目录</option></select></div>
      <div class="field"><label>暂存目录</label><input class="input" id="p115StagingPath" value="${esc(config.p115_staging_path || "")}" /></div>
      <div class="field"><label>一级子目录（每行一个）</label><textarea class="input" id="p115CloudDirs" rows="4">${esc((config.p115_cloud_download_organizer_directories || []).join("\n"))}</textarea></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="p115cloud">保存 115 云下载</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>夸克云下载</h2><small>夸克云下载目录、暂存与分类子目录</small></div><span class="pill ${config.quark_cloud_download_organizer_enabled ? "ok" : "muted"}"><i></i>${config.quark_cloud_download_organizer_enabled ? "已启用" : "未启用"}</span></div>
    <div class="switch-row"><div><b>整理夸克云下载</b><small>只处理夸克云下载目录</small></div><button class="switch" id="wsCloudQuark" aria-checked="${config.quark_cloud_download_organizer_enabled ? "true" : "false"}" aria-label="夸克云下载整理"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>云下载目录</label><input class="input" id="quarkCloudPath" value="${esc(config.quark_cloud_download_path || "")}" /></div>
      <div class="field"><label>整理范围</label><select class="input" id="quarkCloudScope"><option value="all" ${config.quark_cloud_download_organizer_scope_mode !== "selected" ? "selected" : ""}>整个云下载目录</option><option value="selected" ${config.quark_cloud_download_organizer_scope_mode === "selected" ? "selected" : ""}>仅勾选的一级子目录</option></select></div>
      <div class="field"><label>暂存目录</label><input class="input" id="quarkStagingPath" value="${esc(config.quark_staging_path || "")}" /></div>
      <div class="field"><label>一级子目录（每行一个）</label><textarea class="input" id="quarkCloudDirs" rows="4">${esc((config.quark_cloud_download_organizer_directories || []).join("\n"))}</textarea></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="quarkcloud">保存夸克云下载</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>手动整理</h2><small>指定目录跑一次整理，用于自动任务失败后的补救</small></div></div>
    <div class="form-grid" style="grid-template-columns:160px minmax(0,1fr);align-items:end">
      <div class="field"><label>网盘</label><select class="input" id="organizeProvider"><option value="quark">夸克</option><option value="p115">115</option></select></div>
      <div class="field"><label>目录</label><input class="input" id="organizePath" placeholder="/云下载/剧名 (2024)" /></div>
    </div>
    <div class="row-actions" style="margin-top:8px"><button class="mini-btn" data-organize-run>整理这个目录</button><span class="muted-note" id="organizeResult"></span></div>
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
    <div class="field"><label>回调地址</label><input class="input" readonly value="${esc((config.public_base_url || window.location.origin) + "/api/webhooks/mdc-ng")}" /></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-ws-save="webhook">保存 Webhook 设置</button>${wsStateResult()}</div>
  </section>
  <section class="panel panel-pad" id="wsWebhookPanel"><div class="loading-block">正在读取 Webhook 连接…</div></section>`;
}

function wsTasksView(jobs) {
  const tab = wsState.taskTab || "transfers";
  const config = wsState.config || {};
  const scheduled = [
    { name: "追更巡检", detail: config.tracking_scheduler_enabled ? `每 ${config.tracking_poll_minutes || 30} 分钟 · 默认 ${config.tracking_check_time || "20:00"}` : "已关闭", on: Boolean(config.tracking_scheduler_enabled) },
    { name: "愿望单检查", detail: config.wishlist_scheduler_enabled ? `每 ${config.wishlist_poll_minutes || 30} 分钟 · ${config.wishlist_default_check_hour ?? 9} 点` : "已关闭", on: Boolean(config.wishlist_scheduler_enabled) },
    { name: "115 STRM", detail: config.p115_strm_enabled ? `增量 cron：${config.p115_strm_incremental_cron || "未设置"}` : "已关闭", on: Boolean(config.p115_strm_enabled) },
    { name: "夸克 STRM", detail: config.quark_strm_enabled ? `增量 cron：${config.quark_strm_incremental_cron || "未设置"}` : "已关闭", on: Boolean(config.quark_strm_enabled) },
    { name: "Emby 封面刷新", detail: config.emby_cover_refresh_enabled ? `cron：${config.emby_cover_refresh_cron || "未设置"} · 每 ${config.emby_cover_refresh_hours || 24} 小时` : "已关闭", on: Boolean(config.emby_cover_refresh_enabled) },
    { name: "云下载整理", detail: config.cloud_download_organizer_enabled ? `每 ${config.cloud_download_organizer_interval_minutes || 10} 分钟` : "已关闭", on: Boolean(config.cloud_download_organizer_enabled) },
  ];
  return `
  <section class="panel">
    <div class="subnav" role="tablist" aria-label="任务中心分区">
      <button role="tab" aria-selected="${tab === "transfers"}" class="${tab === "transfers" ? "active" : ""}" data-task-tab="transfers">转存任务</button>
      <button role="tab" aria-selected="${tab === "scheduled"}" class="${tab === "scheduled" ? "active" : ""}" data-task-tab="scheduled">计划任务</button>
    </div>
    <div class="panel-head" style="margin-top:12px"><div><h2>${tab === "transfers" ? "任务中心" : "计划任务"}</h2><small>${tab === "transfers" ? `最近 ${Math.min(jobs.length, 20)} 条转存任务` : "按配置汇总的定时任务"}</small></div><button class="mini-btn" data-ws-refresh>刷新</button></div>
    ${tab === "transfers" ? (jobs.length ? `<div class="list">${jobs.slice(0, 20).map((job) => `<div class="list-row" data-job-detail="${job.id}" style="cursor:pointer">
      <div class="grow"><b>${esc(job.display_title || job.title || job.media_title || `任务 #${job.id}`)}</b><small>${esc(job.message || job.stage || "")}${job.provider ? ` · ${esc(job.provider)}` : ""}</small></div>
      <span class="pill ${job.status === "failed" ? "danger" : job.status === "done" ? "ok" : "warn"}"><i></i>${esc(job.status || "")}</span>
      <time>${esc(job.created_at ? formatDate(job.created_at) : "")}</time>
      <svg class="ic ic-sm"><use href="#i-chev-r"/></svg>
    </div>`).join("")}</div>` : `<div class="empty-state"><b>没有任务</b><span>发现页发起转存后，这里会出现记录。</span></div>`) : `<div class="list">${scheduled.map((item) => `<div class="list-row">
      <div class="grow"><b>${esc(item.name)}</b><small>${esc(item.detail)}</small></div>
      <span class="pill ${item.on ? "ok" : "muted"}"><i></i>${item.on ? "已启用" : "已关闭"}</span>
    </div>`).join("")}</div>`}
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
  api("/api/transfers").then((jobs) => { const node = document.getElementById("wsTaskCount"); if (node) node.textContent = String(Array.isArray(jobs) ? jobs.length : 0); }).catch(() => null);
  if (wsState.section === "connections") body.innerHTML = wsConnectionsView(config);
  else if (wsState.section === "sources") { body.innerHTML = wsSourcesView(config); body.insertAdjacentHTML("beforeend", `<section class="panel panel-pad" id="wsChannels"><div class="loading-block">正在读取频道订阅…</div></section>`); setTimeout(() => void loadChannels(), 0); }
  else if (wsState.section === "rules") body.innerHTML = wsRulesView(config);
  else if (wsState.section === "cloud-download") body.innerHTML = wsCloudView(config);
  else if (wsState.section === "webhook") { body.innerHTML = wsWebhookView(config); setTimeout(() => void loadWebhookPanel(), 0); }
  else if (wsState.section === "tasks") { const jobs = await api("/api/transfers").catch(() => []); wsState.jobs = Array.isArray(jobs) ? jobs : []; body.innerHTML = wsTasksView(wsState.jobs); }
  else body.innerHTML = wsPlaceholder(wsState.section);
  bindWs();
}

async function loadWebhookPanel() {
  const panel = document.getElementById("wsWebhookPanel");
  if (!panel) return;
  const [connections, deliveries] = await Promise.all([
    api("/api/webhooks/connections").catch(() => ({ items: [] })),
    api("/api/webhooks/connections/deliveries/recent").catch(() => ({ items: [] })),
  ]);
  const items = connections.items || [];
  const recent = deliveries.items || [];
  panel.innerHTML = `
  <div class="panel-head"><div><h2>Webhook 连接</h2><small>入站与出站连接，含签名密钥与测试</small></div></div>
  ${items.length ? `<div class="list">${items.map((item) => `<div class="list-row">
    <div class="grow"><b>${esc(item.name || String(item.id))}</b><small>${esc(item.kind || "")} · ${item.direction === "inbound" ? "入站" : "出站"} · ${esc(item.event_types ? (Array.isArray(item.event_types) ? item.event_types.join(", ") : item.event_types) : "")}</small></div>
    <span class="pill ${item.enabled ? "ok" : "muted"}"><i></i>${item.enabled ? "已启用" : "已停用"}</span>
    <button class="mini-btn" data-webhook-test="${esc(item.id)}">测试</button>
  </div>`).join("")}</div>` : `<div class="empty-state"><b>没有 Webhook 连接</b><span>MDC-NG 内置连接会显示在这里。</span></div>`}
  <div class="panel-head" style="margin-top:14px"><div><h2>最近投递</h2><small>最近 20 条</small></div></div>
  ${recent.length ? `<div class="list">${recent.slice(0, 20).map((item) => `<div class="list-row">
    <div class="grow"><b>${esc(item.event_type || item.name || "投递")}</b><small>${esc(item.message || item.error || "")}</small></div>
    <span class="pill ${item.status === "delivered" ? "ok" : item.status === "failed" ? "danger" : "warn"}"><i></i>${esc(item.status || "")}</span>
    <time>${esc(item.created_at ? formatDate(item.created_at) : "")}</time>
  </div>`).join("")}</div>` : `<div class="empty-state"><b>还没有投递记录</b><span>外部事件进入后会出现在这里。</span></div>`}`;
  panel.querySelectorAll("[data-webhook-test]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    try { const result = await api(`/api/webhooks/connections/${encodeURIComponent(button.dataset.webhookTest)}/test`, { method: "POST" }); button.textContent = result.ok ? "成功" : "失败"; }
    catch (error) { button.textContent = "失败"; }
    await loadWebhookPanel();
  }));
}

function bindWs() {
  document.querySelectorAll("[data-cloud-trigger]").forEach((button) => button.addEventListener("click", () => button.classList.toggle("active")));
  document.querySelectorAll("[data-ws-section]").forEach((button) => button.addEventListener("click", () => { wsState.section = button.dataset.wsSection; document.querySelectorAll("[data-ws-section]").forEach((chip) => { const active = chip.dataset.wsSection === wsState.section; chip.classList.toggle("active", active); chip.setAttribute("aria-selected", String(active)); }); void loadWs(); }));
  document.querySelectorAll("[data-ws-provider]").forEach((button) => button.addEventListener("click", () => { wsState.provider = button.dataset.wsProvider; wsState.result = null; void loadWs(); }));
  document.querySelectorAll("[data-ws-toggle]").forEach((button) => button.addEventListener("click", () => void toggleWsProvider(button.dataset.wsToggle)));
  document.querySelectorAll("[data-task-tab]").forEach((button) => button.addEventListener("click", () => { wsState.taskTab = button.dataset.taskTab; void loadWs(); }));
  document.querySelectorAll("[data-ws-qr]").forEach((button) => button.addEventListener("click", () => void openQrLogin(button.dataset.wsQr)));
  document.querySelectorAll("[data-ws-save-cookie]").forEach((button) => button.addEventListener("click", () => void saveWsCookie(button.dataset.wsSaveCookie)));
  document.querySelectorAll("[data-ws-test]").forEach((button) => { if (button.dataset.wsTest === "quark" || button.dataset.wsTest === "p115") button.addEventListener("click", () => void testWsConnection(button.dataset.wsTest)); });
  document.querySelectorAll(".switch").forEach((button) => button.addEventListener("click", () => button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true")));
  document.querySelectorAll("[data-ws-save]").forEach((button) => button.addEventListener("click", () => void saveWsSection(button.dataset.wsSave)));
  document.querySelector("[data-organize-run]")?.addEventListener("click", () => void runManualOrganize());
  document.querySelectorAll("[data-ws-test]").forEach((button) => button.addEventListener("click", () => void testWsSection(button.dataset.wsTest)));
  document.querySelector("[data-ws-refresh]")?.addEventListener("click", () => void loadWs());
  document.querySelectorAll("[data-job-detail]").forEach((card) => card.addEventListener("click", () => openJobDetail(card.dataset.jobDetail)));
}

function readCategoryPaths(prefix) {
  const result = {};
  document.querySelectorAll(`[data-cat^="${prefix}:"]`).forEach((input) => {
    const key = input.dataset.cat.split(":")[1];
    const value = input.value.trim();
    if (value) result[key] = value;
  });
  return result;
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
  } else if (scope === "rules") {
    payload.media_folder_naming_rule = document.getElementById("wsRuleMedia")?.value || "";
    payload.season_folder_naming_rule = document.getElementById("wsRuleSeason")?.value || "";
    payload.movie_naming_rule = document.getElementById("wsRuleMovie")?.value || "";
    payload.episode_naming_rule = document.getElementById("wsRuleEpisode")?.value || "";
    payload.season_subdirectory_enabled = document.getElementById("wsSeasonDir")?.getAttribute("aria-checked") === "true";
    payload.quality_priority_keywords = (document.getElementById("wsQuality")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
    payload.resource_excluded_keywords = (document.getElementById("wsExclude")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
    payload.category_paths = readCategoryPaths("base");
  } else if (scope === "p115rules") {
    payload.p115_root_path = document.getElementById("p115Root")?.value || "";
    payload.p115_cloud_download_path = document.getElementById("p115Cloud")?.value || "";
    payload.p115_staging_path = document.getElementById("p115Staging")?.value || "";
    payload.p115_local_path = document.getElementById("p115Local")?.value || "";
    payload.p115_category_paths = readCategoryPaths("p115");
  } else if (scope === "quarkrules") {
    payload.quark_root_path = document.getElementById("quarkRoot")?.value || "";
    payload.quark_cloud_download_path = document.getElementById("quarkCloud")?.value || "";
    payload.quark_staging_path = document.getElementById("quarkStaging")?.value || "";
    payload.quark_category_paths = readCategoryPaths("quark");
  } else if (scope === "cloud") {
    payload.cloud_download_organizer_enabled = document.getElementById("wsCloudEnabled")?.getAttribute("aria-checked") === "true";
    payload.p115_cloud_download_organizer_enabled = document.getElementById("wsCloudP115")?.getAttribute("aria-checked") === "true";
    payload.quark_cloud_download_organizer_enabled = document.getElementById("wsCloudQuark")?.getAttribute("aria-checked") === "true";
    payload.cloud_download_organizer_interval_minutes = Number(document.getElementById("wsCloudInterval")?.value || 10);
    payload.cloud_download_organizer_mode = document.getElementById("wsCloudMode")?.value || "move";
    payload.cloud_download_organizer_triggers = [...document.querySelectorAll("[data-cloud-trigger].active")].map((button) => button.dataset.cloudTrigger);
    payload.cloud_download_organizer_stable_minutes = Number(document.getElementById("wsCloudStable")?.value || 3);
    payload.p115_staging_path = document.getElementById("wsStagingP115")?.value || "";
    payload.quark_staging_path = document.getElementById("wsStagingQuark")?.value || "";
  } else if (scope === "p115cloud") {
    payload.p115_cloud_download_organizer_enabled = document.getElementById("wsCloudP115")?.getAttribute("aria-checked") === "true";
    payload.p115_cloud_download_path = document.getElementById("p115CloudPath")?.value || "";
    payload.p115_staging_path = document.getElementById("p115StagingPath")?.value || "";
    payload.p115_cloud_download_organizer_scope_mode = document.getElementById("p115CloudScope")?.value || "all";
    payload.p115_cloud_download_organizer_directories = (document.getElementById("p115CloudDirs")?.value || "").split("\n").map((item) => item.trim()).filter(Boolean);
  } else if (scope === "quarkcloud") {
    payload.quark_cloud_download_organizer_enabled = document.getElementById("wsCloudQuark")?.getAttribute("aria-checked") === "true";
    payload.quark_cloud_download_path = document.getElementById("quarkCloudPath")?.value || "";
    payload.quark_staging_path = document.getElementById("quarkStagingPath")?.value || "";
    payload.quark_cloud_download_organizer_scope_mode = document.getElementById("quarkCloudScope")?.value || "all";
    payload.quark_cloud_download_organizer_directories = (document.getElementById("quarkCloudDirs")?.value || "").split("\n").map((item) => item.trim()).filter(Boolean);
  } else if (scope === "webhook") {  } else if (scope === "webhook") {
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

async function saveWsCookie(provider) {
  const input = document.getElementById(`wsCookie-${provider}`);
  const value = input && input.value ? input.value.trim() : "";
  if (!value) return;
  wsState.busy = "cookie";
  try {
    const payload = provider === "quark" ? { quark_cookie: value } : { p115_cookie: value, p115_auth_mode: "cookie" };
    await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
    wsState.result = { ok: true, message: `${provider === "quark" ? "夸克" : "115"} Cookie 已保存在本机服务端。` };
  } catch (error) { wsState.result = { ok: false, message: error.message }; }
  wsState.busy = "";
  await loadWs();
}

async function testWsConnection(provider) {
  wsState.busy = "test";
  try {
    const result = await api(provider === "quark" ? "/api/config/test-quark" : "/api/config/test-p115", { method: "POST" });
    wsState.result = { ok: Boolean(result.ok), message: result.message || "验证完成" };
  } catch (error) { wsState.result = { ok: false, message: error.message }; }
  wsState.busy = "";
  await loadWs();
}

const crossState = { config: null, tasks: [], entries: [], sourceEntries: [], targetEntries: [], source: "", target: "", selected: new Set(), overwrite: false, message: "", busy: false, tab: "rules" };

function crossPageView() {
  return `
  <div class="mi-page" id="crossPage">
    <div class="page-head">
      <div><p class="eyebrow">CROSS CLOUD · 跨盘补齐</p><h1>跨盘转存</h1><p class="sub">这是补偿链路：两盘各自完成发现与转存，需要时再从夸克定向补齐 115。</p></div>
      <div class="page-actions"><span class="pill" id="crossPill"><i></i>读取中</span></div>
    </div>
    <section class="callout panel panel-pad">
      <b>补偿链路，不是发现入口</b>
      <p>先由两个网盘分别完成发现与转存；需要时再从夸克定向补齐 115。自动补齐只在夸克完成标准命名与正式落盘后启动，云下载暂存内容需先经整理器落盘。</p>
    </section>
    <div class="subnav" id="crossTabs" role="tablist" aria-label="跨盘分区">
      <button role="tab" aria-selected="true" class="active" data-cross-tab="rules">通路与规则</button>
      <button role="tab" aria-selected="false" data-cross-tab="manual">手动复制</button>
      <button role="tab" aria-selected="false" data-cross-tab="tasks">复制队列</button>
    </div>
    <div id="crossBody"><div class="loading-block">正在读取跨盘配置…</div></div>
  </div>`;
}

function crossConfigView(config) {
  const route = crossState.route || config.cross_copy_transport || "openlist";
  const cd2 = route === "cd2";
  const label = cd2 ? "CD2" : "OpenList";
  const saved = config || {};
  return `
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>跨盘通路与补齐规则</h2><small>OpenList 与 CD2 二选一；两条通路共用缺失文件筛选、落盘核验和 STRM / Emby 入库流程。</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>复制通路</label><select class="input" id="crossRoute"><option value="openlist" ${cd2 ? "" : "selected"}>OpenList</option><option value="cd2" ${cd2 ? "selected" : ""}>CD2（CloudDrive2）</option></select></div>
      <div class="field"><label>${label} 地址</label><input class="input" id="crossUrl" value="${esc(saved[route + "_url"] || "")}" placeholder="${cd2 ? "http://clouddrive:19798" : "http://openlist:5244"}" /></div>
      <div class="field"><label>${label} ${cd2 ? "API " : ""}Token</label><input class="input" id="crossToken" type="password" placeholder="${saved["has_" + route + "_token"] ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>夸克媒体库目录</label><input class="input" id="crossQasPath" value="${esc(saved[route + "_qas_library_path"] || "")}" placeholder="/夸克/媒体库" /></div>
      <div class="field"><label>115 媒体库目录</label><input class="input" id="crossP115Path" value="${esc(saved[route + "_p115_library_path"] || "")}" placeholder="/115/媒体库" /></div>
    </div>
    <div class="switch-row"><div><b>启用跨盘复制</b><small>关闭后不会发起任何跨盘复制</small></div><button class="switch" id="crossEnabled" aria-checked="${saved.openlist_enabled ? "true" : "false"}" aria-label="启用跨盘复制"></button></div>
    <div class="switch-row"><div><b>允许夸克 → 115 自动补齐</b><small>关闭后只保留手动补齐</small></div><button class="switch" id="crossAuto" aria-checked="${saved.openlist_auto_sync ? "true" : "false"}" aria-label="允许自动补齐"></button></div>
    ${cd2 ? `<p class="muted-note">CD2 使用服务地址与 API Token，支持原生连接和 gRPC-Web 反向代理；Token 需允许浏览、复制、创建目录与查询任务。</p>` : `<p class="muted-note">OpenList 需要可读写的 Quark 与 115 挂载；测试会读取根目录。</p>`}
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-cross-save>保存跨盘设置</button><button class="mini-btn" data-cross-test>测试已保存的连接</button>${crossState.message ? `<span class="inline-result ${crossState.ok ? "ok" : "error"}">${esc(crossState.message)}</span>` : ""}</div>
  </section>`;
}

function crossManualView() {
  const selected = crossState.selected;
  const rows = (entries, side) => entries.map((entry) => `<label class="copy-row"><input type="checkbox" data-copy-pick="${esc(entry.name)}" data-side="${side}" ${selected.has(entry.name) && side === "source" ? "checked" : ""} /><svg class="ic"><use href="#${entry.is_dir ? "i-folder" : "i-doc"}"/></svg><span ${entry.is_dir ? `data-copy-enter="${esc(entry.name)}"` : ""}>${esc(entry.name)}</span><time>${esc((entry.updated_at || entry.modified || "").slice(5, 10))}</time></label>`).join("");
  return `
  <section class="panel">
    <div class="panel-head">
      <div><h2>手动复制</h2><small>勾选左侧条目，选择目标目录后复制</small></div>
      <div class="chip-row"><button class="chip mini${crossState.overwrite ? "" : " active"}" data-copy-mode="skip">跳过已存在</button><button class="chip mini${crossState.overwrite ? " active" : ""}" data-copy-mode="overwrite">覆盖已存在</button></div>
    </div>
    <div class="copy-grid">
      <div class="copy-pane">
        <div class="copy-head"><b>夸克媒体库</b><small>${esc(crossState.source || "/")}</small><div class="row-actions"><button class="mini-btn" data-copy-up="source">上一级</button><button class="mini-btn" data-copy-refresh="source">刷新</button></div></div>
        ${crossState.sourceEntries.length ? rows(crossState.sourceEntries, "source") : `<div class="empty-state"><b>目录为空或未读取</b><span>点刷新读取当前目录</span></div>`}
      </div>
      <div class="copy-mid">
        <button class="copy-go" data-copy-run ${selected.size ? "" : "disabled"} title="复制到 115">→</button>
        <span class="copy-count">已选 ${selected.size}</span>
      </div>
      <div class="copy-pane">
        <div class="copy-head"><b>115 媒体库</b><small>${esc(crossState.target || "/")}</small><div class="row-actions"><button class="mini-btn" data-copy-up="target">上一级</button><button class="mini-btn" data-copy-refresh="target">刷新</button></div></div>
        ${crossState.targetEntries.length ? rows(crossState.targetEntries, "target") : `<div class="empty-state"><b>目标目录为空或未读取</b><span>点刷新读取当前目录</span></div>`}
      </div>
    </div>
    ${crossState.message ? `<p class="inline-result ${crossState.ok ? "ok" : "error"}" style="padding:0 18px 14px">${esc(crossState.message)}</p>` : ""}
  </section>`;
}

async function loadCopyPane(side) {
  const path = side === "source" ? crossState.source : crossState.target;
  try {
    const result = await api("/api/openlist/entries", { method: "POST", body: JSON.stringify({ path }) });
    const entries = (result.entries || []).map((entry) => ({ ...entry, updated_at: entry.updated_at || entry.modified_at || "" }));
    if (side === "source") crossState.sourceEntries = entries; else crossState.targetEntries = entries;
    crossState.ok = true;
    crossState.message = "";
  } catch (error) { crossState.ok = false; crossState.message = error.message; }
  await loadCross();
}

function bindCopy() {
  document.querySelectorAll("[data-copy-refresh]").forEach((button) => button.addEventListener("click", () => void loadCopyPane(button.dataset.copyRefresh)));
  document.querySelectorAll("[data-copy-up]").forEach((button) => button.addEventListener("click", () => {
    const side = button.dataset.copyUp;
    const path = side === "source" ? crossState.source : crossState.target;
    const parent = path.replace(/\/[^/]+\/?$/, "") || "/";
    if (side === "source") crossState.source = parent; else crossState.target = parent;
    void loadCopyPane(side);
  }));
  document.querySelectorAll("[data-copy-enter]").forEach((node) => node.addEventListener("click", () => {
    const side = node.closest(".copy-pane")?.querySelector("[data-copy-refresh]")?.dataset.copyRefresh || "source";
    const base = (side === "source" ? crossState.source : crossState.target).replace(/\/$/, "");
    const next = `${base}/${node.dataset.copyEnter}`;
    if (side === "source") crossState.source = next; else crossState.target = next;
    void loadCopyPane(side);
  }));
  document.querySelectorAll("[data-copy-pick]").forEach((input) => input.addEventListener("change", () => {
    if (input.dataset.side !== "source") return;
    if (input.checked) crossState.selected.add(input.dataset.copyPick); else crossState.selected.delete(input.dataset.copyPick);
    const button = document.querySelector("[data-copy-run]");
    if (button) button.disabled = crossState.selected.size === 0;
    const count = document.querySelector(".copy-count");
    if (count) count.textContent = `已选 ${crossState.selected.size}`;
  }));
  document.querySelectorAll("[data-copy-mode]").forEach((button) => button.addEventListener("click", () => {
    crossState.overwrite = button.dataset.copyMode === "overwrite";
    void loadCross();
  }));
  document.querySelector("[data-copy-run]")?.addEventListener("click", () => void runCopy());
}

async function runCopy() {
  if (!crossState.selected.size) return;
  crossState.busy = true;
  try {
    const result = await api("/api/openlist/sync-selected", { method: "POST", body: JSON.stringify({ source_dir: crossState.source, target_dir: crossState.target, names: [...crossState.selected], overwrite: Boolean(crossState.overwrite) }) });
    crossState.ok = true; crossState.message = result.message || "复制任务已提交"; crossState.selected = new Set();
  } catch (error) { crossState.ok = false; crossState.message = error.message; }
  crossState.busy = false;
  await loadCross();
}

function crossTasksView() {
  const tasks = crossState.tasks;
  return `
  <section class="panel">
    <div class="panel-head"><div><h2>复制队列</h2><small>OpenList 任务状态每 2.5 秒刷新</small></div><div class="row-actions"><button class="mini-btn" data-cross-refresh-tasks>刷新</button><button class="mini-btn" data-cross-clear-finished>清除已完成</button></div></div>
    ${tasks.length ? `<div class="list">${tasks.map((task) => `<div class="list-row">
      <div class="grow"><b>${esc(task.name || task.source || `任务 #${task.id}`)}</b><small>${esc(task.source || "")} → ${esc(task.target || "")}${task.message ? ` · ${esc(task.message)}` : ""}</small></div>
      <span class="pill ${task.state === "running" ? "warn" : task.state === "failed" ? "danger" : "ok"}"><i></i>${esc(task.state || "")}</span>
      ${task.progress ? `<span class="muted-note">${esc(task.progress)}%</span>` : ""}
    </div>`).join("")}</div>` : `<div class="empty-state"><b>复制队列为空</b><span>手动复制或自动补齐会出现在这里。</span></div>`}
  </section>`;
}
async function loadCross() {
  const body = document.getElementById("crossBody");
  if (!body) return;
  const [config, tasks] = await Promise.all([
    api("/api/cross-copy/config").catch(() => null),
    api("/api/openlist/tasks").catch(() => ({ tasks: [] })),
  ]);
  crossState.config = config;
  crossState.tasks = Array.isArray(tasks.tasks) ? tasks.tasks : [];
  const pill = document.getElementById("crossPill");
  if (pill) { const ready = Boolean(config && config.ready); pill.className = `pill ${ready ? "ok" : "muted"}`; pill.innerHTML = `<i></i>${ready ? "通路已就绪" : "通路未就绪"}`; }
  if (!config) { body.innerHTML = `<section class="panel panel-pad"><div class="empty-state"><b>跨盘配置读取失败</b><span>请稍后重试</span></div></section>`; return; }
  if (crossState.tab === "manual") {
    const route = crossState.route || config.cross_copy_transport || "openlist";
    if (!crossState.source) crossState.source = config[route + "_qas_library_path"] || "/";
    if (!crossState.target) crossState.target = config[route + "_p115_library_path"] || "/";
    if (!crossState.sourceEntries.length) { try { const res = await api("/api/openlist/entries", { method: "POST", body: JSON.stringify({ path: crossState.source }) }); crossState.sourceEntries = res.entries || []; } catch (error) { crossState.sourceEntries = []; } }
    if (!crossState.targetEntries.length) { try { const res = await api("/api/openlist/entries", { method: "POST", body: JSON.stringify({ path: crossState.target }) }); crossState.targetEntries = res.entries || []; } catch (error) { crossState.targetEntries = []; } }
    body.innerHTML = crossManualView();
  } else if (crossState.tab === "tasks") body.innerHTML = crossTasksView();
  else body.innerHTML = crossConfigView(config);
  bindCross();
}

function bindCross() {
  document.querySelectorAll("[data-cross-tab]").forEach((button) => button.addEventListener("click", () => {
    crossState.tab = button.dataset.crossTab;
    document.querySelectorAll("[data-cross-tab]").forEach((chip) => { const on = chip.dataset.crossTab === crossState.tab; chip.classList.toggle("active", on); chip.setAttribute("aria-selected", String(on)); });
    void loadCross();
  }));
  document.getElementById("crossRoute")?.addEventListener("change", (event) => { crossState.route = event.target.value; crossState.config = { ...(crossState.config || {}) }; void loadCross(); });
  document.querySelector("[data-cross-save]")?.addEventListener("click", () => void saveCrossConfig());
  document.querySelector("[data-cross-test]")?.addEventListener("click", async () => {
    try { const result = await api("/api/openlist/test", { method: "POST" }); crossState.ok = result.ok; crossState.message = result.message; }
    catch (error) { crossState.ok = false; crossState.message = error.message; }
    await loadCross();
  });
  bindCopy();
  document.querySelector("[data-cross-sync-library]")?.addEventListener("click", () => void syncCrossLibrary());
  document.querySelectorAll("[data-cross-entry]").forEach((input) => input.addEventListener("change", () => {
    if (input.checked) crossState.selected.add(input.dataset.crossEntry);
    else crossState.selected.delete(input.dataset.crossEntry);
    const label = document.querySelector("[data-cross-sync-selected]");
    if (label) label.textContent = `复制所选（${crossState.selected.size}）`;
  }));
}

async function saveCrossConfig() {
  const route = document.getElementById("crossRoute")?.value || "openlist";
  const payload = {
    cross_copy_transport: route,
    openlist_enabled: document.getElementById("crossEnabled")?.getAttribute("aria-checked") === "true",
    openlist_auto_sync: document.getElementById("crossAuto")?.getAttribute("aria-checked") === "true",
    [`${route}_url`]: document.getElementById("crossUrl")?.value || "",
    [`${route}_qas_library_path`]: document.getElementById("crossQasPath")?.value || "",
    [`${route}_p115_library_path`]: document.getElementById("crossP115Path")?.value || "",
  };
  const token = document.getElementById("crossToken")?.value?.trim();
  if (token) payload[`${route}_token`] = token;
  try { await api("/api/cross-copy/config", { method: "POST", body: JSON.stringify(payload) }); crossState.ok = true; crossState.message = "跨盘设置已保存"; }
  catch (error) { crossState.ok = false; crossState.message = error.message; }
  await loadCross();
}

async function browseCross(kind) {
  const current = kind === "source" ? (document.getElementById("crossSource")?.value || "/") : (document.getElementById("crossTarget")?.value || "/");
  try {
    const result = await api("/api/openlist/browse", { method: "POST", body: JSON.stringify({ path: current }) });
    const dirs = (result.directories || []).filter((item) => item.is_dir);
    const dialog = document.createElement("dialog");
    dialog.className = "picker-dialog";
    dialog.innerHTML = `<div class="picker-head"><div><h2>选择${kind === "source" ? "源" : "目标"}目录</h2><small>${esc(result.path || current)}</small></div><button class="icon-btn" data-browse-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
    <div class="picker-list">${dirs.length ? dirs.map((item) => `<button class="picker-row" data-browse-dir="${esc(item.name)}"><svg class="ic"><use href="#i-folder"/></svg><span>${esc(item.name)}</span><svg class="ic ic-sm"><use href="#i-chev-r"/></svg></button>`).join("") : `<div class="empty-state"><b>没有子目录</b><span>可直接使用当前目录。</span></div>`}</div>
    <div class="picker-foot"><button class="mini-btn" data-browse-close>取消</button><button class="mini-btn primary" data-browse-choose>使用当前目录</button></div>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("close", () => dialog.remove());
    dialog.querySelectorAll("[data-browse-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    dialog.querySelectorAll("[data-browse-dir]").forEach((button) => button.addEventListener("click", async () => {
      const base = (result.path || current).replace(/\/$/, "");
      const next = `${base}/${button.dataset.browseDir}`;
      dialog.close();
      await browseInto(kind, next);
    }));
    dialog.querySelector("[data-browse-choose]")?.addEventListener("click", () => {
      const input = document.getElementById(kind === "source" ? "crossSource" : "crossTarget");
      if (input) input.value = result.path || current;
      dialog.close();
    });
    dialog.showModal();
  } catch (error) { crossState.ok = false; crossState.message = error.message; await loadCross(); }
}

async function browseInto(kind, path) {
  const input = document.getElementById(kind === "source" ? "crossSource" : "crossTarget");
  if (input) input.value = path;
  await browseCross(kind);
}

async function loadCrossEntries() {
  crossState.source = document.getElementById("crossSource")?.value?.trim() || "";
  crossState.target = document.getElementById("crossTarget")?.value?.trim() || "";
  if (!crossState.source) { crossState.ok = false; crossState.message = "请先填写源目录"; await loadCross(); return; }
  try {
    const result = await api("/api/openlist/entries", { method: "POST", body: JSON.stringify({ path: crossState.source }) });
    crossState.entries = result.entries || [];
    crossState.selected = new Set();
    crossState.ok = true;
    crossState.message = `读取到 ${crossState.entries.length} 个条目`;
  } catch (error) { crossState.ok = false; crossState.message = error.message; }
  await loadCross();
}

async function syncCrossSelected() {
  if (!crossState.selected.size) { crossState.ok = false; crossState.message = "请先勾选要复制的条目"; await loadCross(); return; }
  try {
    const result = await api("/api/openlist/sync-selected", { method: "POST", body: JSON.stringify({ source_dir: crossState.source, target_dir: crossState.target, names: [...crossState.selected], overwrite: false }) });
    crossState.ok = true; crossState.message = result.message || "复制任务已提交";
    crossState.selected = new Set();
  } catch (error) { crossState.ok = false; crossState.message = error.message; }
  await loadCross();
}

async function syncCrossLibrary() {
  try { const result = await api("/api/openlist/sync-library", { method: "POST" }); crossState.ok = true; crossState.message = result.message || "整库同步已提交"; }
  catch (error) { crossState.ok = false; crossState.message = error.message; }
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
    <div class="subnav" id="strmChips" role="tablist" aria-label="STRM 分区">
      <button role="tab" aria-selected="${strmState.section === "common"}" class="${strmState.section === "common" ? "active" : ""}" data-strm-section="common">STRM 通用设置</button>
      <button role="tab" aria-selected="${strmState.section === "p115"}" class="${strmState.section === "p115" ? "active" : ""}" data-strm-section="p115">115 STRM</button>
      <button role="tab" aria-selected="${strmState.section === "quark"}" class="${strmState.section === "quark" ? "active" : ""}" data-strm-section="quark">夸克 STRM</button>
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
      <div class="field"><label>源文件删除方式</label><select class="input" id="strmDeletionMode"><option value="trash" ${config.emby_deletion_mode !== "delete" ? "selected" : ""}>移到回收站</option><option value="delete" ${config.emby_deletion_mode === "delete" ? "selected" : ""}>直接删除</option></select></div>
      <div class="field"><label>删除 Webhook 密钥</label><input class="input" id="strmDeletionToken" type="password" placeholder="${config.has_emby_deletion_webhook_token ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
    </div>
    <div class="switch-row"><div><b>STRM 完成后刷新 Emby 媒体库</b><small>生成后自动触发对应库扫描</small></div><button class="switch" id="strmEmbyRefresh" aria-checked="${config.emby_library_refresh_enabled ? "true" : "false"}" aria-label="刷新 Emby 媒体库"></button></div>
    <div class="switch-row"><div><b>收到 Emby 删除事件后自动执行</b><small>关闭后只记录删除意图，等待人工确认</small></div><button class="switch" id="strmAutoDelete" aria-checked="${config.emby_deletion_auto_confirm ? "true" : "false"}" aria-label="自动执行删除"></button></div>
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
      <div class="field" style="grid-column:1/-1"><label>包含子目录（每行一个，留空为全部）</label><textarea class="input" id="strmInclude" rows="3">${esc(((isP115 ? config.p115_strm_included_directories : config.quark_strm_included_directories) || []).join("\n"))}</textarea></div>
    </div>
    <div class="panel-head" style="margin-top:6px"><div><h3>手动操作</h3><small>立即生成或重新扫描指定目录</small></div></div>
    <div class="form-grid" style="grid-template-columns:160px minmax(0,1fr) auto;align-items:end">
      <div class="field"><label>生成模式</label><select class="input" id="strmMode"><option value="incremental">增量</option><option value="full">全量</option></select></div>
      <div class="field"><label>目录</label><input class="input" id="strmActionDir" placeholder="${esc(root || "/媒体库")}" /></div>
      <div class="row-actions" style="margin:0 0 10px"><button class="mini-btn" data-strm-run="${provider}">生成 STRM</button><button class="mini-btn" data-strm-rescan="${provider}">扫描目录</button></div>
    </div>
    <p class="muted-note" id="strmActionResult"></p>
    <div class="switch-row"><div><b>生成后刮削</b><small>让 Emby 读取 nfo 与图片</small></div><button class="switch" id="strmScrape" aria-checked="${scrape ? "true" : "false"}" aria-label="生成后刮削"></button></div>
    ${isP115 ? `<div class="switch-row"><div><b>生活事件监控</b><small>监听网盘文件变化，自动补生成</small></div><button class="switch" id="strmLife" aria-checked="${config.p115_strm_life_monitor_enabled ? "true" : "false"}" aria-label="生活事件监控"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>监控的 115 子目录</label><input class="input" id="strmLifePath" value="${esc(config.p115_strm_life_monitor_path || "")}" placeholder="/媒体库" /></div>
      <div class="field"><label>事件检查间隔（秒）</label><input class="input" id="strmLifeInterval" type="number" min="5" value="${esc(config.p115_strm_life_monitor_interval_seconds ?? 30)}" /></div>
    </div>` : ""}
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

async function runStrmJob(provider) {
  const note = document.getElementById("strmActionResult");
  const dir = document.getElementById("strmActionDir")?.value.trim();
  const config = strmState.config || {};
  if (!dir) { if (note) note.textContent = "请先填写目录"; return; }
  try {
    const res = await api("/api/cloud/strm/jobs", { method: "POST", body: JSON.stringify({ provider, mode: document.getElementById("strmMode")?.value || "incremental", root_path: dir, output_root: config.strm_output_root || "/strm", include_directories: (document.getElementById("strmInclude")?.value || "").split("\n").map((item) => item.trim()).filter(Boolean), playback_base_url: config.strm_playback_base_url || "" }) });
    if (note) note.textContent = res.message || "已提交生成任务";
  } catch (error) { if (note) note.textContent = error.message; }
}

async function rescanStrm(provider) {
  const note = document.getElementById("strmActionResult");
  const dir = document.getElementById("strmActionDir")?.value.trim();
  if (!dir) { if (note) note.textContent = "请先填写目录"; return; }
  try {
    const res = await api("/api/strm/directory-rescan", { method: "POST", body: JSON.stringify({ provider, directory_path: dir }) });
    if (note) note.textContent = res.message || "已提交扫描任务";
  } catch (error) { if (note) note.textContent = error.message; }
}

function bindStrm() {
  document.querySelectorAll("[data-strm-section]").forEach((button) => button.addEventListener("click", () => {
    strmState.section = button.dataset.strmSection;
    document.querySelectorAll("[data-strm-section]").forEach((chip) => { const on = chip.dataset.strmSection === strmState.section; chip.classList.toggle("active", on); chip.setAttribute("aria-selected", String(on)); });
    void loadStrm();
  }));
  document.querySelectorAll(".switch").forEach((button) => button.addEventListener("click", () => {
    button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true");
  }));
  document.querySelectorAll("[data-strm-save]").forEach((button) => button.addEventListener("click", () => void saveStrm(button.dataset.strmSave)));
  document.querySelectorAll("[data-strm-run]").forEach((button) => button.addEventListener("click", () => void runStrmJob(button.dataset.strmRun)));
  document.querySelectorAll("[data-strm-rescan]").forEach((button) => button.addEventListener("click", () => void rescanStrm(button.dataset.strmRescan)));
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
    payload.emby_library_refresh_enabled = document.getElementById("strmEmbyRefresh")?.getAttribute("aria-checked") === "true";
    payload.emby_deletion_mode = document.getElementById("strmDeletionMode")?.value || "trash";
    payload.emby_deletion_auto_confirm = document.getElementById("strmAutoDelete")?.getAttribute("aria-checked") === "true";
    const deletionToken = document.getElementById("strmDeletionToken")?.value?.trim();
    if (deletionToken) payload.emby_deletion_webhook_token = deletionToken;
    const key = document.getElementById("strmEmbyKey")?.value?.trim();
    if (key) payload.emby_api_key = key;
  } else {
    const prefix = scope === "p115" ? "p115_strm" : "quark_strm";
    payload[`${prefix}_enabled`] = document.getElementById("strmEnabled")?.getAttribute("aria-checked") === "true";
    payload[`${prefix}_source_root`] = document.getElementById("strmRoot")?.value || "";
    payload[`${prefix}_incremental_cron`] = document.getElementById("strmCron")?.value || "";
    payload[`${prefix}_scrape_enabled`] = document.getElementById("strmScrape")?.getAttribute("aria-checked") === "true";
  payload[`${prefix}_included_directories`] = (document.getElementById("strmInclude")?.value || "").split("\n").map((item) => item.trim()).filter(Boolean);
    payload.strm_min_file_size_mb = Number(document.getElementById("strmMinSize")?.value || 0);
    payload.strm_excluded_name_tokens = (document.getElementById("strmExclude")?.value || "").split(",").map((item) => item.trim()).filter(Boolean);
    if (scope === "p115") {
      payload.p115_strm_life_monitor_enabled = document.getElementById("strmLife")?.getAttribute("aria-checked") === "true";
      payload.p115_strm_life_monitor_path = document.getElementById("strmLifePath")?.value || "";
      payload.p115_strm_life_monitor_interval_seconds = Number(document.getElementById("strmLifeInterval")?.value || 30);
    }
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
      ${libraries.length ? `<div class="media-lib-grid">${libraries.map((lib) => `<div class="media-lib-card">${lib.cover_item_id ? `<img src="/api/integrations/emby/images/${esc(lib.cover_item_id)}" alt="">` : ""}<div class="media-lib-copy"><b>${esc(lib.name)}</b><small>${esc(lib.collection_type || "")}</small></div></div>`).join("")}</div>` : `<div class="empty-state"><b>还没有媒体库</b><span>在 Emby 里创建后刷新。</span></div>`}
    </section>
    <section class="panel panel-pad">
      <div class="panel-head"><div><h2>正在播放</h2><small>实时会话</small></div></div>
      ${sessions.length ? `<div class="list">${sessions.map((item) => `<div class="list-row"><div class="grow"><b>${esc(item.item_name || "")}</b><small>${esc(item.user_name || "")} · ${esc(item.device_name || "")}${item.is_playing ? " · 播放中" : ""}</small></div><span class="pill ${item.is_playing ? "ok" : "muted"}"><i></i>${item.is_playing ? "播放中" : "空闲"}</span></div>`).join("")}</div>` : `<div class="empty-state"><b>当前没有播放</b><span>有会话时会出现在这里。</span></div>`}
    </section>
  </div>
  <section class="panel panel-pad"><div class="panel-head"><div><h2>媒体库封面工坊</h2><small>按媒体库生成拼贴封面，可定时刷新；工坊在独立弹层里操作</small></div><button class="mini-btn primary" data-open-cover>打开封面工坊</button></div><p class="muted-note">支持拼贴 / 陈列 / 马赛克 / 极简四种风格，可单独选择参与刷新的媒体库。</p></section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>最近入库</h2><small>Emby 最近添加的内容</small></div></div>
    ${latest.length ? `<div class="media-latest-grid">${latest.map((item) => `<div class="media-latest" style="${item.has_image ? `background-image:url(/api/integrations/emby/images/${esc(item.id)})` : ""}"><div class="media-latest-body"><b>${esc(item.name)}</b><span>${esc(item.type || "")}${item.year ? ` · ${esc(String(item.year))}` : ""}${item.rating ? ` · ★ ${Number(item.rating).toFixed(1)}` : ""}</span></div></div>`).join("")}</div>` : `<div class="empty-state"><b>暂无最近入库</b><span>Emby 有新内容时会显示。</span></div>`}
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
function openCoverWorkshop() {
  const config = state.config || {};
  const libraries = (mediaState.dashboard && mediaState.dashboard.libraries) || [];
  const selected = new Set(config.emby_cover_library_ids || []);
  const dialog = document.createElement("dialog");
  dialog.className = "picker-dialog cover-workshop";
  dialog.innerHTML = `
  <div class="picker-head"><div><h2>媒体库封面工坊</h2><small>选择风格、刷新计划与参与媒体库，保存后按计划生成</small></div><button class="icon-btn" data-cover-close aria-label="关闭"><svg class="ic ic-sm"><use href="#i-close"/></svg></button></div>
  <div class="form-grid" style="grid-template-columns:repeat(3,minmax(0,1fr));padding:0 18px">
    <div class="field"><label>封面风格</label><select class="input" id="coverStyle">${[["collage", "拼贴"], ["showcase", "陈列"], ["mosaic", "马赛克"], ["minimal", "极简"]].map(([value, label]) => `<option value="${value}" ${config.emby_cover_style === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>
    <div class="field"><label>刷新计划（Cron）</label><input class="input" id="coverCron" value="${esc(config.emby_cover_refresh_cron || "")}" placeholder="0 4 * * *" /></div>
    <div class="field"><label>刷新间隔（小时）</label><input class="input" id="coverHours" type="number" min="1" value="${esc(config.emby_cover_refresh_hours ?? 24)}" /></div>
  </div>
  <div class="field" style="padding:0 18px"><label>参与刷新的媒体库</label><div class="cover-libs">${libraries.map((lib) => `<label class="check"><input type="checkbox" data-cover-lib="${esc(lib.id)}" ${selected.has(lib.id) ? "checked" : ""} /><span>${esc(lib.name)}</span></label>`).join("") || `<span class="muted-note">Emby 未连接或没有媒体库</span>`}</div></div>
  <div class="picker-foot"><button class="mini-btn" data-cover-refresh>立即刷新封面</button><button class="mini-btn primary" data-cover-save>保存封面设置</button></div>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.querySelector("[data-cover-close]").addEventListener("click", () => dialog.close());
  dialog.querySelector("[data-cover-save]").addEventListener("click", () => { void saveCoverSettings(); dialog.close(); });
  dialog.querySelector("[data-cover-refresh]").addEventListener("click", async () => {
    const button = dialog.querySelector("[data-cover-refresh]");
    button.disabled = true;
    try { const result = await api("/api/integrations/emby/cover-refresh", { method: "POST" }); button.textContent = result.message || "已提交"; }
    catch (error) { button.textContent = error.message; }
    button.disabled = false;
  });
  dialog.showModal();
}

function bindMedia() {
  document.querySelector("[data-media-refresh]")?.addEventListener("click", () => void loadMedia());
  document.querySelector("[data-emby-config]")?.addEventListener("click", () => void openEmbyConfig());
  document.querySelector("[data-cover-save]")?.addEventListener("click", () => void saveCoverSettings());
  document.querySelector("[data-open-cover]")?.addEventListener("click", () => openCoverWorkshop());
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
    <div class="subnav" id="settingsTabs" role="tablist" aria-label="设置分区">${SETTINGS_TABS.map(([key, label]) => `<button role="tab" aria-selected="${settingsState.tab === key}" class="${settingsState.tab === key ? "active" : ""}" data-settings-tab="${key}">${label}</button>`).join("")}</div>
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
  return `<div class="chain-wrap">${OVERVIEW_HTML}${WEBHOOK_CHAIN_HTML}</div>`;
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
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>自动调度</h2><small>追更巡检与愿望单检查的全局节奏</small></div></div>
    <div class="switch-row"><div><b>启用追更巡检</b><small>关闭后只能手动执行</small></div><button class="switch" id="setTrackingScheduler" aria-checked="${config.tracking_scheduler_enabled ? "true" : "false"}" aria-label="启用追更巡检"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>巡检周期（分钟）</label><input class="input" id="setTrackingPoll" type="number" min="1" value="${esc(config.tracking_poll_minutes ?? 30)}" /></div>
      <div class="field"><label>默认追更时间</label><input class="input" id="setTrackingTime" type="time" value="${esc(config.tracking_check_time || "20:00")}" /></div>
      <div class="field"><label>失败重试间隔（分钟）</label><input class="input" id="setRetryInterval" type="number" min="1" value="${esc(config.tracking_retry_interval_minutes ?? 120)}" /></div>
      <div class="field"><label>最大重试次数</label><input class="input" id="setMaxRetries" type="number" min="1" value="${esc(config.tracking_max_retries ?? 5)}" /></div>
    </div>
    <div class="switch-row"><div><b>启用愿望单检查</b><small>按小时检查愿望单资源是否上线</small></div><button class="switch" id="setWishlistScheduler" aria-checked="${config.wishlist_scheduler_enabled ? "true" : "false"}" aria-label="启用愿望单检查"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>愿望单默认检查小时</label><input class="input" id="setWishlistHour" type="number" min="0" max="23" value="${esc(config.wishlist_default_check_hour ?? 9)}" /></div>
      <div class="field"><label>愿望单轮询周期（分钟）</label><input class="input" id="setWishlistPoll" type="number" min="1" value="${esc(config.wishlist_poll_minutes ?? 30)}" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="schedule">保存调度设置</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>直接下载</h2><small>发现页粘贴链接后直接保存到指定目录</small></div></div>
    <div class="switch-row"><div><b>允许直接下载</b><small>关闭后只保留智能追更与愿望单</small></div><button class="switch" id="setDirectEnabled" aria-checked="${config.direct_download_enabled ? "true" : "false"}" aria-label="允许直接下载"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>执行网盘</label><select class="input" id="setDirectProvider"><option value="quark" ${config.direct_download_provider !== "p115" ? "selected" : ""}>夸克</option><option value="p115" ${config.direct_download_provider === "p115" ? "selected" : ""}>115</option></select></div>
      <div class="field"><label>保存目录</label><input class="input" id="setDirectPath" value="${esc(config.direct_download_save_path || "")}" /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="direct">保存直接下载设置</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>配置导入导出</h2><small>导出设置与任务数据，便于迁移或备份</small></div></div>
    <div class="row-actions" style="justify-content:flex-start"><button class="mini-btn primary" data-settings-export>导出配置 JSON</button><label class="mini-btn">导入配置<input type="file" accept="application/json" data-settings-import hidden /></label></div>
  </section>
`;
}function settingsNotifications(config) {
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
  </section>

  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>通知时间与云下载</h2><small>限定推送时段，并决定云下载完成后是否通知</small></div></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>推送时间点</label><input class="input" id="setNotifyAt" value="${esc(config.notification_enabled_at || "")}" placeholder="20:00" /></div>
      <div class="field"><label>外部推送总开关</label><input class="input" value="${config.notification_external_enabled ? "已开启" : "已关闭"}" readonly /></div>
    </div>
    <div class="switch-row"><div><b>云下载完成通知</b><small>整理完成后推送结果</small></div><button class="switch" id="setCloudNotify" aria-checked="${config.cloud_download_organizer_enabled ? "true" : "false"}" aria-label="云下载通知"></button></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="notifytime">保存通知时间</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>企业微信机器人</h2><small>群机器人 Webhook 推送</small></div><button class="mini-btn" data-settings-test="wecom">测试</button></div>
    <div class="switch-row"><div><b>启用机器人</b><small>关闭后不推送</small></div><button class="switch" id="setWecomEnabled" aria-checked="${config.wecom_enabled ? "true" : "false"}" aria-label="企业微信机器人"></button></div>
    <div class="field"><label>Webhook Key</label><input class="input" id="setWecomKey" type="password" placeholder="${config.has_wecom_key ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="wecom_bot">保存企业微信机器人</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>企业微信应用</h2><small>应用消息推送，需要企业 ID 与 Secret</small></div></div>
    <div class="switch-row"><div><b>启用应用推送</b><small>关闭后只保留机器人</small></div><button class="switch" id="setWecomAppEnabled" aria-checked="${config.wecom_app_enabled ? "true" : "false"}" aria-label="企业微信应用"></button></div>
    <div class="form-grid" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      <div class="field"><label>企业 ID</label><input class="input" id="setWecomCorp" value="${esc(config.wecom_corp_id || "")}" /></div>
      <div class="field"><label>应用 Secret</label><input class="input" id="setWecomSecret" type="password" placeholder="${config.has_wecom_app_secret ? "已保存，如需更换请重新填写" : "未配置"}" /></div>
      <div class="field"><label>Agent ID</label><input class="input" id="setWecomAgent" value="${esc(config.wecom_app_agent_id ?? "")}" /></div>
      <div class="field"><label>回调地址</label><input class="input" id="setWecomCallback" value="${esc(config.wecom_callback_url || "")}" placeholder="https://..." /></div>
    </div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="wecom_app">保存企业微信应用</button></div>
  </section>
  <section class="panel panel-pad">
    <div class="panel-head"><div><h2>交互指令</h2><small>Telegram 机器人支持的指令，回复消息即可操作</small></div></div>
    <div class="list">
      <div class="list-row"><div class="grow"><b>/search 关键词</b><small>搜索资源并返回候选</small></div></div>
      <div class="list-row"><div class="grow"><b>/track 剧名</b><small>加入智能追更</small></div></div>
      <div class="list-row"><div class="grow"><b>/wish 片名</b><small>加入愿望单</small></div></div>
      <div class="list-row"><div class="grow"><b>/status</b><small>查看任务与巡检状态</small></div></div>
      <div class="list-row"><div class="grow"><b>/pause | /resume</b><small>暂停或恢复追更任务</small></div></div>
    </div>
  </section>
`;
}function settingsNetwork(config) {
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
    <div class="panel-head"><div><h2>开发者选项</h2><small>远程诊断与运行时信息</small></div></div>
    <div class="switch-row"><div><b>远程诊断</b><small>允许维护者读取脱敏运行日志</small></div><button class="switch" id="setDiagnostics" aria-checked="${config.developer_remote_diagnostics_enabled ? "true" : "false"}" aria-label="远程诊断"></button></div>
    <div class="row-actions" style="margin-top:12px"><button class="mini-btn primary" data-settings-save="developer">保存开发者选项</button></div>
    <div class="panel-head" style="margin-top:14px"><div><h2>运行状态</h2><small>当前后端配置快照</small></div></div>
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
  bindSettingsControls();
  bindSettings();
}

async function loadSettings() {
  const body = document.getElementById("settingsBody");
  if (body) body.innerHTML = `<div class="loading-block">正在读取配置…</div>`;
  settingsState.config = await api("/api/config/status").catch(() => null);
  state.config = settingsState.config || state.config;
  if (!settingsState.config) { body.innerHTML = `<section class="panel panel-pad"><div class="empty-state"><b>配置读取失败</b><span>请稍后重试</span></div></section>`; return; }
  renderSettingsBody();
  bindSettings();
}

function bindSettingsControls() {
  document.querySelectorAll("#settingsBody .switch").forEach((button) => button.addEventListener("click", () => button.setAttribute("aria-checked", button.getAttribute("aria-checked") === "true" ? "false" : "true")));
  document.querySelectorAll("#settingsBody [data-settings-save]").forEach((button) => button.addEventListener("click", () => void saveSettings(button.dataset.settingsSave)));
  document.querySelectorAll("#settingsBody [data-settings-test]").forEach((button) => button.addEventListener("click", () => void testSettings(button.dataset.settingsTest)));
  document.querySelector("#settingsBody [data-settings-export]")?.addEventListener("click", () => void exportSettings());
  document.querySelector("#settingsBody [data-settings-import]")?.addEventListener("change", (event) => { const file = event.target.files && event.target.files[0]; if (file) void importSettings(file); });
}

function bindSettings() {
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "1";
    button.addEventListener("click", () => {
    settingsState.tab = button.dataset.settingsTab;
    settingsState.result = null;
    document.querySelectorAll("[data-settings-tab]").forEach((chip) => { const on = chip.dataset.settingsTab === settingsState.tab; chip.classList.toggle("active", on); chip.setAttribute("aria-selected", String(on)); });
      renderSettingsBody();
    });
  });
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
  } else if (scope === "schedule") {
    payload.tracking_scheduler_enabled = document.getElementById("setTrackingScheduler")?.getAttribute("aria-checked") === "true";
    payload.tracking_poll_minutes = Number(document.getElementById("setTrackingPoll")?.value || 30);
    payload.tracking_check_time = document.getElementById("setTrackingTime")?.value || "20:00";
    payload.tracking_retry_interval_minutes = Number(document.getElementById("setRetryInterval")?.value || 120);
    payload.tracking_max_retries = Number(document.getElementById("setMaxRetries")?.value || 5);
    payload.wishlist_scheduler_enabled = document.getElementById("setWishlistScheduler")?.getAttribute("aria-checked") === "true";
    payload.wishlist_default_check_hour = Number(document.getElementById("setWishlistHour")?.value || 9);
    payload.wishlist_poll_minutes = Number(document.getElementById("setWishlistPoll")?.value || 30);
  } else if (scope === "direct") {
    payload.direct_download_enabled = document.getElementById("setDirectEnabled")?.getAttribute("aria-checked") === "true";
    payload.direct_download_provider = document.getElementById("setDirectProvider")?.value || "quark";
    payload.direct_download_save_path = document.getElementById("setDirectPath")?.value || "";
  } else if (scope === "notifytime") {
    payload.notification_enabled_at = document.getElementById("setNotifyAt")?.value || "";
  } else if (scope === "developer") {
    payload.developer_remote_diagnostics_enabled = document.getElementById("setDiagnostics")?.getAttribute("aria-checked") === "true";
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
  document.querySelectorAll("[data-discover-section]").forEach((button) => button.addEventListener("click", () => { discoverState.section = button.dataset.discoverSection; document.querySelectorAll("[data-discover-section]").forEach((chip) => { const on = chip.dataset.discoverSection === discoverState.section; chip.classList.toggle("active", on); chip.setAttribute("aria-selected", String(on)); }); void loadDiscover(); }));
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
  } catch (error) {
    console.error(error);
    document.getElementById("root").innerHTML = loginView(error && error.message ? `加载失败：${error.message}` : "");
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
