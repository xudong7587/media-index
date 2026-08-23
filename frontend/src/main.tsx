import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowClockwise,
  ArrowSquareOut,
  Bell,
  CaretDown,
  CaretLeft,
  CaretRight,
  CaretUp,
  Check,
  CheckCircle,
  CheckSquare,
  Checks,
  CloudArrowDown,
  Eye,
  HardDrives,
  Heart,
  File,
  FloppyDisk,
  FolderOpen,
  Info,
  MagnifyingGlass,
  MinusCircle,
  Pause,
  PaperPlaneTilt,
  Play,
  PlusCircle,
  Question,
  ShareNetwork,
  Trash,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { api, ApiError, ConfigStatus, Genre, MediaItem, MediaWorkflow, NotificationItem, OpenListCopyTask, OpenListEntry, ResourceCandidateOption, ResourceStatus, ReviewCandidate, TrackingProviderState, TrackingTask, TransferBatch, TransferJob, WecomTransferRecord, WishlistItem } from "./lib/api";
import { ConfigBackupSettings } from "./features/settings/ConfigBackupSettings";
import { TrackingRunStatus } from "./features/tracking/TrackingRunStatus";
import { buildConfigPayload, CategoryPathSettings, FilterRow, ProviderConnectionStatus, SettingsInput, SettingsNumberInput, SettingsToggle } from "./features/settings/SettingsFormParts";
import { normalizeCategoryInputPath, normalizeOpenListPath, OpenListDirectoryPicker, Segmented, SettingsSection } from "./features/settings/SettingsUi";
import { OpenListManualSync } from "./features/openlist/OpenListManualSync";
import { matchOpenListTasks, OpenListTaskMonitor, OpenListTaskPanel } from "./features/openlist/OpenListTaskMonitor";
import { Empty, Poster, PosterSkeleton } from "./features/discover/MediaPrimitives";
import { DiscoverExploreView, DiscoveryGroup, MediaDetailScaffold } from "./features/discover/DiscoveryViews";
import { CommandReference, ProviderDirectoryPicker } from "./features/openlist/OpenListSettingsTools";
import { ActivityCenter } from "./features/activity/ActivityCenter";
import { ApplicationShell } from "./app/ApplicationShell";
import { AppRoute, hashForRoute, routeFromHash, sameRoute } from "./app/routes";
import { StrmPortal } from "./features/strm/StrmPortal";
import { CloudConnectionsPage, TransferRulesPage } from "./features/workspace/WorkspaceSections";
import { TaskCenterPage } from "./features/workspace/TaskCenterPage";
import { ResourceAcquisitionPage } from "./features/workspace/ResourceAcquisitionPage";
import { MediaServerDashboard } from "./features/media-server/MediaServerDashboard";
import { DiscoveryRankings } from "./features/discover/DiscoveryRankings";
import "./styles.css";
import "./app/emil-workbench.css";

type SettingsTab = "basic" | "drives" | "openlist" | "notifications" | "wishlist" | "network";
type Theme = "light" | "dark";
type CloudProvider = "qas" | "quark" | "p115";

function BrandLogo({ login = false }: { login?: boolean }) {
  return <img className={`brand-logo ${login ? "login-brand-logo" : ""}`} src="/assets/media-index-icon.png" alt="Media Index" />;
}

function App() {
  const [user, setUser] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("mi-theme") as Theme) || "light");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("mi-theme", theme);
  }, [theme]);

  useEffect(() => {
    api
      .me()
      .then((res) => setUser(res.user))
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="boot">Media Index</div>;
  if (!user) return <Login onDone={setUser} />;
  return <Shell user={user} theme={theme} setTheme={setTheme} onLogout={() => setUser(null)} />;
}

function Login({ onDone }: { onDone: (user: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.login(username.trim(), password);
      onDone(res.user);
    } catch {
      setError("用户名或密码不正确");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-panel" onSubmit={submit}>
        <BrandLogo login />
        <h1>Media Index</h1>
        <p>登录你的 NAS 媒体自动化控制台。</p>
        <label>
          用户名
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
        </label>
        <label>
          密码
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? "登录中" : "登录"}
        </button>
        {error && <div className="form-error">{error}</div>}
      </form>
    </main>
  );
}

function Shell({
  user,
  theme,
  setTheme,
  onLogout,
}: {
  user: string;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  onLogout: () => void;
}) {
  const [route, setRoute] = useState<AppRoute>(() => routeFromHash());
  const [enabledProviders, setEnabledProviders] = useState<CloudProvider[]>([]);

  useEffect(() => {
    const syncRoute = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", syncRoute);
    return () => window.removeEventListener("hashchange", syncRoute);
  }, []);

  useEffect(() => {
    let active = true;
    async function refreshProviders() {
      try {
        const config = await api.config();
        if (!active) return;
        setEnabledProviders((["quark", "p115"] as const).filter((value) => config.enabled_providers.includes(value)));
      } catch {
        if (active) setEnabledProviders(["quark"]);
      }
    }
    void refreshProviders();
    window.addEventListener("mediaindex:providers-changed", refreshProviders);
    return () => {
      active = false;
      window.removeEventListener("mediaindex:providers-changed", refreshProviders);
    };
  }, []);

  async function logout() {
    await api.logout().catch(() => undefined);
    onLogout();
  }

  function navigate(next: AppRoute) {
    if (sameRoute(route, next)) return;
    window.history.replaceState(null, "", hashForRoute(next));
    setRoute(next);
  }

  return (
    <ApplicationShell
      user={user}
      theme={theme}
      route={route}
      onNavigate={navigate}
      onThemeChange={() => setTheme(theme === "light" ? "dark" : "light")}
      onLogout={() => void logout()}
      activity={<><ActivityCenter /><NotificationCenter onNavigate={navigate} /></>}
    >
      {route.page === "discover" && <DiscoverPage enabledProviders={enabledProviders} />}
      {route.page === "workspace" && <WorkspacePortal route={route} onNavigate={navigate} />}
      {route.page === "subscriptions" && <SubscriptionWorkspace enabledProviders={enabledProviders} onOpenConnections={() => navigate({ page: "workspace", section: "connections" })} />}
      {route.page === "cross-cloud" && <CrossCloudPage onNavigate={navigate} />}
      {route.page === "strm" && <StrmPortal route={route} onNavigate={navigate} />}
      {route.page === "media-server" && <MediaServerDashboard onNavigate={navigate} />}
      {route.page === "system" && <SettingsHub />}
    </ApplicationShell>
  );
}

function CrossCloudPage({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [message, setMessage] = useState("");
  const [openListTasks, setOpenListTasks] = useState<OpenListCopyTask[]>([]);

  useEffect(() => {
    void api.config().then(setConfig).catch((error: Error) => setMessage(error.message));
    let active = true;
    let taskLoading = false;
    const refreshTasks = async () => {
      if (taskLoading) return;
      taskLoading = true;
      try { const result = await api.openListTasks(); if (active) setOpenListTasks(result.tasks); }
      catch { if (active) setOpenListTasks([]); }
      finally { taskLoading = false; }
    };
    refreshTasks();
    const timer = window.setInterval(refreshTasks, 2_500);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const openListReady = Boolean(config?.openlist_enabled && config.has_openlist_token);
  return (
    <section className="cross-cloud-page">
      <div className="page-head"><div><p className="eyebrow">OPENLIST COPY</p><h1>跨盘转存</h1><p>通过已有 OpenList 挂载选择源与目标，并沿用正式的手动同步任务链路。</p></div></div>
      <section className="openlist-transfer-boundary">
        <div><HardDrives size={24} weight="fill" /><div><strong>执行器：OpenList</strong><p>数据会经过 OpenList 所在节点；是否落盘、临时目录位置及残留清理由 OpenList 的存储与复制配置决定。这里不宣称原生秒传，也不保证无临时残留。</p></div></div>
        <div className="settings-action-strip">
          <button type="button" className="ghost compact-action" onClick={() => onNavigate({ page: "system", section: "openlist" })}><ArrowSquareOut />前往 OpenList 配置</button>
          <button type="button" className="ghost compact-action" onClick={() => onNavigate({ page: "workspace", section: "tasks" })}><ArrowSquareOut />查看任务中心</button>
        </div>
      </section>
      {message && <div className="settings-inline-result error">{message}</div>}
      {!config && !message && <div className="workspace-loading"><Spinner />正在读取 OpenList 配置</div>}
      {config && <>
        {!openListReady && <div className="settings-inline-result error">OpenList 尚未启用或 Token 未保存。请先完成连接与挂载目录配置，再回到本页选择源和目标。</div>}
        <OpenListManualSync qasPath={config.openlist_qas_library_path} p115Path={config.openlist_p115_library_path} enabled={openListReady} />
        <section className="openlist-live-tasks">
          <header><div><h2>OpenList 复制进度</h2><p>使用已保存的 OpenList Token 每 2.5 秒读取其原生复制队列。</p></div><span>{openListTasks.filter((task) => task.state === "running").length} 个进行中</span></header>
          <OpenListTaskMonitor tasks={openListTasks.slice(0, 30)} />
        </section>
      </>}
    </section>
  );
}

function WorkspacePortal({ route, onNavigate }: { route: AppRoute; onNavigate: (route: AppRoute) => void }) {
  const section = route.section || "connections";
  const items: Array<{ key: string; label: string }> = [
    { key: "connections", label: "网盘连接" },
    { key: "sources", label: "资源获取" },
    { key: "rules", label: "转存和整理规则" },
    { key: "tasks", label: "任务中心" },
  ];

  return (
    <section className="workspace-portal">
      <div className="page-head workspace-portal-head">
        <div>
          <p className="eyebrow">CLOUD WORKSPACE</p>
          <h1>网盘工作台</h1>
          <p>连接网盘、定义通用与网盘路径规则，并统一查看转存和整理任务。</p>
        </div>
      </div>
      <nav className="portal-subnav" aria-label="网盘工作台模块">
        {items.map((item) => <button key={item.key} type="button" className={section === item.key ? "active" : ""} onClick={() => onNavigate({ page: "workspace", section: item.key === "connections" ? undefined : item.key })}>{item.label}</button>)}
      </nav>
      {section === "connections" && <CloudConnectionsPage />}
      {section === "sources" && <ResourceAcquisitionPage />}
      {section === "rules" && <TransferRulesPage />}
      {section === "tasks" && <TaskCenterPage />}
    </section>
  );
}

function SubscriptionWorkspace({ enabledProviders, onOpenConnections }: { enabledProviders: CloudProvider[]; onOpenConnections: () => void }) {
  const [tab, setTab] = useState<"tracking" | "wishlist">("tracking");
  return (
    <section className="subscription-workspace primary-subscription-page">
      <div className="page-head subscription-page-head"><div><p className="eyebrow">SUBSCRIPTIONS</p><h1>订阅与追更</h1><p>发现负责添加媒体；这里统一管理追更、愿望、执行网盘和巡检结果。</p></div></div>
      <div className="portal-tabs" role="tablist" aria-label="订阅类型">
        <button type="button" role="tab" aria-selected={tab === "tracking"} className={tab === "tracking" ? "active" : ""} onClick={() => setTab("tracking")}>智能追更</button>
        <button type="button" role="tab" aria-selected={tab === "wishlist"} className={tab === "wishlist" ? "active" : ""} onClick={() => setTab("wishlist")}>愿望单</button>
      </div>
      {tab === "tracking" ? <TrackingPage enabledProviders={enabledProviders} onOpenConnections={onOpenConnections} /> : <WishlistPage enabledProviders={enabledProviders} />}
    </section>
  );
}

function DiscoverPage({ enabledProviders }: { enabledProviders: CloudProvider[] }) {
  const [discoverSection, setDiscoverSection] = useState<"explore" | "rankings">("explore");
  const [mediaType, setMediaType] = useState<"movie" | "tv" | "variety" | "concert" | "documentary" | "anime">("movie");
  const [region, setRegion] = useState("");
  const [sort, setSort] = useState("hot");
  const [genre, setGenre] = useState("");
  const [genres, setGenres] = useState<Genre[]>([]);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MediaItem[]>([]);
  const [exploreGroups, setExploreGroups] = useState<DiscoveryGroup[]>([]);
  const [exploreLoading, setExploreLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<MediaItem | null>(null);
  const [trackingSelection, setTrackingSelection] = useState<MediaItem | null>(null);
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [trackingAction, setTrackingAction] = useState("");
  const [pageMessage, setPageMessage] = useState("");
  const [discoverPage, setDiscoverPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [searchHistory, setSearchHistory] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("mi-discover-search-history") || "[]");
      return Array.isArray(saved) ? saved.filter((value): value is string => typeof value === "string" && Boolean(value.trim())).slice(0, 10) : [];
    } catch {
      return [];
    }
  });
  const [searchHistoryOpen, setSearchHistoryOpen] = useState(false);
  const searchRef = useRef<HTMLFormElement | null>(null);

  async function load(page = discoverPage, refresh = false, searchValue = query) {
    setLoading(true);
    setError("");
    try {
      const searchTerm = searchValue.trim();
      const res = searchTerm ? await api.search(searchTerm) : await api.discover(mediaType, region, sort, genre, 0, page, 24, refresh);
      setItems(Array.from(new Map((res.results || []).map((item) => [`${item.media_type}-${item.tmdb_id}`, item])).values()));
      setTotalPages("total_pages" in res && typeof res.total_pages === "number" ? res.total_pages || 1 : 1);
      if ("page" in res && typeof res.page === "number") setDiscoverPage(res.page);
      if ("error" in res && res.error) setError("TMDB 尚未配置");
    } catch {
      setError("加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadExplore(refresh = false) {
    setExploreLoading(true);
    setError("");
    try {
      const definitions = [
        ["hot", "正在热播", "近期最受关注的电影与节目"],
        ["rating", "口碑精选", "按 TMDB 评分发现值得看的作品"],
        ["latest", "最近上线", "浏览最近上映和更新的内容"],
      ] as const;
      const responses = await Promise.all(definitions.map(([key]) => api.discover(mediaType, region, key, genre, 0, 1, 14, refresh)));
      setExploreGroups(definitions.map(([key, title, description], index) => ({
        key, title, description,
        items: Array.from(new Map((responses[index].results || []).map((entry) => [`${entry.media_type}-${entry.tmdb_id}`, entry])).values()),
      })));
    } catch {
      setError("加载失败");
    } finally {
      setExploreLoading(false);
    }
  }

  useEffect(() => {
    setDiscoverPage(1);
    if (discoverSection === "explore") void loadExplore();
  }, [mediaType, region, sort, genre, discoverSection]);

  useEffect(() => {
    setGenre("");
    api.genres(mediaType).then(setGenres).catch(() => setGenres([]));
  }, [mediaType]);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    localStorage.setItem("mi-discover-search-history", JSON.stringify(searchHistory));
  }, [searchHistory]);

  useEffect(() => {
    if (!searchHistoryOpen) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!searchRef.current?.contains(event.target as Node)) setSearchHistoryOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [searchHistoryOpen]);

  function rememberSearch(value: string) {
    const normalized = value.trim();
    if (!normalized) return;
    setSearchHistory((current) => [normalized, ...current.filter((item) => item !== normalized)].slice(0, 10));
  }

  function selectSearchHistory(value: string) {
    setQuery(value);
    setDiscoverPage(1);
    setSearchHistoryOpen(false);
    void load(1, false, value);
  }

  async function addTrackingFromDiscover(item: MediaItem) {
    const actionKey = `${item.media_type}-${item.tmdb_id}`;
    setTrackingAction(actionKey);
    setPageMessage("");
    try {
      const detail = await api.details(item.media_type, item.tmdb_id);
      const media = { ...detail, category: item.category || detail.category || item.media_type };
      const seasons = (detail.seasons || []).filter((season) => season.season_number > 0);
      const latest = seasons.at(-1)?.season_number ?? 1;
      const providers = enabledProviders.length ? enabledProviders : (["quark"] as CloudProvider[]);
      await Promise.all(providers.map((provider) => api.createTracking(media, latest, "cloud", provider)));
      const ongoingText = detail.status && detail.status !== "Ended" ? "，连载中媒体已按最新季追更" : "";
      setPageMessage(`已将《${item.title}》加入智能追更${ongoingText}。`);
    } catch (error) {
      setPageMessage(error instanceof Error ? error.message : "加入智能追更失败");
    } finally {
      setTrackingAction("");
    }
  }

  if (selected) {
    return <MediaDialog item={selected} onClose={() => setSelected(null)} enabledProviders={enabledProviders} />;
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>发现</h1>
          <p>从 TMDB 发现内容，确认后交给已启用的网盘执行转存。</p>
        </div>
        <form
          ref={searchRef}
          className={`search search-history ${searchHistoryOpen ? "is-open" : ""}`}
          onSubmit={(event) => {
            event.preventDefault();
            rememberSearch(query);
            setSearchHistoryOpen(false);
            setDiscoverPage(1);
            void load(1, false, query);
          }}
        >
          <MagnifyingGlass size={18} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onFocus={() => setSearchHistoryOpen(true)}
            placeholder="搜索电影、剧集、综艺等内容"
            aria-label="搜索电影、剧集、综艺等内容"
          />
          {searchHistoryOpen && searchHistory.length > 0 && (
            <div className="search-history-menu" role="listbox" aria-label="历史搜索">
              <div className="search-history-head">
                <span>历史搜索</span>
                <button type="button" onClick={() => setSearchHistory([])}>清除</button>
              </div>
              {searchHistory.map((value) => (
                <button type="button" className="search-history-item" key={value} onClick={() => selectSearchHistory(value)}>
                  <span>{value}</span>
                  <ArrowClockwise size={14} />
                </button>
              ))}
            </div>
          )}
        </form>
      </div>

      <nav className="portal-subnav discover-subnav" aria-label="发现模块">
        <button type="button" className={discoverSection === "explore" ? "active" : ""} onClick={() => setDiscoverSection("explore")}>影视探索</button>
        <button type="button" className={discoverSection === "rankings" ? "active" : ""} onClick={() => { setDiscoverSection("rankings"); setSort("hot"); setDiscoverPage(1); }}>榜单推荐</button>
      </nav>

      {(discoverSection === "explore" || query.trim()) && <div className="toolbar">
        <Segmented
          value={mediaType}
          items={[
            ["movie", "电影"],
            ["tv", "电视剧"],
            ["variety", "综艺"],
            ["concert", "演唱会"],
            ["documentary", "纪录片"],
            ["anime", "动漫"],
          ]}
          onChange={(value) => setMediaType(value as typeof mediaType)}
        />
        {discoverSection === "explore" && <Segmented
          value={region}
          items={[
            ["", "全部"],
            ["cn", "华语"],
          ]}
          onChange={setRegion}
        />}
        <button className="ghost" onClick={() => void (discoverSection === "explore" && !query.trim() ? loadExplore(true) : load(discoverPage, true))} disabled={loading || exploreLoading}>
          <ArrowClockwise size={16} />
          刷新
        </button>
      </div>}

      {discoverSection === "explore" && !query.trim() && exploreLoading && <PosterSkeleton />}
      {query.trim() && loading && <PosterSkeleton />}
      {!loading && !exploreLoading && error && <Empty title={error} body="请到发现相关设置确认 TMDB 配置。" />}
      {pageMessage && <div className="notice page-notice">{pageMessage}</div>}
      {discoverSection === "explore" && !query.trim() && !exploreLoading && !error && <DiscoverExploreView groups={exploreGroups} busyKey={trackingAction} canTrack={(entry) => canSmartTrackMedia(entry, mediaType)} onSelect={setSelected} onTrack={setTrackingSelection} />}
      {discoverSection === "rankings" && !query.trim() && <DiscoveryRankings onSelect={setSelected} onTrack={setTrackingSelection} busyKey={trackingAction} canTrack={(entry) => canSmartTrackMedia(entry, entry.media_type)} />}
      {query.trim() && !loading && !error && items.length === 0 && <Empty title="没有结果" body="换个关键词或分类试试。" />}
      {query.trim() && !loading && !error && (
        <>
          <div className="poster-grid">
            {items.map((item) => {
              const canTrack = canSmartTrackMedia(item, mediaType);
              return (
                <article className="poster-card" key={`${item.media_type}-${item.tmdb_id}`}>
                  <button className="poster-card-main" onClick={() => setSelected(item)} aria-label={`查看${item.title}详情`}>
                    <Poster item={item} />
                    <span className="poster-title">{item.title}</span>
                    <span className="poster-meta">{item.release_date ? `发行 ${item.release_date}` : item.year ? `发行 ${item.year}` : "发行日期待定"}</span>
                  </button>
                  {canTrack && (
                    <button
                      type="button"
                      className="poster-track-action"
                      onClick={() => setTrackingSelection(item)}
                      aria-label={`将${item.title}加入智能追更`}
                      disabled={trackingAction === `${item.media_type}-${item.tmdb_id}`}
                    >
                      {trackingAction === `${item.media_type}-${item.tmdb_id}` ? <Spinner /> : <Eye size={15} />}
                      {trackingAction === `${item.media_type}-${item.tmdb_id}` ? "加入中" : "加入智能追更"}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
          {!query.trim() && items.length > 0 && (
            <div className="pagination-bar" aria-label="发现分页">
              <span>第 {discoverPage} 页 / 共 {totalPages} 页</span>
              <button
                className="pagination-arrow"
                disabled={discoverPage <= 1 || loading}
                onClick={() => {
                  const prev = Math.max(1, discoverPage - 1);
                  setDiscoverPage(prev);
                  void load(prev);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                title="上一页"
              >
                <CaretLeft size={16} weight="bold" />
              </button>
              <button
                className="pagination-arrow next"
                disabled={discoverPage >= totalPages || loading}
                onClick={() => {
                  const next = discoverPage + 1;
                  setDiscoverPage(next);
                  void load(next);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                title="下一页"
              >
                <CaretRight size={16} weight="bold" />
              </button>
            </div>
          )}
        </>
      )}
      {trackingSelection && (
        <TrackingCategoryDialog
          item={trackingSelection}
          config={config}
          onClose={() => setTrackingSelection(null)}
          onSelect={(category) => {
            const next = { ...trackingSelection, category };
            setTrackingSelection(null);
            void addTrackingFromDiscover(next);
          }}
        />
      )}
    </section>
  );
}

function TrackingCategoryDialog({
  item,
  config,
  action = "tracking",
  onClose,
  onSelect,
}: {
  item: MediaItem;
  config: ConfigStatus | null;
  action?: "tracking" | "transfer";
  onClose: () => void;
  onSelect: (category: NonNullable<MediaItem["category"]>) => void;
}) {
  const categories: NonNullable<MediaItem["category"]>[] = item.media_type === "movie"
    ? ["movie"]
    : ["tv", "anime", "variety", "documentary"];
  const configuredPaths = config?.category_paths || {};
  const qasPaths = config?.qas_category_paths || {};
  const p115Paths = config?.p115_category_paths || {};
  const actionText = action === "transfer" ? "转存到网盘" : "加入智能追更";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="tracking-category-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">×</button>
        <div className="tracking-category-heading">
          <div>
            <h2>选择媒体库目录</h2>
            <p>{item.title}将按所选分类{actionText}。</p>
          </div>
          <FolderOpen size={28} aria-hidden />
        </div>
        <div className="tracking-category-options">
          {categories.map((category) => {
            const fallback = configuredPaths[category] || "未设置";
            const qasPath = qasPaths[category] || fallback;
            const p115Path = p115Paths[category] || fallback;
            return (
              <button type="button" className="tracking-category-option" key={category} onClick={() => onSelect(category)}>
                <span className="tracking-category-option-title">{mediaTypeLabel(category)}</span>
                <span>夸克：{qasPath}</span>
                <span>115：{p115Path}</span>
                <CaretRight size={17} />
              </button>
            );
          })}
        </div>
        {!config && <p className="settings-help">正在读取已保存的目录配置，未读取到时仍可继续使用默认分类。</p>}
      </article>
    </div>
  );
}

function MediaDialog({ item, onClose, enabledProviders }: { item: MediaItem; onClose: () => void; enabledProviders: CloudProvider[] }) {
  const [detail, setDetail] = useState<MediaItem | null>(null);
  const [selectedSeasons, setSelectedSeasons] = useState<number[]>([]);
  const [expandedSeason, setExpandedSeason] = useState<number | null>(null);
  const [selectedSeasonEpisodes, setSelectedSeasonEpisodes] = useState<Record<number, number[]>>({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"" | "cloud" | "local">("");
  const [completed, setCompleted] = useState<"" | "cloud" | "local">("");
  const [seasonResources, setSeasonResources] = useState<Record<string, ResourceStatus>>({});
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceLoadingKeys, setResourceLoadingKeys] = useState<string[]>([]);
  const [resourceStage, setResourceStage] = useState(0);
  const [trackingTasks, setTrackingTasks] = useState<TrackingTask[]>([]);
  const [progressStage, setProgressStage] = useState("");
  const [progressSeason, setProgressSeason] = useState(0);
  const [progressProvider, setProgressProvider] = useState<CloudProvider | "">("");
  const [copiedProvider, setCopiedProvider] = useState<CloudProvider | "">("");
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [categoryPrompt, setCategoryPrompt] = useState<"" | "tracking" | "cloud">("");
  const [candidateChoice, setCandidateChoice] = useState<{ provider: CloudProvider; options: Array<ResourceCandidateOption & { season_number: number }> } | null>(null);
  const [candidateLoadingProvider, setCandidateLoadingProvider] = useState<CloudProvider | "">("");
  const [manualLink, setManualLink] = useState("");
  const [manualLinkBusy, setManualLinkBusy] = useState(false);
  const [manualLinkMessage, setManualLinkMessage] = useState("");
  const [workflow, setWorkflow] = useState<MediaWorkflow | null>(null);

  useEffect(() => {
    api.details(item.media_type, item.tmdb_id).then((data) => {
      setDetail({ ...data, category: item.category || data.category });
      const latest = data.seasons?.at(-1)?.season_number ?? 1;
      setSelectedSeasons([latest]);
    });
  }, [item]);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    let active = true;
    async function loadWorkflow() {
      try {
        const next = await api.mediaWorkflow(item.media_type, item.tmdb_id);
        if (active) setWorkflow(next);
      } catch {
        if (active) setWorkflow(null);
      }
    }
    void loadWorkflow();
    const timer = window.setInterval(() => void loadWorkflow(), 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [item.media_type, item.tmdb_id]);

  const media = detail || item;
  const canTrack = canSmartTrackMedia(media);
  const isOngoing = canTrack && media.status !== "Ended";
  const seasons = (media.seasons || []).filter((value) => value.season_number > 0);
  const latestSeason = seasons.at(-1)?.season_number ?? 1;
  const orderedSelection = [...selectedSeasons].sort((a, b) => a - b);
  const allSeasonsSelected = seasons.length > 0 && orderedSelection.length === seasons.length;
  const resourceSelection = canTrack ? orderedSelection : [0];
  const isResourceReady = (status?: ResourceStatus) => Boolean(status && (status.ready ?? (status.found && !status.requires_review)));
  function expectedEpisodeNumbers(seasonNumber: number) {
    if (!canTrack || seasonNumber <= 0) return [];
    const selected = selectedSeasonEpisodes[seasonNumber];
    if (selected) return selected;
    const episodeCount = media.seasons?.find((season) => season.season_number === seasonNumber)?.episode_count || 0;
    return episodeCount > 0 ? Array.from({ length: episodeCount }, (_, index) => index + 1) : [];
  }

  function resourceCoverage(status: ResourceStatus | undefined, seasonNumber: number) {
    const expected = expectedEpisodeNumbers(seasonNumber);
    if (!expected.length) return isResourceReady(status) ? 1 : 0;
    const covered = new Set(status?.episode_numbers || []);
    return expected.filter((number) => covered.has(number)).length / expected.length;
  }

  function isResourceComplete(status: ResourceStatus | undefined, seasonNumber: number) {
    if (!isResourceReady(status)) return false;
    return resourceCoverage(status, seasonNumber) >= 1;
  }

  function resourceConfidence(status: ResourceStatus | undefined, seasonNumber: number, score = 0, confirmed = false) {
    if (!status?.found) return null;
    if (confirmed && isResourceComplete(status, seasonNumber)) return 100;
    const scorePercent = Math.min(99, Math.max(0, Math.round(score)));
    if (!canTrack || seasonNumber <= 0) return scorePercent || 50;
    const coveragePercent = Math.round(resourceCoverage(status, seasonNumber) * 100);
    return Math.max(1, Math.min(99, Math.min(coveragePercent || scorePercent || 50, scorePercent || coveragePercent || 50)));
  }
  const allResourcesFound = resourceSelection.length > 0 && resourceSelection.every((number) =>
    enabledProviders.some((provider) => isResourceReady(seasonResources[resourceKey(provider, number)])),
  );
  const isTracked = canTrack && orderedSelection.some((number) => trackingTasks.some((task) => task.tmdb_id === media.tmdb_id && task.season_number === number));
  const localProvider: CloudProvider | undefined = enabledProviders.includes("qas")
    ? "qas"
    : enabledProviders.includes("p115")
      ? "p115"
      : undefined;
  const canSaveCloud = allResourcesFound && !resourceLoading && !busy && !completed;
  const localResourcesFound = Boolean(
    localProvider
    && resourceSelection.every((number) => isResourceReady(seasonResources[resourceKey(localProvider, number)])),
  );
  const canSaveLocal = localResourcesFound && !resourceLoading && !busy && !completed;
  const canToggleOpenListAutoSync = Boolean(
    enabledProviders.includes("qas")
    && enabledProviders.includes("p115")
    && config?.openlist_enabled
    && config.has_openlist_token
    && config.openlist_qas_library_path
    && config.openlist_p115_library_path,
  );
  const saveDisabledReason = resourceLoading
    ? "正在分别验证夸克和 115 资源"
    : !allResourcesFound
      ? "每个已选季度至少需要一个网盘找到可用资源"
      : busy
        ? "正在执行转存"
        : completed
          ? "本次转存已完成"
          : "";

  async function submitManualLink(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const link = manualLink.trim();
    if (!link || manualLinkBusy) return;
    const category = media.category || media.media_type || "movie";
    setManualLinkBusy(true);
    setManualLinkMessage("");
    try {
      const preview = await api.directLinkOptions(link, media.title, media.year || "", category);
      const option = preview.options.find((item) => item.category === category) || preview.options[0];
      if (!option) throw new Error("未找到可用的媒体库目录");
      const result = await api.directLinkTransfer(
        preview.link,
        option.path || preview.root_path,
        media.title,
        preview.year || media.year || "",
        option.category || category,
      );
      setManualLink("");
      setManualLinkMessage(result.message || "转存已执行，可在右上角任务中心查看结果");
    } catch (error) {
      setManualLinkMessage(error instanceof ApiError || error instanceof Error ? error.message : "链接转存失败");
    } finally {
      setManualLinkBusy(false);
    }
  }

  useEffect(() => {
    if (!canTrack) return;
    api.tracking().then(setTrackingTasks).catch(() => setTrackingTasks([]));
  }, [canTrack, media.tmdb_id]);

  useEffect(() => {
    if (!resourceLoading) return;
    setResourceStage(0);
    const timer = window.setInterval(() => setResourceStage((current) => Math.min(current + 1, 3)), 1400);
    return () => window.clearInterval(timer);
  }, [resourceLoading, selectedSeasons.join(",")]);

  useEffect(() => {
    if (!detail || !enabledProviders.length) return;
    const seasonNumbers = (detail.seasons || []).map((season) => season.season_number).filter((number) => number > 0);
    const numbers = seasonNumbers.length ? seasonNumbers : [0];
    void Promise.all(
      numbers.flatMap((number) =>
        enabledProviders.map(async (provider) => [
          resourceKey(provider, number),
          await api.cachedResource(detail, number || undefined, provider),
        ] as const),
      ),
    ).then((entries) => {
      setSeasonResources((current) => {
        const next = { ...current };
        for (const [key, status] of entries) if (status) next[key] = status;
        return next;
      });
    });
  }, [detail, enabledProviders.join(",")]);

  useEffect(() => {
    if (!detail || !enabledProviders.length) return;
    let cancelled = false;
    const clickedOrder = selectedSeasons.filter((number) => number !== latestSeason);
    const allSeasonOrder = allSeasonsSelected ? seasons.map((value) => value.season_number).sort((a, b) => a - b) : [];
    const numbers = canTrack ? [...new Set([latestSeason, ...clickedOrder, ...allSeasonOrder])] : [0];
    const targets = numbers.flatMap((number) =>
      enabledProviders
        .filter((provider) => !seasonResources[resourceKey(provider, number)])
        .map((provider) => ({ number, provider })),
    );
    if (!targets.length) return;
    const currentDetail = detail;
    setResourceLoading(true);
    setResourceLoadingKeys(targets.map(({ number, provider }) => resourceKey(provider, number)));
    async function inspectTargets() {
      await Promise.all(targets.map(async ({ number, provider }) => {
        let result: ResourceStatus = { ok: false, found: false, message: "资源搜索失败", provider };
        try {
          result = await api.resources(currentDetail, canTrack ? number : undefined, false, provider);
        } catch {
          result = { ok: false, found: false, message: `${providerLabel(provider)}资源搜索失败`, provider };
        }
        if (!cancelled) {
          const key = resourceKey(provider, number);
          setSeasonResources((current) => ({ ...current, [key]: result }));
          setResourceLoadingKeys((current) => current.filter((value) => value !== key));
        }
      }));
    }
    void inspectTargets()
      .finally(() => {
        if (!cancelled) {
          setResourceLoadingKeys([]);
          setResourceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [detail, selectedSeasons.join(","), canTrack, allSeasonsSelected, latestSeason, enabledProviders.join(",")]);

  function toggleSeason(number: number) {
    setCompleted("");
    setSelectedSeasons((current) => {
      if (!current.includes(number)) return [...current, number];
      if (current.length === 1) return current;
      return current.filter((value) => value !== number);
    });
  }

  function selectAllSeasons() {
    setCompleted("");
    setSelectedSeasons((current) => [
      ...current,
      ...seasons.map((value) => value.season_number).sort((a, b) => a - b).filter((number) => !current.includes(number)),
    ]);
  }

  async function addSelectedTracking(category?: NonNullable<MediaItem["category"]>) {
    if (!canTrack) return;
    const actionMedia = { ...media, category: category || media.category || item.category || media.media_type };
    setBusy("cloud");
    setMessage("");
    try {
      const providers = enabledProviders.length ? enabledProviders : (["quark"] as CloudProvider[]);
      await Promise.allSettled(
        orderedSelection.flatMap((seasonNumber) =>
          providers.map((provider) => api.createTracking(actionMedia, seasonNumber, "cloud", provider)),
        ),
      );
      const latestText = orderedSelection.includes(latestSeason) && isOngoing ? "，最新季会按追更时间继续检查" : "";
      setMessage(`已将 ${orderedSelection.map((number) => `S${number}`).join("、")} 加入智能追更${latestText}。`);
      api.tracking().then(setTrackingTasks).catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加入智能追更失败");
    } finally {
      setBusy("");
    }
  }

  async function transfer(target: "cloud" | "local", category?: NonNullable<MediaItem["category"]>) {
    setBusy(target);
    setProgressStage("tmdb_resolving");
    setMessage("");
    const actionMedia = category ? { ...media, category } : media;
    try {
      if (target === "cloud") {
        const batchItems = resourceSelection.flatMap((seasonNumber) =>
            enabledProviders
            .filter((provider) => isResourceReady(seasonResources[resourceKey(provider, seasonNumber)]))
            .map((provider) => ({
              provider,
              season_number: canTrack ? seasonNumber : undefined,
              episode_numbers: selectedSeasonEpisodes[seasonNumber],
              preferred_share_url: seasonResources[resourceKey(provider, seasonNumber)]?.source_share_url
                || seasonResources[resourceKey(provider, seasonNumber)]?.share_url
                || "",
              preferred_share_only: Boolean(
                seasonResources[resourceKey(provider, seasonNumber)]?.source_share_url
                || seasonResources[resourceKey(provider, seasonNumber)]?.share_url
              ),
            })),
        ).filter((item) => item.episode_numbers === undefined || item.episode_numbers.length > 0);
        if (!batchItems.length) {
          setMessage("当前没有已验证可用的网盘资源。");
          return;
        }
        const started = await api.createTransferBatch(actionMedia, batchItems);
        const batch = await waitForTransferBatch(started.id, (current) => {
          const running = current.children.find((child) => child.status === "running");
          if (running) {
            setProgressStage(running.stage);
            setProgressSeason(running.season_number || 0);
            setProgressProvider(running.provider === "quark" || running.provider === "p115" ? running.provider : "qas");
          }
        });
        const successful = batch.children.filter((child) => child.status === "done" || child.status === "triggered").length;
        const failed = batch.children.length - successful;
        const trackedProviders = batch.children
          .filter((child) => (child.status === "done" || child.status === "triggered") && child.season_number === latestSeason && (child.provider === "qas" || child.provider === "quark" || child.provider === "p115"))
          .map((child) => child.provider as CloudProvider);
        if (isOngoing && trackedProviders.length) {
          await Promise.allSettled([...new Set(trackedProviders)].map((provider) => api.createTracking(actionMedia, latestSeason, "cloud", provider)));
          api.tracking().then(setTrackingTasks).catch(() => undefined);
        }
        if (successful) setCompleted("cloud");
        setMessage(
          failed
            ? `已完成 ${successful} 个网盘任务，${failed} 个失败或需要确认；成功网盘已继续转存。`
            : `已完成 ${successful} 个网盘任务${isOngoing && trackedProviders.length ? "，最新季已加入智能追更" : ""}。`,
        );
        return;
      }
      const results: TransferJob[] = [];
      for (const seasonNumber of orderedSelection) {
        setProgressSeason(seasonNumber);
        setProgressProvider(localProvider || "qas");
        const status = seasonResources[resourceKey(localProvider || "qas", seasonNumber)];
        const started = await api.createTransfer(
          actionMedia,
          target,
          canTrack ? seasonNumber : undefined,
          localProvider,
          status?.source_share_url || status?.share_url || "",
        );
        const result = await waitForTransfer(started.id, (job) => setProgressStage(job.stage));
        results.push(result);
        const transferOk = result.status === "done" || result.status === "triggered";
        if (transferOk && localProvider === "qas" && isOngoing && seasonNumber === latestSeason) {
          await api.createTracking(actionMedia, seasonNumber, target, localProvider);
        }
      }
      const successful = results.filter((result) => result.status === "done" || result.status === "triggered").length;
      const failed = results.length - successful;
      if (!failed) {
        setCompleted(target);
        setMessage(`已处理 ${successful} 季${isOngoing && orderedSelection.includes(latestSeason) ? "，最新季已加入智能追更" : ""}。`);
      } else {
        setMessage(`已处理 ${successful} 季，${failed} 季未完成，可调整选择后重试。`);
      }
    } catch {
      setMessage("创建任务失败");
    } finally {
      setBusy("");
      setProgressStage("");
      setProgressSeason(0);
      setProgressProvider("");
    }
  }

  function candidateOptions(provider: CloudProvider, statuses = seasonResources) {
    return resourceSelection.flatMap((seasonNumber) =>
      (statuses[resourceKey(provider, seasonNumber)]?.candidates || []).map((candidate) => ({ ...candidate, season_number: seasonNumber })),
    );
  }

  function providerShareCandidates(provider: CloudProvider, statuses = seasonResources) {
    return resourceSelection.flatMap((seasonNumber) => {
      const status = statuses[resourceKey(provider, seasonNumber)];
      if (!status || !status.found) return [];
      const confirmedShareUrl = status.ready && status.share_url ? status.share_url : "";
      const candidates = (status.candidates || [])
        .filter((candidate) => candidate.share_url && (!candidate.provider || candidate.provider === provider))
        .map((candidate) => ({
          url: candidate.share_url,
          score: candidate.share_url === confirmedShareUrl
            ? 1000
            : resourceConfidence(status, seasonNumber, Number(candidate.score || 0), false) || 0,
        }));
      const directUrl = status.share_url || status.source_share_url;
      if (directUrl && !candidates.some((candidate) => candidate.url === directUrl)) {
        candidates.push({
          url: directUrl,
          score: directUrl === confirmedShareUrl
            ? 1000
            : resourceConfidence(status, seasonNumber, 0, false) || 0,
        });
      }
      return candidates;
    }).sort((left, right) => right.score - left.score);
  }

  function providerConfidence(statuses: ResourceStatus[], shareCandidates: Array<{ url: string; score: number }>) {
    const highestScore = shareCandidates.reduce((highest, candidate) => Math.max(highest, candidate.score), 0);
    if (highestScore >= 1000) return 100;
    if (highestScore > 0) return Math.min(99, Math.max(1, Math.round(highestScore)));
    return statuses.some((status) => status.found) ? 50 : null;
  }

  async function openCandidateChoice(provider: CloudProvider) {
    let options = candidateOptions(provider);
    if (options.length) {
      setCandidateChoice({ provider, options });
      return;
    }
    const targets = resourceSelection.filter((number) => {
      const status = seasonResources[resourceKey(provider, number)];
      return Boolean(status?.candidate_count || status?.requires_review);
    });
    if (!targets.length || !detail) {
      setMessage("候选资源正在后台确认，请稍后刷新资源或到待确认页面处理。");
      return;
    }
    setCandidateLoadingProvider(provider);
    setMessage("正在读取候选资源详情…");
    const refreshed = await Promise.all(targets.map(async (seasonNumber) => {
      try {
        return [
          resourceKey(provider, seasonNumber),
          await api.resources(detail, canTrack ? seasonNumber : undefined, true, provider),
        ] as const;
      } catch {
        return [resourceKey(provider, seasonNumber), null] as const;
      }
    }));
    const nextStatuses = { ...seasonResources };
    for (const [key, status] of refreshed) if (status) nextStatuses[key] = status;
    setSeasonResources(nextStatuses);
    options = candidateOptions(provider, nextStatuses);
    setCandidateLoadingProvider("");
    if (options.length) {
      setMessage("");
      setCandidateChoice({ provider, options });
    } else {
      setMessage("候选资源详情暂未返回，请稍后重试或到待确认页面处理。");
    }
  }

  async function transferProvider(provider: CloudProvider, selected?: { season_number: number; share_url: string }) {
    setBusy("cloud");
    setProgressProvider(provider);
    setMessage("");
    try {
      const items = resourceSelection
        .filter((number) => selected?.season_number === number || isResourceReady(seasonResources[resourceKey(provider, number)]))
        .map((number) => ({
          provider,
          season_number: canTrack ? number : undefined,
          episode_numbers: selectedSeasonEpisodes[number],
          preferred_share_url: selected?.season_number === number ? selected.share_url : seasonResources[resourceKey(provider, number)]?.source_share_url || seasonResources[resourceKey(provider, number)]?.share_url || "",
          preferred_share_only: Boolean(
            selected?.season_number === number
              ? selected.share_url
              : seasonResources[resourceKey(provider, number)]?.source_share_url || seasonResources[resourceKey(provider, number)]?.share_url
          ),
        }))
        .filter((item) => item.episode_numbers === undefined || item.episode_numbers.length > 0);
      if (!items.length) return;
      const started = await api.createTransferBatch(media, items);
      const batch = await waitForTransferBatch(started.id, (current) => {
        const running = current.children.find((child) => child.status === "running");
        if (running) setProgressStage(running.stage);
      });
      const successful = batch.children.filter((child) => child.status === "done" || child.status === "triggered").length;
      const failed = batch.children.find((child) => child.status !== "done" && child.status !== "triggered");
      setMessage(
        successful
          ? `${providerLabel(provider)}已完成 ${successful} 个转存任务。`
          : `${providerLabel(provider)}转存失败：${failed?.message || "未返回具体原因，请在右上角任务中心查看详情"}`,
      );
    } finally {
      setBusy("");
      setProgressProvider("");
      setProgressStage("");
    }
  }

  async function copyProviderShare(provider: CloudProvider) {
    const url = providerShareCandidates(provider)[0]?.url;
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopiedProvider(provider);
    setMessage(`已复制${providerLabel(provider)}分享链接（包含提取码）。`);
    window.setTimeout(() => setCopiedProvider((current) => current === provider ? "" : current), 1800);
  }

  function openProviderShare(provider: CloudProvider) {
    const url = providerShareCandidates(provider)[0]?.url;
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  async function refreshSelectedResources() {
    if (!detail || !enabledProviders.length) return;
    const targets = resourceSelection.flatMap((number) =>
      enabledProviders.map((provider) => ({ number, provider })),
    );
    setResourceLoading(true);
    setResourceStage(0);
    setResourceLoadingKeys(targets.map(({ number, provider }) => resourceKey(provider, number)));
    setMessage("");
    await Promise.all(targets.map(async ({ number, provider }) => {
      const key = resourceKey(provider, number);
      let result: ResourceStatus = { ok: false, found: false, message: "资源刷新失败", provider };
      try {
        result = await api.resources(detail, canTrack ? number : undefined, true, provider);
      } catch (error) {
        result = { ok: false, found: false, message: error instanceof Error ? error.message : `${providerLabel(provider)}资源刷新失败`, provider };
      }
      setSeasonResources((current) => ({ ...current, [key]: result }));
      setResourceLoadingKeys((current) => current.filter((value) => value !== key));
    }));
    setResourceLoadingKeys([]);
    setResourceLoading(false);
    setMessage("已重新搜索当前选择的资源。");
  }

  function availableSeasonEpisodes(seasonNumber: number) {
    return [...new Set(
      enabledProviders.flatMap((provider) => seasonResources[resourceKey(provider, seasonNumber)]?.episode_numbers || []),
    )].sort((left, right) => left - right);
  }

  function toggleSeasonEpisode(seasonNumber: number, episodeNumber: number) {
    const available = availableSeasonEpisodes(seasonNumber);
    setSelectedSeasonEpisodes((current) => {
      const selected = current[seasonNumber] || available;
      return {
        ...current,
        [seasonNumber]: selected.includes(episodeNumber)
          ? selected.filter((number) => number !== episodeNumber)
          : [...selected, episodeNumber].sort((left, right) => left - right),
      };
    });
  }

  async function toggleOpenListAutoSync() {
    if (!config || !canToggleOpenListAutoSync) return;
    const nextEnabled = !config.openlist_auto_sync;
    setConfig({ ...config, openlist_auto_sync: nextEnabled });
    try {
      await api.saveConfig({ openlist_auto_sync: nextEnabled });
      setMessage("");
      window.dispatchEvent(new CustomEvent("mediaindex:providers-changed"));
    } catch (error) {
      setConfig({ ...config, openlist_auto_sync: !nextEnabled });
      setMessage(error instanceof Error ? error.message : "OpenList 自动同步设置保存失败");
    }
  }

  return (
    <>
    <MediaDetailScaffold media={media} onBack={onClose} strmStatus={config ? `自动 STRM：${[config.p115_strm_enabled && "115", config.quark_strm_enabled && "夸克"].filter(Boolean).join(" / ") || "未开启"}` : undefined}>
          <div className="modal-main media-detail-workflow-content">
            {canTrack && Boolean(media.seasons?.length) && (
              <div className="season-row season-selector">
                <button className={`season-select-all ${allSeasonsSelected ? "active" : ""}`} onClick={selectAllSeasons} aria-label="全选季度" title="全选季度">
                  <CheckSquare size={16} weight={allSeasonsSelected ? "fill" : "regular"} />
                  <span>全选</span>
                </button>
                {seasons.map((s) => {
                  const selected = selectedSeasons.includes(s.season_number);
                  const isTransferring = Boolean(busy) && progressSeason === s.season_number;
                  const statuses = enabledProviders.map((provider) => ({
                    provider,
                    status: seasonResources[resourceKey(provider, s.season_number)],
                    loading: resourceLoadingKeys.includes(resourceKey(provider, s.season_number)),
                  }));
                  const resourceState = statuses.map(({ provider, status, loading }) =>
                    `${providerShortLabel(provider)}${loading ? "…" : status?.found ? "✓" : status ? "×" : "·"}`,
                  ).join(" ");
                  const seasonFound = statuses.some(({ status }) => status?.found);
                  const isInspecting = statuses.some(({ loading }) => loading);
                  return (
                    <div className="season-choice" key={s.season_number}>
                      <button
                        className={`${selected ? "selected" : ""} ${seasonFound ? "verified" : ""}`}
                        onClick={() => toggleSeason(s.season_number)}
                        aria-pressed={selected}
                      >
                        {isTransferring || isInspecting ? <Spinner /> : selected && <Check size={13} weight="bold" />}
                        <span>S{s.season_number}</span>
                        <em>{resourceState}</em>
                      </button>
                      <button
                        type="button"
                        className={`season-expand ${expandedSeason === s.season_number ? "open" : ""}`}
                        title={`展开 S${s.season_number} 已检索剧集`}
                        aria-label={`展开 S${s.season_number} 已检索剧集`}
                        aria-expanded={expandedSeason === s.season_number}
                        disabled={!seasonFound}
                        onClick={() => setExpandedSeason((current) => current === s.season_number ? null : s.season_number)}
                      >
                        <CaretDown size={14} />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
            {canTrack && expandedSeason !== null && (
              <div className="season-episode-picker">
                <div>
                  <strong>S{expandedSeason} 已检索剧集</strong>
                  <span>勾选后仅转存所选集</span>
                </div>
                <div className="season-episode-picker-list">
                  {availableSeasonEpisodes(expandedSeason).map((episodeNumber) => {
                    const selected = (selectedSeasonEpisodes[expandedSeason] || availableSeasonEpisodes(expandedSeason)).includes(episodeNumber);
                    return <button type="button" key={episodeNumber} className={selected ? "selected" : ""} onClick={() => toggleSeasonEpisode(expandedSeason, episodeNumber)}>E{String(episodeNumber).padStart(2, "0")}</button>;
                  })}
                </div>
              </div>
            )}
            {isTracked && <div className="tracking-lock"><CheckCircle size={17} /> 选中的季度中有已加入智能追更的项目，仍可手动转存</div>}
            <div className="provider-progress-layout">
            <div className="provider-progress-grid" aria-label="网盘资源验证状态">
              {enabledProviders.map((provider) => {
                const statuses = resourceSelection.map((number) => seasonResources[resourceKey(provider, number)]).filter(Boolean);
                const found = statuses.filter((status) => status.found).length;
                const transferable = statuses.filter((status) => isResourceReady(status)).length;
                const reviewCount = statuses.filter((status) => status.requires_review).length;
                const candidateCount = statuses.reduce((count, status) => count + (status.candidate_count || 0), 0);
                const transferableFiles = statuses.reduce((count, status) => count + (isResourceReady(status) ? Math.max(1, status.file_count || 0) : 0), 0);
                const sourceLabels = Array.from(new Set(statuses.flatMap((status) => (status.candidates || []).map((candidate) => candidate.source?.startsWith("telegram:") ? "TG 频道" : candidate.source ? "PanSou" : "")).filter(Boolean)));
                const sourceHint = sourceLabels.length ? ` · 来源 ${sourceLabels.join(" + ")}` : "";
                const loading = resourceSelection.some((number) => resourceLoadingKeys.includes(resourceKey(provider, number)));
                const shareCandidates = providerShareCandidates(provider);
                const hasShareLink = shareCandidates.length > 0;
                const confidence = providerConfidence(statuses, shareCandidates);
                const autoStrm = provider === "p115" ? config?.p115_strm_enabled : config?.quark_strm_enabled;
                const cardState = reviewCount ? "review" : transferable ? "found" : candidateCount ? "candidate" : "";
                const statusLabel = loading
                  ? "检索中…"
                  : canTrack
                    ? transferable
                      ? `${transferable}/${resourceSelection.length} 季可转存`
                      : reviewCount
                        ? `${reviewCount} 季候选待确认`
                        : candidateCount
                          ? `${candidateCount} 个候选资源`
                          : "暂无可用资源"
                    : transferable
                      ? `${transferableFiles} 个资源可转存`
                      : reviewCount
                        ? `${reviewCount} 个候选待确认`
                        : candidateCount
                          ? `${candidateCount} 个候选资源`
                          : "暂无可用资源";
                const hint = loading
                  ? "正在验证资源"
                  : reviewCount
                    ? "点击进入确认"
                    : transferable
                      ? "点击转存至该网盘"
                      : candidateCount
                        ? "候选尚未完成验证"
                        : "等待可用资源";
                return (
                  <div className={`provider-progress-card ${cardState}`} key={provider}>
                    <button type="button" className="provider-progress-main" disabled={(!found && !candidateCount) || Boolean(busy) || candidateLoadingProvider === provider} onClick={() => void (reviewCount || candidateCount ? openCandidateChoice(provider) : transferProvider(provider))}>
                      {loading || candidateLoadingProvider === provider ? <Spinner /> : reviewCount || candidateCount ? <WarningCircle size={17} /> : transferable === resourceSelection.length ? <CheckCircle size={17} /> : <CloudArrowDown size={17} />}
                      <strong>{providerLabel(provider)}</strong>
                      <span>{statusLabel}</span>
                      <small>{hint}{sourceHint}{confidence !== null ? ` · 可信度 ${confidence}%` : ""}{config ? ` · STRM ${autoStrm ? "自动" : "手动"}` : ""}</small>
                    </button>
                    {hasShareLink && (
                      <div className="provider-card-actions">
                        <button type="button" className="provider-open-action" title={`打开最高可信度${providerLabel(provider)}链接`} aria-label={`打开最高可信度${providerLabel(provider)}链接`} onClick={() => openProviderShare(provider)}>
                          <ArrowSquareOut size={16} weight="bold" />
                        </button>
                        <button type="button" className={`provider-share-action ${copiedProvider === provider ? "copied" : ""}`} title={copiedProvider === provider ? "已复制" : "分享链接"} aria-label={copiedProvider === provider ? `已复制${providerLabel(provider)}分享链接` : `分享${providerLabel(provider)}链接`} onClick={() => void copyProviderShare(provider)}>
                          {copiedProvider === provider ? <Check size={16} weight="bold" /> : <ShareNetwork size={16} weight="bold" />}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {canToggleOpenListAutoSync && (
              <button
                type="button"
                className={`icon openlist-auto-toggle-icon ${config?.openlist_auto_sync ? "active" : ""}`}
                onClick={() => void toggleOpenListAutoSync()}
                disabled={Boolean(busy)}
                title={config?.openlist_auto_sync ? "OpenList 自动同步已开启，点击关闭" : "OpenList 自动同步未开启，点击开启"}
                aria-label={config?.openlist_auto_sync ? "关闭 OpenList 自动同步" : "开启 OpenList 自动同步"}
              >
                {config?.openlist_auto_sync ? <Checks size={17} /> : <ArrowClockwise size={17} />}
              </button>
            )}
            </div>
            <div className={`action-row ${canTrack ? "has-tracking" : "movie-action-row"}`}>
              {canTrack && (
                <button className="secondary action-button" onClick={() => setCategoryPrompt("tracking")} disabled={Boolean(busy)}>
                  <Eye size={18} />
                  <span>{isTracked ? "更新追更路径" : "加入智能追更"}</span>
                </button>
              )}
              <button className="primary action-button" onClick={() => canTrack ? setCategoryPrompt("cloud") : void transfer("cloud")} disabled={!canSaveCloud} title={saveDisabledReason}>
                {completed === "cloud" ? <CheckCircle size={18} /> : busy === "cloud" ? <Spinner /> : <CloudArrowDown size={18} />}
                <span>{completed === "cloud" ? "已完成" : busy === "cloud" ? `${progressProvider ? `${providerShortLabel(progressProvider)} ` : ""}${progressSeason ? `S${progressSeason} ` : ""}${transferStageLabel(progressStage)}` : "转存全部网盘"}</span>
              </button>
              {localProvider && (
                <button className="secondary action-button" onClick={() => transfer("local")} disabled={!canSaveLocal} title={saveDisabledReason}>
                  {completed === "local" ? <CheckCircle size={18} /> : busy === "local" ? <Spinner /> : <HardDrives size={18} />}
                  <span>{completed === "local" ? "已完成" : busy === "local" ? `${progressSeason ? `S${progressSeason} ` : ""}${transferStageLabel(progressStage)}` : "存本地"}</span>
                </button>
              )}
              <button
                className="secondary action-button refresh-action-button"
                onClick={() => void refreshSelectedResources()}
                disabled={resourceLoading || Boolean(busy)}
                title="重新搜索当前选择的资源"
              >
                {resourceLoading ? <Spinner /> : <ArrowClockwise size={18} />}
                <span>{resourceLoading ? resourceSearchLabel(resourceStage) : "刷新资源"}</span>
              </button>
              <form className="modal-manual-link" onSubmit={submitManualLink}>
                <input
                  aria-label="手动粘贴分享链接"
                  value={manualLink}
                  onChange={(event) => setManualLink(event.target.value)}
                  placeholder="如无法自动找到资源，可在此处粘贴链接"
                  inputMode="url"
                />
                <button className="modal-manual-link-submit" type="submit" disabled={manualLinkBusy || !manualLink.trim()} title="转存链接" aria-label="转存链接">
                  {manualLinkBusy ? <Spinner /> : <CloudArrowDown size={18} />}
                </button>
              </form>
              {manualLinkMessage && <div className="modal-manual-link-message">{manualLinkMessage}</div>}
            </div>
            {message && <div className="notice">{message}</div>}
            <MediaWorkflowPreview workflow={workflow} />
          </div>
    </MediaDetailScaffold>
    {categoryPrompt && (
      <TrackingCategoryDialog
        item={media}
        config={config}
        action={categoryPrompt === "cloud" ? "transfer" : "tracking"}
        onClose={() => setCategoryPrompt("")}
        onSelect={(category) => {
          const action = categoryPrompt;
          setCategoryPrompt("");
          if (action === "tracking") void addSelectedTracking(category);
          if (action === "cloud") void transfer("cloud", category);
        }}
      />
    )}
    {candidateChoice && (
      <ResourceCandidateDialog
        provider={candidateChoice.provider}
        options={candidateChoice.options}
        onClose={() => setCandidateChoice(null)}
        onSelect={(option) => {
          setCandidateChoice(null);
          void transferProvider(candidateChoice.provider, option);
        }}
      />
    )}
    </>
  );
}

function MediaWorkflowPreview({ workflow }: { workflow: MediaWorkflow | null }) {
  const fallback = ["网盘资源查询", "TMDB 核对和改名", "转存", "OpenList 同步", "STRM 生成", "通知 Emby 入库", "发送入库通知"];
  return <section className="media-workflow-preview" aria-label="自动入库整体进度">
    <header>
      <div><strong>自动入库进度</strong><span>{workflow?.job_id ? `任务 #${workflow.job_id}` : "等待开始"}</span></div>
      {workflow?.steps.some((step) => step.status === "running") && <em><Spinner />运行中</em>}
    </header>
    <div className="media-workflow-step-grid">
      {(workflow?.steps || []).map((step, index) => <article className={`workflow-step ${step.status}`} key={step.key} title={step.message}>
        <i>{step.status === "done" ? <Check size={13} weight="bold" /> : step.status === "failed" ? <XCircle size={14} /> : step.status === "review" ? <WarningCircle size={14} /> : step.status === "running" ? <Spinner /> : step.status === "skipped" ? <MinusCircle size={14} /> : index + 1}</i>
        <div><strong>{step.label}</strong><span>{step.message}</span></div>
      </article>)}
      {!workflow && fallback.map((label, index) => <article className="workflow-step pending" key={label}><i>{index + 1}</i><div><strong>{label}</strong><span>正在读取状态</span></div></article>)}
    </div>
  </section>;
}

function ResourceCandidateDialog({
  provider,
  options,
  onClose,
  onSelect,
}: {
  provider: CloudProvider;
  options: Array<ResourceCandidateOption & { season_number: number }>;
  onClose: () => void;
  onSelect: (option: { season_number: number; share_url: string }) => void;
}) {
  return (
    <div className="modal-backdrop candidate-backdrop" onClick={onClose}>
      <article className="candidate-choice-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">×</button>
        <div className="candidate-choice-heading">
          <div>
            <span className="eyebrow">候选资源确认</span>
            <h2>选择要转存的{providerLabel(provider)}资源</h2>
            <p>系统检测到多个候选或子目录。高置信度资源会直接进入转存，这里只展示需要你判断的候选。</p>
          </div>
          <WarningCircle size={30} />
        </div>
        <div className="candidate-choice-list">
          {options.map((option, index) => (
            <button type="button" className="candidate-choice-item" key={`${option.share_url}-${option.season_number}-${index}`} onClick={() => onSelect({ season_number: option.season_number, share_url: option.share_url })}>
              <span className="candidate-choice-topline">
                <strong>{option.title || `候选资源 ${index + 1}`}</strong>
                <span>{option.season_number > 0 ? `S${option.season_number}` : "电影"}{option.score ? ` · 评分 ${option.score}` : ""}</span>
              </span>
              <span className="candidate-choice-source">{[option.source?.startsWith("telegram:") ? option.source.replace("telegram:", "TG 频道 · ") : option.source, option.published_at].filter(Boolean).join(" · ") || "全局候选资源"}</span>
              {option.files?.length ? <span className="candidate-choice-files">{option.files.slice(0, 3).join("、")}{option.files.length > 3 ? ` 等 ${option.files.length} 个文件` : ""}</span> : <span className="candidate-choice-files">点击后由 MediaIndex 再次验证分享内容</span>}
            </button>
          ))}
        </div>
      </article>
    </div>
  );
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

function resourceSearchLabel(stage: number) {
  return ["正在通过 PanSou 搜索资源，请勿关闭卡片", "正在匹配 TMDB 媒体信息，请勿关闭卡片", "正在验证网盘分享，请勿关闭卡片", "正在生成重命名方案，请勿关闭卡片"][stage] || "正在搜索资源，请勿关闭卡片";
}

function WishlistPage({ enabledProviders }: { enabledProviders: CloudProvider[] }) {
  const [items, setItems] = useState<WishlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [scheduleOpen, setScheduleOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [actionLabel, setActionLabel] = useState("");

  async function load() {
    setLoading(true);
    try {
      setItems(await api.wishlist());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function remove(item: WishlistItem) {
    await Promise.all(item.provider_states.map((state) => api.deleteWishlist(state.id)));
    await load();
  }

  async function setCheckHour(item: WishlistItem, hour: number) {
    setBusy(item.id);
    try {
      await Promise.all(item.provider_states.map((state) => api.updateWishlistSchedule(state.id, hour)));
      setScheduleOpen(null);
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function runNow(item: WishlistItem) {
    setBusy(item.id);
    setActionLabel("正在通过 PanSou 检查资源…");
    const stageTimer = window.setTimeout(() => setActionLabel("正在验证并转存…"), 1200);
    try {
      await Promise.all(item.provider_states.filter((state) => enabledProviders.includes(state.provider)).map((state) => api.runWishlist(state.id)));
      await load();
    } finally {
      window.clearTimeout(stageTimer);
      setActionLabel("");
      setBusy(null);
    }
  }

  async function setWishlistProvider(item: WishlistItem, provider: CloudProvider) {
    setBusy(item.id);
    try {
      const existing = item.provider_states.find((state) => state.provider === provider);
      await api.updateWishlistProvider(item.id, provider, !existing);
      await load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <div className="page-head embedded-section-head">
        <div>
          <h2>愿望单</h2>
          <p>暂时没有资源的影片会先放在这里，后续按设置自动巡检。</p>
        </div>
        <button className="ghost" onClick={() => void load()}>
          <ArrowClockwise size={16} />
          刷新
        </button>
      </div>
      <div className="wishlist-layout">
        <div className="wishlist-items-column">
          {loading && <div className="list-skeleton" />}
          {!loading && items.length === 0 && <Empty title="愿望单是空的" body="在详情页遇到暂无资源时，可以先加入愿望单。" />}
          <div className="task-list">
        {items.map((item) => (
          <article className="task-row" key={item.id}>
            <Poster item={wishlistToMedia(item)} compact />
            <div className="task-main">
              <div className="task-title-line">
                <h3>{item.title}</h3>
                <span className="status">{wishlistStateLabel(item.status)}</span>
              </div>
              <p className="task-overview">{item.overview || "暂无简介。"}</p>
              <p>{[item.year, mediaTypeLabel(item.category || item.media_type), `加入时间 ${item.created_at?.slice(0, 10)}`].filter(Boolean).join(" / ")}</p>
              <p>
                {item.tmdb_date ? `TMDB 日期 ${item.tmdb_date}` : "等待 TMDB 更新日期"}
                {item.next_check_at ? ` / 下次检查 ${formatTrackingTime(item.next_check_at)}` : ""}
              </p>
              {item.last_error && <p className="danger">{item.last_error}</p>}
            </div>
            <div className="row-actions wishlist-control-panel">
              <div className="schedule-picker">
                <button
                  className="schedule-button"
                  title={item.next_check_at ? `下次检查 ${formatTrackingTime(item.next_check_at)}` : "设置每日检查时间"}
                  onClick={() => setScheduleOpen(scheduleOpen === item.id ? null : item.id)}
                  disabled={busy === item.id}
                >
                  {String(item.check_hour ?? 9).padStart(2, "0")}:00
                </button>
                {scheduleOpen === item.id && (
                  <div className="schedule-menu" role="menu" aria-label="选择检查时间">
                    {Array.from({ length: 24 }, (_, hour) => (
                      <button
                        type="button"
                        className={hour === (item.check_hour ?? 9) ? "active" : ""}
                        onClick={() => void setCheckHour(item, hour)}
                        key={hour}
                      >
                        {String(hour).padStart(2, "0")}:00
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="provider-choice row-provider-choice" aria-label="愿望单网盘">
                {enabledProviders.map((provider) => (
                  <button type="button" className={item.provider_states.some((state) => state.provider === provider) ? "active" : ""} onClick={() => void setWishlistProvider(item, provider)} disabled={busy === item.id} key={provider}>
                    {item.provider_states.some((state) => state.provider === provider) && <Check size={14} />}
                    {providerLabel(provider)}
                  </button>
                ))}
              </div>
              <button className="ghost immediate-run" title="立即执行" onClick={() => void runNow(item)} disabled={busy === item.id}>
                {busy === item.id ? <Spinner /> : <ArrowClockwise size={16} />}
                {busy === item.id ? actionLabel : "立即执行"}
              </button>
              <button className="icon danger-icon" title="删除" onClick={() => void remove(item)}>
                <Trash size={16} />
              </button>
            </div>
          </article>
        ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function WecomTransferRecords({ records }: { records: WecomTransferRecord[] }) {
  const [collapsed, setCollapsed] = useState(false);
  const [hiddenIds, setHiddenIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const visibleRecords = records.filter((record) => !hiddenIds.includes(record.id));

  async function deleteRecord(id: number) {
    setBusy(true);
    try {
      await api.deleteWecomTransferRecord(id);
      setHiddenIds((current) => [...current, id]);
    } finally {
      setBusy(false);
    }
  }

  async function clearRecords() {
    setBusy(true);
    try {
      await api.clearWecomTransferRecords();
      setHiddenIds((current) => [...new Set([...current, ...records.map((record) => record.id)])]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`wecom-record-panel settings-record-panel ${collapsed ? "is-collapsed" : ""}`} aria-labelledby="wecom-transfer-records-title">
      <div className="wecom-record-head">
        <div>
          <h2 id="wecom-transfer-records-title">交互转存记录</h2>
          <p>保留企业微信和 Telegram 的文字结果，方便回看每个网盘的处理状态。</p>
        </div>
        <div className="wecom-record-actions">
          <span>{visibleRecords.length}</span>
          <button type="button" className="ghost compact-action" onClick={() => setCollapsed((value) => !value)} aria-expanded={!collapsed}>
            {collapsed ? "展开" : "收缩"}
          </button>
          {visibleRecords.length > 0 && (
            <button type="button" className="ghost compact-action danger-action" onClick={() => void clearRecords()} disabled={busy}>
              删除记录
            </button>
          )}
        </div>
      </div>
      {!collapsed && visibleRecords.length === 0 ? (
        <p className="wecom-record-empty">暂无交互转存记录</p>
      ) : !collapsed ? (
        <div className="wecom-record-list">
          {visibleRecords.map((record) => {
            const channel = record.request_source === "telegram" ? "Telegram" : "企业微信";
            const provider = record.provider === "qas" ? "夸克" : record.provider === "p115" ? "115" : record.provider || "转存";
            const status = record.status === "done" ? "已完成" : record.status === "failed" ? "失败" : record.status === "needs_review" ? "待确认" : record.status === "triggered" ? "已提交" : "处理中";
            return (
              <article className="wecom-record-item" key={record.id}>
                <div className="wecom-record-title">
                  <strong>{record.display_title || "下载链接"}</strong>
                  <div className="wecom-record-item-actions">
                    <span className={`wecom-record-status ${record.status}`}>{status}</span>
                    <button type="button" className="icon danger-icon" title="删除记录" aria-label={`删除${record.display_title || "这条记录"}`} onClick={() => void deleteRecord(record.id)} disabled={busy}>
                      <Trash size={15} />
                    </button>
                  </div>
                </div>
                <p>{channel} · {provider}{record.request_user ? ` · ${record.request_user}` : ""} · {record.created_at?.slice(0, 16)}</p>
                {record.save_path && <p className="wecom-record-path">保存到：{record.save_path}</p>}
                {record.message && <p className="wecom-record-message">{record.message}</p>}
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function TrackingPage({ enabledProviders, onOpenConnections }: { enabledProviders: CloudProvider[]; onOpenConnections: () => void }) {
  const [items, setItems] = useState<TrackingTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [taskAction, setTaskAction] = useState("");
  const [actionNotice, setActionNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [scheduleDrafts, setScheduleDrafts] = useState<Record<number, string>>({});
  const [expandedTask, setExpandedTask] = useState<number | null>(null);
  const [episodeLoading, setEpisodeLoading] = useState<number | null>(null);
  const [taskEpisodes, setTaskEpisodes] = useState<Record<number, { episode_number: number; status: string; title: string; air_date: string; aired: boolean }[]>>({});
  const [selectedMissing, setSelectedMissing] = useState<Record<number, number[]>>({});
  const [shareLinkDrafts, setShareLinkDrafts] = useState<Record<number, string>>({});
  const [actionLabel, setActionLabel] = useState("");
  const [openListAutoSync, setOpenListAutoSync] = useState(false);
  const [trackingSchedulerEnabled, setTrackingSchedulerEnabled] = useState(true);
  const [schedulerSaving, setSchedulerSaving] = useState(false);
  const [autoSyncingProviders, setAutoSyncingProviders] = useState<Record<string, boolean>>({});
  const [trackingDirectoryPicker, setTrackingDirectoryPicker] = useState<{ state: TrackingProviderState; title: string } | null>(null);
  const [openListTasks, setOpenListTasks] = useState<OpenListCopyTask[]>([]);
  const enabledStates = (task: TrackingTask) => task.provider_states.filter((state) => enabledProviders.includes(state.provider));
  const autoSyncKey = (taskId: number, provider: CloudProvider) => `${taskId}:${provider}`;
  const taskRunActive = (task: TrackingTask) => enabledStates(task).some((state) => state.active_job?.status === "running" || state.active_job?.status === "triggered");

  async function load(silent = false) {
    if (!silent) setLoading(true);
    try {
      setItems(await api.tracking());
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    api.config().then((config) => {
      setOpenListAutoSync(config.openlist_enabled && config.openlist_auto_sync && config.has_openlist_token);
      setTrackingSchedulerEnabled(config.tracking_scheduler_enabled);
    }).catch(() => {
      setOpenListAutoSync(false);
      setTrackingSchedulerEnabled(false);
    });
    const timer = window.setInterval(() => void load(true), 10_000);
    let openListLoading = false;
    const refreshOpenList = async () => {
      if (openListLoading) return;
      openListLoading = true;
      try { setOpenListTasks((await api.openListTasks()).tasks); }
      catch { setOpenListTasks([]); }
      finally { openListLoading = false; }
    };
    refreshOpenList();
    const openListTimer = window.setInterval(refreshOpenList, 2_500);
    return () => { window.clearInterval(timer); window.clearInterval(openListTimer); };
  }, []);

  async function toggleTask(task: TrackingTask) {
    const states = enabledStates(task);
    const paused = states.every((state) => state.status === "paused");
    await Promise.all(states.map((state) => paused ? api.resumeTracking(state.id) : api.pauseTracking(state.id)));
    await load();
  }

  async function deleteTask(task: TrackingTask) {
    if (!window.confirm(`删除「${task.title}」的追更任务？`)) return;
    await Promise.all(task.provider_states.map((state) => api.deleteTracking(state.id)));
    await load();
  }

  async function runTask(task: TrackingTask) {
    setTaskAction(`run:${task.id}`);
    setActionLabel("正在检查网盘…");
    const stageTimer = window.setTimeout(() => setActionLabel("正在通过 PanSou 搜索资源…"), 1200);
    setActionNotice(null);
    const runningStates = enabledStates(task);
    const syncingKeys = openListAutoSync
      ? runningStates
          .map((state) => state.provider === "qas" ? "p115" : state.provider === "p115" ? "qas" : "")
          .filter((provider): provider is "qas" | "p115" => provider !== "" && enabledProviders.includes(provider))
          .map((provider) => autoSyncKey(task.id, provider))
      : [];
    if (syncingKeys.length) {
      setAutoSyncingProviders((current) => ({ ...current, ...Object.fromEntries(syncingKeys.map((key) => [key, true])) }));
    }
    try {
      const results = await Promise.all(runningStates.map((state) => api.runTracking(state.id)));
      const reused = results.every((result) => result.duplicate);
      setActionNotice({ kind: "success", message: reused ? "相同追更任务已在执行，已继续显示当前进度。" : "已开始追更，可在卡片和右上角执行任务查看实时阶段。" });
      await load();
      window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "手动追更执行失败" });
    } finally {
      window.clearTimeout(stageTimer);
      setActionLabel("");
      setTaskAction("");
      if (syncingKeys.length) {
        setAutoSyncingProviders((current) => {
          const next = { ...current };
          syncingKeys.forEach((key) => delete next[key]);
          return next;
        });
      }
    }
  }

  async function refreshTaskStorage(task: TrackingTask) {
    setTaskAction(`refresh:${task.id}`);
    setActionNotice(null);
    try {
      const results = await Promise.allSettled(enabledStates(task).map((state) => api.refreshTrackingStorage(state.id)));
      const failures = results.filter((result): result is PromiseRejectedResult => result.status === "rejected");
      if (failures.length) {
        const message = failures.map((failure) => failure.reason instanceof Error ? failure.reason.message : "网盘状态读取失败").join("；");
        setActionNotice({ kind: "error", message });
      }
      await load();
    } finally {
      setTaskAction("");
    }
  }

  async function syncTaskStorage(task: TrackingTask) {
    const firstState = enabledStates(task)[0];
    if (!firstState) return;
    const syncingKeys = enabledStates(task).map((state) => autoSyncKey(task.id, state.provider));
    setTaskAction(`sync:${task.id}`);
    setAutoSyncingProviders((current) => ({ ...current, ...Object.fromEntries(syncingKeys.map((key) => [key, true])) }));
    setActionNotice(null);
    try {
      const result = await api.syncTrackingStorage(firstState.id);
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.message });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "两边网盘同步失败" });
    } finally {
      setTaskAction("");
      setAutoSyncingProviders((current) => {
        const next = { ...current };
        syncingKeys.forEach((key) => delete next[key]);
        return next;
      });
    }
  }

  async function setTrackingProvider(task: TrackingTask, provider: CloudProvider) {
    setTaskAction(`provider:${task.id}`);
    try {
      const existing = task.provider_states.find((state) => state.provider === provider);
      await api.updateTrackingProvider(task.id, provider, !existing);
      await load();
    } finally {
      setTaskAction("");
    }
  }

  async function toggleEpisodePanel(state: TrackingProviderState) {
    const next = expandedTask === state.id ? null : state.id;
    setExpandedTask(next);
    if (next !== null) {
      setEpisodeLoading(state.id);
      try {
        try {
          await api.refreshTrackingStorage(state.id);
        } catch (error) {
          setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "网盘状态读取失败" });
        }
        const result = await api.trackingEpisodes(state.id);
        setTaskEpisodes((current) => ({ ...current, [state.id]: result.episodes }));
      } catch (error) {
        setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "TMDB 分集读取失败" });
      } finally {
        await load(true).catch(() => undefined);
        setEpisodeLoading((current) => current === state.id ? null : current);
      }
    }
  }

  async function fillEpisodes(state: TrackingProviderState) {
    const episodes = selectedMissing[state.id] || [];
    if (!episodes.length) return;
    setTaskAction(`fill:${state.id}`);
    setActionLabel("正在核对缺集…");
    const stageTimer = window.setTimeout(() => setActionLabel("正在通过 PanSou 查找并转存…"), 1200);
    setActionNotice(null);
    try {
      const result = await api.fillTrackingEpisodes(state.id, episodes);
      setSelectedMissing((current) => ({ ...current, [state.id]: [] }));
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.ok ? (result.duplicate ? "相同补齐任务已在执行，已继续显示当前进度。" : "已开始补齐，可在卡片和右上角执行任务查看实时阶段。") : result.message || "补集未完成，请稍后重试" });
      await load();
      window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "补齐所选失败" });
    } finally {
      window.clearTimeout(stageTimer);
      setActionLabel("");
      setTaskAction("");
    }
  }

  async function fillAllEpisodes(state: TrackingProviderState) {
    const episodes = (taskEpisodes[state.id] || [])
      .filter((episode) => episode.status !== "saved" && episode.aired)
      .map((episode) => episode.episode_number);
    if (!episodes.length) return;
    setTaskAction(`fill:${state.id}`);
    setActionLabel("正在核对全部缺集…");
    const stageTimer = window.setTimeout(() => setActionLabel("正在通过 PanSou 查找并转存缺集…"), 1200);
    setActionNotice(null);
    try {
      const result = await api.fillTrackingEpisodes(state.id, episodes);
      setSelectedMissing((current) => ({ ...current, [state.id]: [] }));
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.ok ? (result.duplicate ? "相同补齐任务已在执行，已继续显示当前进度。" : "已开始补齐，可在卡片和右上角执行任务查看实时阶段。") : result.message || "补集未完成，请稍后重试" });
      await load();
      window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "补齐全部失败" });
    } finally {
      window.clearTimeout(stageTimer);
      setActionLabel("");
      setTaskAction("");
    }
  }

  async function syncSelectedEpisodes(state: TrackingProviderState) {
    const episodes = selectedMissing[state.id] || [];
    if (!episodes.length) return;
    setTaskAction(`sync-selected:${state.id}`);
    setActionNotice(null);
    try {
      const result = await api.syncSelectedTrackingEpisodes(state.id, episodes);
      setSelectedMissing((current) => ({ ...current, [state.id]: [] }));
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.message });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "同步所选失败" });
    } finally {
      setTaskAction("");
    }
  }

  async function setTrackingScheduler(enabled: boolean) {
    setSchedulerSaving(true);
    setActionNotice(null);
    try {
      await api.saveConfig({ tracking_scheduler_enabled: enabled });
      setTrackingSchedulerEnabled(enabled);
      setActionNotice({ kind: "success", message: enabled ? "智能追更自动巡检已开启" : "智能追更自动巡检已关闭，仍可手动执行" });
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "巡检开关保存失败" });
    } finally {
      setSchedulerSaving(false);
    }
  }

  async function updateTrackingSavePath(state: TrackingProviderState, path: string) {
    setTaskAction(`path:${state.id}`);
    setActionNotice(null);
    try {
      const result = await api.updateTrackingSavePath(state.id, normalizeOpenListPath(path));
      setActionNotice({ kind: result.storage_refreshed ? "success" : "error", message: result.storage_refreshed ? "保存路径已更新，并已刷新已存集数" : result.message });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "追更保存路径更新失败" });
    } finally {
      setTaskAction("");
    }
  }

  async function fillEpisodesFromShare(state: TrackingProviderState) {
    const episodes = selectedMissing[state.id] || [];
    const shareUrl = (shareLinkDrafts[state.id] || "").trim();
    if (!episodes.length || !shareUrl) return;
    setTaskAction(`share:${state.id}`);
    setActionLabel("正在读取分享链接并核对所选集…");
    setActionNotice(null);
    try {
      const result = await api.fillTrackingEpisodesFromShare(state.id, episodes, shareUrl);
      setSelectedMissing((current) => ({ ...current, [state.id]: [] }));
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.ok ? (result.duplicate ? "相同链接补齐任务已在执行，已继续显示当前进度。" : "已开始验证分享链接并补齐所选集。") : result.message || "分享链接补齐失败" });
      await load();
      window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "分享链接补齐失败" });
    } finally {
      setActionLabel("");
      setTaskAction("");
    }
  }

  async function syncAllEpisodes(state: TrackingProviderState) {
    if (!state) return;
    setTaskAction(`sync-all:${state.id}`);
    setActionNotice(null);
    try {
      const result = await api.syncTrackingStorage(state.id);
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.message || (result.ok ? "已同步所有已存集" : "同步所有失败") });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "同步所有失败" });
    } finally {
      setTaskAction("");
    }
  }

  async function updateSchedule(task: TrackingTask, checkTime: string) {
    if (!checkTime || checkTime === task.check_time) return;
    setTaskAction(`schedule:${task.id}`);
    setActionNotice(null);
    try {
      await Promise.all(enabledStates(task).map((state) => api.updateTrackingSchedule(state.id, checkTime)));
      setScheduleDrafts((current) => {
        const next = { ...current };
        delete next[task.id];
        return next;
      });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "追更时间保存失败" });
    } finally {
      setTaskAction("");
    }
  }

  return (
    <section>
      <div className="page-head embedded-section-head">
        <div>
          <h2>智能追更</h2>
          <p>系统会在设定时间核对 TMDB 已播集数与网盘存量，仅在发现缺集时搜索资源。</p>
        </div>
        <div className="tracking-page-actions">
          <label className="tracking-scheduler-switch">
            <span>自动巡检</span>
            <button type="button" role="switch" aria-checked={trackingSchedulerEnabled} className={trackingSchedulerEnabled ? "active" : ""} disabled={schedulerSaving} onClick={() => void setTrackingScheduler(!trackingSchedulerEnabled)}>
              {schedulerSaving ? <Spinner /> : trackingSchedulerEnabled ? "开启" : "关闭"}
            </button>
          </label>
          <button className="ghost" onClick={() => void load()}>
            <ArrowClockwise size={16} />
            刷新
          </button>
        </div>
      </div>
      {actionNotice && <div className={`tracking-action-notice ${actionNotice.kind}`}>{actionNotice.message}</div>}
      {loading && <div className="list-skeleton" />}
      {!loading && items.length === 0 && <Empty title="还没有追更任务" body="连载剧集点存网盘或存本地后，会自动出现在这里。" />}
      <div className="task-list">
        {items.map((task) => (
          <article className="task-row" key={task.id}>
            <Poster item={taskToMedia(task)} compact />
            <div className="task-main">
              <div className="task-title-line">
                <h3>{task.title}</h3>
                <span className={`status ${enabledStates(task).every((state) => state.status === "paused") ? "paused" : "active"}`}>{enabledStates(task).every((state) => state.status === "paused") ? "已暂停" : taskRunActive(task) ? "执行中" : "运行中"}</span>
              </div>
              <p className="task-overview">{task.overview || "暂无简介。"}</p>
              <p>{[task.year, mediaTypeLabel(task.category || task.media_type)].filter(Boolean).join(" / ")}</p>
              <p className="tracking-progress-summary">
                <strong>进度：S{task.season_number} 共 {Math.max(...enabledStates(task).map((state) => state.episode_count), 0)} 集</strong>
                <span>
                  {enabledStates(task).map((state) => `${providerLabel(state.provider)}${state.storage_check_message?.startsWith("读取") ? `历史已存 ${state.saved_count} 集（未验证）` : `已确认 ${state.saved_count} 集`}`).join(" / ")}
                </span>
              </p>
              {matchOpenListTasks(openListTasks, task.title).length > 0 && <div className="tracking-openlist-progress"><span>OpenList 复制</span><OpenListTaskMonitor compact tasks={matchOpenListTasks(openListTasks, task.title).slice(0, 3)} /></div>}
              <p>
                {task.next_check_at ? `下次巡检：${formatTrackingTime(task.next_check_at)}` : trackingStateLabel(task.decision_state)}
              </p>
              {task.last_error && task.last_error !== task.storage_check_message && (
                <p className="danger">{task.last_error}</p>
              )}
            </div>
            <div className="row-actions tracking-control-panel">
              <div className="tracking-time-field" title="按本地时区设置该剧发布日的追更时间">
                <span>追更时间</span>
                <div className="tracking-time-action">
                  <input
                    type="time"
                    value={scheduleDrafts[task.id] ?? task.check_time ?? "10:00"}
                    aria-label={`${task.title}追更时间`}
                    onChange={(event) => setScheduleDrafts((current) => ({ ...current, [task.id]: event.target.value }))}
                    disabled={Boolean(taskAction)}
                  />
                  <button
                    type="button"
                    className="ghost tracking-time-save"
                    aria-label="保存追更时间"
                    title="保存追更时间"
                    onClick={() => void updateSchedule(task, scheduleDrafts[task.id] ?? task.check_time)}
                    disabled={
                      Boolean(taskAction)
                      || !scheduleDrafts[task.id]
                      || scheduleDrafts[task.id] === task.check_time
                    }
                  >
                    {taskAction === `schedule:${task.id}` ? <Spinner /> : <Check size={16} />}
                    <span>保存</span>
                  </button>
                </div>
              </div>
              <button className="tracking-control-button" title="刷新各网盘已存状态" aria-label="刷新各网盘已存状态" onClick={() => void refreshTaskStorage(task)} disabled={Boolean(taskAction)}>
                {taskAction === `refresh:${task.id}` ? <Spinner /> : <ArrowClockwise size={16} />}
                <span>刷新</span>
              </button>
              <button className="tracking-control-button" title="同步两边网盘缺失集" aria-label="同步两边网盘缺失集" onClick={() => void syncTaskStorage(task)} disabled={enabledStates(task).length < 2 || Boolean(taskAction)}>
                {taskAction === `sync:${task.id}` ? <Spinner /> : <ArrowClockwise size={16} />}
                <span>{taskAction === `sync:${task.id}` ? "同步中" : "同步"}</span>
              </button>
              <button className="tracking-control-button" title="立即执行一次追更" aria-label="立即执行一次追更" onClick={() => void runTask(task)} disabled={!enabledStates(task).length || enabledStates(task).every((state) => state.status === "paused") || Boolean(taskAction) || taskRunActive(task)}>
                {taskAction === `run:${task.id}` ? <Spinner /> : <Play size={16} />}
                <span>{taskAction === `run:${task.id}` ? "执行中" : "执行"}</span>
              </button>
              <button className="tracking-control-button" title={task.provider_states.every((state) => state.status === "paused") ? "恢复追更" : "暂停追更"} aria-label={task.provider_states.every((state) => state.status === "paused") ? "恢复追更" : "暂停追更"} onClick={() => void toggleTask(task)}>
                {task.provider_states.every((state) => state.status === "paused") ? <Play size={16} /> : <Pause size={16} />}
                <span>{task.provider_states.every((state) => state.status === "paused") ? "恢复" : "暂停"}</span>
              </button>
              <button className="tracking-control-button danger-control" title="删除追更" aria-label="删除追更" onClick={() => void deleteTask(task)}>
                <Trash size={16} />
                <span>删除</span>
              </button>
              <div className="tracking-provider-storage-list" aria-label="追更网盘">
              {enabledProviders.map((provider) => {
                const state = task.provider_states.find((entry) => entry.provider === provider);
                const autoSyncing = Boolean(autoSyncingProviders[autoSyncKey(task.id, provider)] || state?.storage_syncing);
                const storageCheckFailed = Boolean(state?.storage_check_message?.startsWith("读取"));
                return (
                <div className="tracking-provider-storage-row" key={provider}>
                  <div className="tracking-provider-identity">
                    <button
                      type="button"
                      className={`tracking-provider-toggle ${state ? "active" : ""} ${autoSyncing ? "syncing" : ""}`}
                      onClick={() => void setTrackingProvider(task, provider)}
                      disabled={Boolean(taskAction)}
                    >
                      {autoSyncing ? <Spinner /> : state ? <Check size={14} /> : null}
                      {providerLabel(provider)}{autoSyncing ? "同步中" : state ? "追更中" : "未启用"}
                    </button>
                    {state && <div className="tracking-provider-path" title={state.save_path}>
                      <span>{state.save_path}</span>
                      {state.provider !== "quark" && <button type="button" className="icon tracking-path-picker" title={`选择${providerLabel(provider)}追更保存路径`} aria-label={`选择${providerLabel(provider)}追更保存路径`} disabled={Boolean(taskAction)} onClick={() => setTrackingDirectoryPicker({ state, title: `${providerLabel(provider)}追更保存路径` })}>
                        {taskAction === `path:${state.id}` ? <Spinner /> : <FolderOpen size={16} />}
                      </button>}
                    </div>}
                    <TrackingRunStatus run={state?.active_job} />
                  </div>
                  {state ? <>
                  <div className={`tracking-storage-dropdown ${expandedTask === state.id ? "open" : ""}`}>
                    <button type="button" className="season-storage-toggle" onClick={() => void toggleEpisodePanel(state)} aria-expanded={expandedTask === state.id}>
                      <span>
                        {autoSyncing
                          ? `${providerLabel(state.provider)} · 同步中`
                          : storageCheckFailed
                            ? `${providerLabel(state.provider)} · S${task.season_number} 历史已存 ${state.saved_count} 集（未验证）`
                            : `${providerLabel(state.provider)} · S${task.season_number} 已存 ${state.saved_count} 集`}
                        {!autoSyncing && !storageCheckFailed && Boolean(state.last_saved_episode) && ` · 至 E${state.last_saved_episode}`}
                      </span>
                      {autoSyncing ? <Spinner /> : <CaretDown size={14} />}
                    </button>
                  </div>
                  {expandedTask === state.id && (
                  <div className="missing-episode-panel tracking-provider-menu">
                    {state.storage_check_message && <div className={`tracking-storage-diagnostic ${storageCheckFailed ? "error" : "success"}`}>
                      <WarningCircle size={17} weight={storageCheckFailed ? "fill" : "regular"} />
                      <span>{state.storage_check_message}</span>
                      {storageCheckFailed && state.provider === "p115" && <button type="button" className="ghost compact-action" onClick={onOpenConnections}>前往 115 连接</button>}
                    </div>}
                    <p className="manual-fill-hint">
                      <WarningCircle size={16} weight="fill" />
                      由于 PanSou 以近期资源为主，发布时间较早的资源可能无法找到。
                    </p>
                    {episodeLoading === state.id && !(taskEpisodes[state.id] || []).length && (
                      <div className="missing-episode-loading"><Spinner />正在刷新 TMDB 分集</div>
                    )}
                    <div className="missing-episode-list">
                      {(taskEpisodes[state.id] || []).map((episode) => {
                        const future = !episode.aired;
                        const missing = episode.status !== "saved" && !future;
                        const selected = (selectedMissing[state.id] || []).includes(episode.episode_number);
                        return (
                          <button
                            type="button"
                            disabled={!missing}
                            className={future ? "future" : selected ? "selected" : episode.status === "saved" ? "saved" : ""}
                            onClick={() => setSelectedMissing((current) => ({
                              ...current,
                              [state.id]: selected
                                ? (current[state.id] || []).filter((number) => number !== episode.episode_number)
                                : [...(current[state.id] || []), episode.episode_number],
                            }))}
                            key={episode.episode_number}
                          >
                            E{String(episode.episode_number).padStart(2, "0")}
                          </button>
                        );
                      })}
                    </div>
                    <div className="tracking-share-fill">
                      <input
                        aria-label={`${providerLabel(state.provider)}手动分享链接`}
                        value={shareLinkDrafts[state.id] || ""}
                        placeholder="粘贴夸克或 115 分享链接"
                        onChange={(event) => setShareLinkDrafts((current) => ({ ...current, [state.id]: event.target.value }))}
                        disabled={Boolean(taskAction)}
                      />
                      <button type="button" className="secondary compact-action" disabled={!(selectedMissing[state.id] || []).length || !(shareLinkDrafts[state.id] || "").trim() || Boolean(taskAction) || Boolean(state.active_job)} onClick={() => void fillEpisodesFromShare(state)}>
                        {taskAction === `share:${state.id}` ? <Spinner /> : <CloudArrowDown size={15} />} {taskAction === `share:${state.id}` ? "处理中" : "链接补齐所选"}
                      </button>
                    </div>
                    <div className="missing-episode-actions">
                      <button type="button" className="ghost compact-action" title="同步所选集到当前网盘" disabled={!(selectedMissing[state.id] || []).length || Boolean(taskAction)} onClick={() => void syncSelectedEpisodes(state)}>
                        {taskAction === `sync-selected:${state.id}` ? <Spinner /> : <ArrowClockwise size={15} />} {taskAction === `sync-selected:${state.id}` ? "同步中" : "同步所选"}
                      </button>
                      <button type="button" className="ghost compact-action" title="同步全部缺失集到当前网盘" disabled={enabledStates(task).length < 2 || Boolean(taskAction)} onClick={() => void syncAllEpisodes(state)}>
                        {taskAction === `sync-all:${state.id}` ? <Spinner /> : <ArrowClockwise size={15} />} {taskAction === `sync-all:${state.id}` ? "同步中" : "同步所有"}
                      </button>
                      <button type="button" className="primary compact-action" disabled={!(selectedMissing[state.id] || []).length || Boolean(taskAction) || Boolean(state.active_job)} onClick={() => void fillEpisodes(state)}>
                        {taskAction === `fill:${state.id}` ? <Spinner /> : <Play size={15} />} {taskAction === `fill:${state.id}` ? "处理中" : "补齐所选"}
                      </button>
                      <button type="button" className="ghost compact-action" disabled={!(taskEpisodes[state.id] || []).some((episode) => episode.status !== "saved" && episode.aired) || Boolean(taskAction) || Boolean(state.active_job)} onClick={() => void fillAllEpisodes(state)}>
                        {taskAction === `fill:${state.id}` ? "处理中" : "补齐所有"}
                      </button>
                    </div>
                  </div>
                )}
                  </> : <div className="tracking-provider-empty">未启用，点击左侧按钮开启</div>}
                </div>
                );
              })}
              </div>
            </div>
          </article>
        ))}
      </div>
      {trackingDirectoryPicker && trackingDirectoryPicker.state.provider !== "quark" && (
        <ProviderDirectoryPicker
          provider={trackingDirectoryPicker.state.provider}
          label={trackingDirectoryPicker.title}
          startPath={trackingDirectoryPicker.state.save_path}
          onClose={() => setTrackingDirectoryPicker(null)}
          onSelect={(path) => {
            const selected = trackingDirectoryPicker.state;
            setTrackingDirectoryPicker(null);
            void updateTrackingSavePath(selected, path);
          }}
        />
      )}
    </section>
  );
}

async function waitForTransfer(id: number, onProgress: (job: TransferJob) => void): Promise<TransferJob> {
  const terminal = new Set(["done", "triggered", "needs_review", "failed"]);
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const job = await api.transfer(id);
    onProgress(job);
    if (terminal.has(job.status)) return job;
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
  throw new Error("transfer_timeout");
}

async function waitForTransferBatch(id: number, onProgress: (batch: TransferBatch) => void): Promise<TransferBatch> {
  const terminal = new Set(["done", "partial", "needs_review", "failed"]);
  for (let attempt = 0; attempt < 360; attempt += 1) {
    const batch = await api.transferBatch(id);
    onProgress(batch);
    if (terminal.has(batch.status)) return batch;
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
  throw new Error("transfer_batch_timeout");
}

function resourceKey(provider: CloudProvider, seasonNumber: number) {
  return `${provider}:${seasonNumber}`;
}

function canSmartTrackMedia(item: Pick<MediaItem, "media_type" | "category">, fallbackType = "") {
  const type = item.category || (fallbackType === "movie" ? "" : fallbackType) || item.media_type;
  return type === "tv" || type === "variety" || type === "anime" || type === "documentary";
}

function providerLabel(provider: CloudProvider) {
  return provider === "p115" ? "115" : "夸克";
}

function providerShortLabel(provider: CloudProvider) {
  return provider === "p115" ? "115" : provider === "quark" ? "夸克原生" : "夸克";
}

function transferStageLabel(stage: string) {
  const labels: Record<string, string> = {
    tmdb_resolving: "正在匹配 TMDB",
    checking_saved: "正在检查目标目录",
    validating_link: "正在检查旧链接",
    searching_sources: "正在检索 PanSou 与 TG 频道资源",
    matching_files: "正在匹配文件",
    preparing_names: "正在生成文件名",
    qas_transferring: "正在执行转存",
    provider_submitting: "正在执行转存",
    provider_submitted: "已提交给网盘",
    provider_triggered: "等待网盘确认",
    provider_completed: "已确认完成",
    openlist_sync: "正在同步 OpenList",
    openlist_sync_done: "OpenList 同步完成",
    openlist_sync_failed: "OpenList 同步失败",
    stopped: "任务已终止",
  };
  return labels[stage] || "正在处理";
}

function formatTrackingTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function wishlistStateLabel(state: string) {
  const labels: Record<string, string> = {
    pending: "等待 TMDB 日期",
    checking: "正在检查",
    retry_wait: "等待下次检查",
    needs_review: "已通知确认",
    triggered: "夸克任务已触发",
    completed: "已完成",
  };
  return labels[state] || state;
}

function trackingStateLabel(state?: string) {
  const labels: Record<string, string> = {
    idle: "TMDB 暂无下一集播出日期",
    pending: "等待首次巡检",
    retry_wait: "等待下次换源重试",
    needs_review: "需要人工确认",
    awaiting_confirmation: "夸克任务已触发，等待结果确认",
    paused: "任务已暂停",
  };
  return labels[state || ""] || "暂无下一次巡检时间";
}

function ReviewPage({ enabledProviders }: { enabledProviders: CloudProvider[] }) {
  const [items, setItems] = useState<ReviewCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<"confirm" | "research" | "delete" | null>(null);
  const [progressStage, setProgressStage] = useState("");
  const [message, setMessage] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<Record<number, string[]>>({});
  const [cloudFilter, setCloudFilter] = useState<"all" | "quark" | "115">("all");
  const enabledCloudTypes: ("quark" | "115")[] = Array.from(new Set(enabledProviders.map((provider) => provider === "p115" ? "115" : "quark")));
  const providerItems = items.filter((item) => item.cloud_type === "quark"
    ? enabledCloudTypes.includes("quark")
    : item.cloud_type === "115" && enabledCloudTypes.includes("115"));
  const visibleItems = cloudFilter === "all" ? providerItems : providerItems.filter((item) => item.cloud_type === cloudFilter);

  async function load() {
    setLoading(true);
    try {
      setItems(await api.review());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function confirm(item: ReviewCandidate) {
    setBusy(item.id);
    setBusyAction("confirm");
    setProgressStage(item.provider === "moviepilot_115" ? "provider_submitting" : "matching_files");
    setMessage("");
    try {
      const result = await api.confirmReview(item.id, selectedFiles[item.id] || []);
      const job = await waitForTransfer(result.id, (current) => setProgressStage(current.stage));
      setMessage(
        ["done", "triggered"].includes(job.status)
          ? item.provider === "moviepilot_115"
            ? "已提交给 MoviePilot；后续转存、整理和 STRM 由 MoviePilot 处理。"
            : "所选资源已完成匹配、改名并提交转存。"
          : job.message || "所选文件仍无法安全匹配，请更换文件或重新搜索。",
      );
      await load();
    } catch {
      setMessage("提交失败，请稍后重试。");
    } finally {
      setBusy(null);
      setBusyAction(null);
      setProgressStage("");
    }
  }

  async function research(item: ReviewCandidate) {
    setBusy(item.id);
    setBusyAction("research");
    setMessage("");
    try {
      const result = await api.researchReview(item.job_id);
      setMessage(result.ok ? "已找到可执行资源。" : result.message || "已重新搜索，暂时仍没有安全候选。" );
      await load();
    } catch {
      setMessage("重新搜索失败，请稍后重试。");
    } finally {
      setBusy(null);
      setBusyAction(null);
    }
  }

  async function dismiss(item: ReviewCandidate) {
    setBusy(item.id);
    setBusyAction("delete");
    setMessage("");
    try {
      await api.deleteReview(item.id);
      setItems(await api.review());
      setSelectedFiles((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
    } catch {
      setMessage("删除失败，请稍后重试。");
    } finally {
      setBusy(null);
      setBusyAction(null);
    }
  }

  if (loading) return <div className="list-skeleton" />;
  if (!items.length) return (
    <section>
      {message && <div className="notice">{message}</div>}
      <Empty title="暂无待确认" body="系统会自动处理绝大多数任务；只有无法安全判断时才在这里提醒你。" />
    </section>
  );
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>待确认</h1>
          <p>候选会绑定创建任务时选定的执行端：夸克与 115 均使用 MediaIndex 原生链路；确认不会改变原任务的网盘归属。</p>
        </div>
      </div>
      <div className="segmented review-provider-filter" role="group" aria-label="候选网盘筛选">
        {([ ["all", "全部"], ["quark", "夸克"], ["115", "115"] ] as const)
          .filter(([key]) => key === "all" || enabledCloudTypes.includes(key))
          .map(([key, label]) => (
          <button key={key} className={cloudFilter === key ? "active" : ""} onClick={() => setCloudFilter(key)}>
            {label}
          </button>
        ))}
      </div>
      {message && <div className="notice">{message}</div>}
      <div className="review-list">
        {visibleItems.length === 0 && <Empty title="当前筛选下没有候选" body="可以切换到其他网盘类型查看。" />}
        {visibleItems.map((item) => (
          <article className="review-card" key={item.id}>
            <header className="review-card-head">
              <div>
                <span className={`review-kicker provider-badge ${item.cloud_type || "unknown"}`}>
                  {item.cloud_type === "115" ? "115 候选" : "夸克候选"}
                </span>
                <h2>{item.source_title || "未命名候选"}</h2>
                <p>{[item.search_query, item.source, item.season_number ? `S${item.season_number}` : ""].filter(Boolean).join(" / ")}</p>
              </div>
              <span className="review-score">匹配分 {Math.round(item.score)}</span>
            </header>

            <div className="review-link-row">
              <div>
                <strong>{item.cloud_type === "115" ? "115 分享" : "夸克分享"}</strong>
                <span>{item.share_url}</span>
              </div>
              <a className="secondary review-open-link" href={item.share_url} target="_blank" rel="noreferrer">
                <ArrowSquareOut size={17} />
                打开查看
              </a>
            </div>

            <div className="review-evidence">
              {(item.reasons.length ? item.reasons : [item.job_message || "文件名与 TMDB 信息无法形成唯一匹配"]).map((reason) => (
                <span key={reason}>{reviewReasonLabel(reason)}</span>
              ))}
            </div>

            {item.files?.length > 0 && (
              <fieldset className="review-files">
                <legend>选择要转存的文件</legend>
                <p>不选择时由后台继续自动判断；选择后只在这些文件中匹配和改名。</p>
                <div className="review-file-list">
                  {item.files.map((file) => {
                    const selected = selectedFiles[item.id]?.includes(file) ?? false;
                    return (
                      <label className={selected ? "selected" : ""} key={file}>
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() =>
                            setSelectedFiles((current) => {
                              const values = current[item.id] || [];
                              return {
                                ...current,
                                [item.id]: values.includes(file) ? values.filter((value) => value !== file) : [...values, file],
                              };
                            })
                          }
                        />
                        <span title={file}>{file}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            )}

            {item.review_state === "notification_failed" && <p className="danger">待确认通知未发送成功，请检查外部通知配置。</p>}
            {item.provider === "p115" && item.job_provider === "p115" && <p className="muted">确认后由 MediaIndex 原生读取 115 分享并完成筛选、改名、转存和目标目录核对。</p>}
            {item.provider === "quark" && item.job_provider === "quark" && <p className="muted">确认后由 MediaIndex 原生读取夸克分享并完成筛选、暂存、改名、转存和目标目录核对。</p>}
            {item.provider === "moviepilot_115" && item.job_provider === "moviepilot_115" && <p className="muted">确认后会把此分享链接提交给 MoviePilot；MediaIndex 不会直接操作 115。</p>}
            {item.provider !== item.job_provider && <p className="muted">此候选与原任务网盘不一致，请按目标网盘重新创建任务。</p>}
            <footer className="review-actions">
              <button className="primary review-confirm" onClick={() => void confirm(item)} disabled={busy !== null || item.provider !== item.job_provider}>
                {busy === item.id && busyAction === "confirm" ? <Spinner /> : <CheckCircle size={17} />}
                <span>
                  {busy === item.id && busyAction === "confirm"
                    ? transferStageLabel(progressStage)
                    : item.provider === "moviepilot_115"
                      ? "提交给 MoviePilot"
                      : (selectedFiles[item.id]?.length || 0) > 0
                      ? `转存所选文件 (${selectedFiles[item.id].length})`
                      : "使用此资源"}
                </span>
              </button>
              <button className="ghost" onClick={() => void research(item)} disabled={busy !== null}>
                {busy === item.id && busyAction === "research" ? <Spinner /> : <ArrowClockwise size={17} />}
                PanSou 重新搜索
              </button>
              <button className="ghost danger-action" onClick={() => void dismiss(item)} disabled={busy !== null}>
                {busy === item.id && busyAction === "delete" ? <Spinner /> : <Trash size={17} />}
                删除
              </button>
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}

function NotificationCenter({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  const [feed, setFeed] = useState<{ items: NotificationItem[]; unread_count: number }>({ items: [], unread_count: 0 });
  const [open, setOpen] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);

  async function load(silent = false) {
    if (!silent) setLoading(true);
    try {
      setFeed(await api.notifications(unreadOnly));
      setError("");
    } catch {
      setError("通知暂时无法加载");
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), 30_000);
    return () => window.clearInterval(timer);
  }, [unreadOnly]);

  useEffect(() => {
    function refreshFromAction(event: Event) {
      if (event instanceof CustomEvent && event.detail?.open) setOpen(true);
      void load(true);
    }
    window.addEventListener("mediaindex:notifications", refreshFromAction);
    return () => window.removeEventListener("mediaindex:notifications", refreshFromAction);
  }, [unreadOnly]);

  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, []);

  async function read(item: NotificationItem) {
    if (!item.is_read) {
      await api.markNotificationRead(item.id).catch(() => undefined);
      setFeed((current) => ({
        items: current.items.map((entry) => (entry.id === item.id ? { ...entry, is_read: 1 } : entry)),
        unread_count: Math.max(0, current.unread_count - 1),
      }));
    }
    const route = actionPageRoute(item.action_page);
    if (route) {
      onNavigate(route);
      setOpen(false);
    }
  }

  async function readAll() {
    await api.markNotificationRead();
    setFeed((current) => ({ items: current.items.map((item) => ({ ...item, is_read: 1 })), unread_count: 0 }));
  }

  async function clearAll() {
    if (!window.confirm("清空当前通知列表？已清空的通知不会再次显示。")) return;
    await api.clearNotifications();
    setFeed({ items: [], unread_count: 0 });
  }

  return (
    <div className="notification-center" ref={root}>
      <button
        className="icon notification-trigger"
        onClick={() => setOpen((value) => !value)}
        title="通知"
        aria-label={`通知${feed.unread_count ? `，${feed.unread_count} 条未读` : ""}`}
        aria-expanded={open}
      >
        <Bell size={18} weight={feed.unread_count ? "fill" : "regular"} />
        {feed.unread_count > 0 && <span className="notification-badge">{feed.unread_count > 99 ? "99+" : feed.unread_count}</span>}
      </button>
      {open && (
        <section className="notification-panel" aria-label="通知中心">
          <header className="notification-head">
            <div>
              <strong>通知</strong>
              <span>{feed.unread_count ? `${feed.unread_count} 条未读` : "全部已读"}</span>
            </div>
            <div className="notification-tools">
              <button onClick={() => void readAll()} disabled={!feed.unread_count} title="全部标为已读" aria-label="全部标为已读">
                <Checks size={17} />
              </button>
              <button onClick={() => void clearAll()} disabled={!feed.items.length} title="清空通知" aria-label="清空通知">
                <Trash size={16} />
              </button>
            </div>
          </header>
          <div className="notification-filter" role="group" aria-label="通知筛选">
            <button className={!unreadOnly ? "active" : ""} onClick={() => setUnreadOnly(false)}>全部</button>
            <button className={unreadOnly ? "active" : ""} onClick={() => setUnreadOnly(true)}>未读</button>
          </div>
          <div className="notification-list">
            {loading ? (
              <NotificationSkeleton />
            ) : error ? (
              <div className="notification-state error-state">
                <XCircle size={22} />
                <span>{error}</span>
                <button onClick={() => void load()}>重试</button>
              </div>
            ) : feed.items.length === 0 ? (
              <div className="notification-state">
                <Bell size={24} />
                <strong>{unreadOnly ? "没有未读通知" : "暂时没有通知"}</strong>
                <span>任务有新进展时会显示在这里</span>
              </div>
            ) : (
              feed.items.map((item) => (
                <button className={`notification-item ${item.poster_url ? "has-poster" : ""} ${item.is_read ? "read" : "unread"}`} key={item.id} onClick={() => void read(item)}>
                  <NotificationVisual item={item} />
                  <span className="notification-copy">
                    <strong>{item.title}</strong>
                    {item.message && <span>{item.message}</span>}
                    <time dateTime={item.created_at}>{formatNotificationTime(item.created_at)}</time>
                  </span>
                  {!item.is_read && <span className="unread-marker" aria-label="未读" />}
                </button>
              ))
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function NotificationVisual({ item }: { item: NotificationItem }) {
  const [failed, setFailed] = useState(false);
  if (item.poster_url && !failed) {
    return (
      <span className="notification-poster">
        <img src={item.poster_url} alt="" loading="lazy" onError={() => setFailed(true)} />
      </span>
    );
  }
  return <span className={`notification-type ${item.type}`}>{notificationIcon(item.type)}</span>;
}

function NotificationSkeleton() {
  return (
    <div className="notification-skeleton" aria-label="正在加载通知">
      {[0, 1, 2].map((item) => <span key={item} />)}
    </div>
  );
}

function notificationIcon(type: NotificationItem["type"]) {
  if (type === "success") return <CheckCircle size={18} weight="fill" />;
  if (type === "warning") return <WarningCircle size={18} weight="fill" />;
  if (type === "error") return <XCircle size={18} weight="fill" />;
  return <Info size={18} weight="fill" />;
}

function actionPageRoute(value: string): AppRoute | null {
  if (!["discover", "cloud", "tracking", "wishlist", "review", "settings", "push"].includes(value)) return null;
  return routeFromHash(`#${value}`);
}

function formatNotificationTime(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const timestamp = new Date(normalized).getTime();
  if (!Number.isFinite(timestamp)) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 604_800) return `${Math.floor(seconds / 86_400)} 天前`;
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(timestamp));
}

function reviewReasonLabel(reason: string) {
  if (reason.startsWith("episode_coverage:")) return `集数覆盖 ${reason.split(":")[1]}`;
  const labels: Record<string, string> = {
    title_exact_or_contained: "标题匹配",
    title_partial: "标题部分匹配",
    season_exact: "季数匹配",
    year_match: "年份匹配",
    target_episode_evidence: "发现目标集证据",
    derivative_content: "可能包含衍生内容",
    update_lags_target: "资源尚未更新到目标集",
    multiple_close_candidates: "存在多个相近文件",
    provider_execution_unavailable: "当前执行器尚未开放",
    external_organize_requires_confirmation: "需确认后提交给外部整理器",
  };
  return labels[reason] || reason.replaceAll("_", " ");
}

function taskToMedia(task: TrackingTask): MediaItem {
  return {
    id: task.tmdb_id,
    tmdb_id: task.tmdb_id,
    media_type: task.media_type as MediaItem["media_type"],
    category: task.category,
    title: task.title,
    year: task.year,
    poster_url: task.poster_url,
    overview: task.overview,
  };
}

function wishlistToMedia(item: WishlistItem): MediaItem {
  return {
    id: item.tmdb_id,
    tmdb_id: item.tmdb_id,
    media_type: item.media_type as MediaItem["media_type"],
    category: item.category,
    title: item.title,
    year: item.year,
    poster_url: item.poster_url,
    overview: item.overview,
  };
}

function mediaTypeLabel(mediaType: string) {
  if (mediaType === "movie") return "电影";
  if (mediaType === "variety") return "综艺";
  if (mediaType === "concert") return "演唱会";
  if (mediaType === "documentary") return "纪录片";
  if (mediaType === "anime") return "动漫";
  return "电视剧";
}

type PushProvider = "telegram" | "wecom" | "wecom_app";

function SettingsHub() {
  const [tab, setTab] = useState<SettingsTab>(() => {
    if (["#push", "#settings-notifications", "#settings-interaction", "#settings-transfer-records"].includes(window.location.hash)) return "notifications";
    if (window.location.hash === "#settings-network") return "network";
    if (["#settings-openlist", "#system/openlist"].includes(window.location.hash)) return "openlist";
    return "basic";
  });
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function selectTab(next: SettingsTab) {
    if (next === tab) return;
    if (dirty && !window.confirm("当前页面有未保存的设置，确定离开吗？")) return;
    setTab(next);
    const hashes: Record<SettingsTab, string> = {
      basic: "#settings",
      drives: "#workspace",
      network: "#settings-network",
      wishlist: "#subscriptions",
      openlist: "#settings-openlist",
      notifications: "#settings-notifications",
    };
    window.history.replaceState(null, "", hashes[next]);
  }

  return (
    <section className="settings-hub">
      <div className="settings-toolbar">
        <div className="settings-subnav" role="tablist" aria-label="设置页面">
          {([
            ["basic", "全局设置"],
            ["openlist", "OpenList 同步"],
            ["notifications", "通知和交互"],
            ["network", "网络代理"],
          ] as const).map(([value, label]) => (
            <button type="button" role="tab" aria-selected={tab === value} className={tab === value ? "active" : ""} onClick={() => selectTab(value)} key={value}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {tab === "notifications" ? <PushSettingsPage onDirtyChange={setDirty} /> : <SettingsPage section={tab} onDirtyChange={setDirty} />}
    </section>
  );
}

function PushSettingsPage({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [pushSection, setPushSection] = useState<"notifications" | "interaction" | "records">(() => {
    if (window.location.hash === "#settings-interaction") return "interaction";
    if (window.location.hash === "#settings-transfer-records") return "records";
    return "notifications";
  });
  const [wecomRecords, setWecomRecords] = useState<WecomTransferRecord[]>([]);
  const [saving, setSaving] = useState(false);
  const [testingChannel, setTestingChannel] = useState<PushProvider | null>(null);
  const [channelResults, setChannelResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [callbackCopied, setCallbackCopied] = useState(false);
  const [notificationChannel, setNotificationChannel] = useState<"wecom_app" | "wecom_bot" | "telegram">("wecom_app");
  const [providerDirectoryPicker, setProviderDirectoryPicker] = useState<{ provider: "qas" | "p115"; label: string; startPath: string; onSelect: (path: string) => void } | null>(null);
  const publicBaseUrl = (form.public_base_url || config?.public_base_url || window.location.origin).replace(/\/$/, "");
  const generatedCallbackUrl = `${publicBaseUrl}/api/notifications/wecom/callback`;
  const callbackUrl = form.wecom_callback_url ?? (config?.wecom_callback_url || generatedCallbackUrl);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setMessage("通知配置加载失败"));
  }, []);

  useEffect(() => {
    onDirtyChange?.(Object.keys(form).length > 0);
    return () => onDirtyChange?.(false);
  }, [form, onDirtyChange]);

  useEffect(() => {
    if (pushSection !== "records") return;
    let disposed = false;
    async function loadRecords() {
      try {
        const records = await api.wecomTransferRecords();
        if (!disposed) setWecomRecords(records);
      } catch {
        if (!disposed) setWecomRecords([]);
      }
    }
    void loadRecords();
    const timer = window.setInterval(() => void loadRecords(), 10000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [pushSection]);

  function selectPushSection(next: "notifications" | "interaction" | "records") {
    setPushSection(next);
    const hashes = {
      notifications: "#settings-notifications",
      interaction: "#settings-interaction",
      records: "#settings-transfer-records",
    } as const;
    window.history.replaceState(null, "", hashes[next]);
  }

  function update(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggleValue(key: string, saved: boolean) {
    return form[key] === undefined ? saved : form[key] === "true";
  }

  function directDownloadProvider(): "qas" | "p115" {
    return "p115";
  }

  function interactionProviders(): CloudProvider[] {
    const value = form.interaction_providers || (config?.interaction_providers || []).join(",");
    const selected = value.split(",").filter((item): item is CloudProvider => item === "qas" || item === "p115");
    return selected.length ? Array.from(new Set(selected)) : ["qas"];
  }

  function setInteractionProvider(provider: CloudProvider, enabled: boolean) {
    const selected = interactionProviders().filter((item) => item !== provider);
    if (enabled) selected.push(provider);
    if (!selected.length) return;
    update("interaction_providers", selected.join(","));
  }

  function providerRoot(provider: "qas" | "p115") {
    return normalizeOpenListPath(provider === "p115" ? config?.p115_root_path || "/" : config?.qas_root || config?.cloud_root || "/");
  }

  function pickDirectDownloadPath() {
    const provider = directDownloadProvider();
    const saved = form.direct_download_save_path || config?.direct_download_save_path || providerRoot(provider);
    setProviderDirectoryPicker({
      provider,
      label: `${provider === "p115" ? "115" : "夸克"}默认保存路径`,
      startPath: normalizeOpenListPath(saved),
      onSelect: (path) => update("direct_download_save_path", normalizeOpenListPath(path)),
    });
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const payload = buildPushConfigPayload(form);
      if (!("public_base_url" in payload)) {
        payload.public_base_url = config?.public_base_url || window.location.origin;
      }
      await api.saveConfig(payload);
      setConfig(await api.config());
      setForm({});
      setMessage("通知配置已保存");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "保存失败，请检查地址、AgentId 和必填项");
    } finally {
      setSaving(false);
    }
  }

  async function testNotificationChannel(provider: PushProvider) {
    setTestingChannel(provider);
    setChannelResults((current) => ({ ...current, [provider]: { ok: true, message: "正在发送测试消息…" } }));
    try {
      const result = await api.testNotificationChannel(provider);
      setChannelResults((current) => ({ ...current, [provider]: { ok: true, message: result.message } }));
    } catch (error) {
      const detail = error instanceof ApiError ? error.message : "发送失败，请先保存配置并检查凭据和接收范围";
      setChannelResults((current) => ({ ...current, [provider]: { ok: false, message: detail } }));
    } finally {
      setTestingChannel(null);
    }
  }

  async function copyCallbackUrl() {
    try {
      await navigator.clipboard.writeText(callbackUrl);
      setCallbackCopied(true);
      window.setTimeout(() => setCallbackCopied(false), 1800);
    } catch {
      window.prompt("复制企业微信回调 URL", callbackUrl);
    }
  }

  return (
    <section>
      <div className="page-head push-page-head">
        <div>
          <h1>{pushSection === "interaction" ? "交互指令" : pushSection === "records" ? "转存记录" : "通知设置"}</h1>
          <p>{pushSection === "interaction" ? "企业微信和 Telegram 共用同一套交互指令、网盘和转存规则。" : pushSection === "records" ? "集中查看企业微信和 Telegram 发起的交互转存结果。" : "配置企业微信、Telegram 和消息推送。密钥只保存在服务端。"}</p>
        </div>
        {pushSection === "records" && <PaperPlaneTilt size={32} aria-hidden />}
      </div>
      <div className="push-section-tabs" role="tablist" aria-label="通知与交互设置">
        <button type="button" role="tab" aria-selected={pushSection === "notifications"} className={pushSection === "notifications" ? "active" : ""} onClick={() => selectPushSection("notifications")}>
          通知
        </button>
        <button type="button" role="tab" aria-selected={pushSection === "interaction"} className={pushSection === "interaction" ? "active" : ""} onClick={() => selectPushSection("interaction")}>
          交互指令
        </button>
        <button type="button" role="tab" aria-selected={pushSection === "records"} className={pushSection === "records" ? "active" : ""} onClick={() => selectPushSection("records")}>
          转存记录
        </button>
      </div>
      {!config && <div className="list-skeleton" />}
      {config && (
        <form id="notification-settings-form" className={`settings-form push-settings-form push-section-${pushSection}`} onSubmit={save}>
          {pushSection === "notifications" && <>
          <SettingsSection title="推送总开关" body="启用后，新产生的转存结果和待处理事项会发送到下方已启用的渠道。">
            <SettingsToggle
              label="外部消息推送"
              value={toggleValue("notification_external_enabled", config.notification_external_enabled)}
              onChange={(value) => update("notification_external_enabled", String(value))}
              trueLabel="启用"
              falseLabel="关闭"
            />
            <div className="push-event-list" aria-label="推送事件">
              <span><CheckCircle size={17} />转存完成</span>
              <span><CheckCircle size={17} />Emby 入库完成（含海报）</span>
              <span><WarningCircle size={17} />需要确认</span>
              <span><Info size={17} />暂无资源</span>
              <span><XCircle size={17} />处理失败</span>
            </div>
            <SettingsInput
              label="公网访问地址"
              name="public_base_url"
              saved={Boolean(config.public_base_url)}
              value={form.public_base_url || ""}
              onChange={update}
              placeholder={config.public_base_url || window.location.origin}
              showSavedValue
            />
            <p className="channel-help">用于通知跳转、企业微信回调和缓存海报访问。请填写手机可以访问的 MediaIndex 地址，不要带页面路径。</p>
          </SettingsSection>

          <div className="notification-channel-tabs" role="tablist" aria-label="通知渠道">
            {([
              ["wecom_app", "企业微信"],
              ["wecom_bot", "企微机器人"],
              ["telegram", "Telegram"],
            ] as const).map(([value, label]) => (
              <button type="button" role="tab" aria-selected={notificationChannel === value} className={notificationChannel === value ? "active" : ""} onClick={() => setNotificationChannel(value)} key={value}>
                {label}
              </button>
            ))}
          </div>

          {notificationChannel === "wecom_app" && (
          <SettingsSection title="企业微信" body="通过自建应用定向发送消息，并可启用成员交互指令。">
            <div className="notification-channel-flat primary-channel">
              <div className="channel-heading">
                <div>
                  <strong>自建应用</strong>
                  <span>通过企业微信应用消息接口发送，可控制接收范围。</span>
                </div>
                <span className="recommended-label">推荐</span>
              </div>
              <SettingsToggle
                label="启用自建应用"
                value={toggleValue("wecom_app_enabled", config.wecom_app_enabled)}
                onChange={(value) => update("wecom_app_enabled", String(value))}
                trueLabel="启用"
                falseLabel="关闭"
              />
              <SettingsInput label="企业 ID (CorpId)" name="wecom_corp_id" saved={Boolean(config.wecom_corp_id)} value={form.wecom_corp_id || ""} onChange={update} placeholder={config.wecom_corp_id || "wwxxxxxxxxxxxxxxxx"} showSavedValue />
              <SettingsInput label="应用 Secret" name="wecom_app_secret" saved={config.has_wecom_app_secret} value={form.wecom_app_secret || ""} onChange={update} secret />
              <SettingsNumberInput
                label="AgentId"
                name="wecom_app_agent_id"
                value={form.wecom_app_agent_id || ""}
                placeholder={config.wecom_app_agent_id > 0 ? String(config.wecom_app_agent_id) : "1000002"}
                min={1}
                max={2147483647}
                onChange={update}
              />
              <SettingsInput label="接收成员" name="wecom_app_to_user" saved={Boolean(config.wecom_app_to_user)} value={form.wecom_app_to_user ?? ""} onChange={update} placeholder={config.wecom_app_to_user || "@all"} showSavedValue />
              <SettingsInput label="接收部门" name="wecom_app_to_party" saved={Boolean(config.wecom_app_to_party)} value={form.wecom_app_to_party ?? ""} onChange={update} placeholder={config.wecom_app_to_party || "1|2"} showSavedValue />
              <SettingsInput label="接收标签" name="wecom_app_to_tag" saved={Boolean(config.wecom_app_to_tag)} value={form.wecom_app_to_tag ?? ""} onChange={update} placeholder={config.wecom_app_to_tag || "1|2"} showSavedValue />
              <SettingsInput
                label="微信消息代理地址"
                help="仅用于代理 MediaIndex 向企业微信发送应用消息；未使用代理时填写 https://qyapi.weixin.qq.com，不是企业微信后台回调地址。"
                name="wecom_origin"
                saved
                value={form.wecom_origin || ""}
                onChange={update}
                placeholder={config.wecom_origin || "https://qyapi.weixin.qq.com"}
                showSavedValue
                action={(
                  <button type="button" className="primary compact-action" onClick={() => void testNotificationChannel("wecom_app")} disabled={testingChannel !== null}>
                    {testingChannel === "wecom_app" && <Spinner />}
                    测试自建应用
                  </button>
                )}
                result={channelResults.wecom_app}
              />
              <p className="channel-help">多个成员、部门或标签用竖线分隔。接收成员填写 @all 时，发送给应用可见范围内的全部成员。</p>
            </div>

            <div className="notification-channel-flat">
              <div className="channel-heading">
                <div>
                  <strong>交互指令回调</strong>
                  <span>接收企业微信成员发给自建应用的文本消息和菜单点击事件。</span>
                </div>
              </div>
              <SettingsToggle
                label="启用交互回调"
                value={toggleValue("wecom_callback_enabled", config.wecom_callback_enabled)}
                onChange={(value) => update("wecom_callback_enabled", String(value))}
                trueLabel="启用"
                falseLabel="关闭"
              />
              <SettingsInput label="回调 Token" name="wecom_callback_token" saved={config.has_wecom_callback_token} value={form.wecom_callback_token || ""} onChange={update} secret />
              <SettingsInput label="EncodingAESKey" name="wecom_callback_aes_key" saved={config.has_wecom_callback_aes_key} value={form.wecom_callback_aes_key || ""} onChange={update} secret />
              <SettingsInput
                label="允许指令的成员"
                name="wecom_callback_allowed_users"
                saved={Boolean(config.wecom_callback_allowed_users)}
                value={form.wecom_callback_allowed_users ?? ""}
                onChange={update}
                placeholder={config.wecom_callback_allowed_users || "留空允许应用可见范围内的成员"}
                showSavedValue
              />
              <SettingsInput
                label="企业微信后台回调 URL"
                name="wecom_callback_url"
                saved={Boolean(config.wecom_callback_url)}
                value={form.wecom_callback_url ?? ""}
                onChange={update}
                placeholder={config.wecom_callback_url || generatedCallbackUrl}
                showSavedValue
                action={(
                  <button type="button" className="ghost compact-action" onClick={() => void copyCallbackUrl()}>
                    {callbackCopied ? "已复制" : "复制 URL"}
                  </button>
                )}
              />
              <p className="channel-help">公网访问地址使用上方通知设置中的统一配置。Token 和 EncodingAESKey 要与企业微信管理后台填写的值完全一致；交互指令、关联网盘和默认路径在“交互指令”栏统一配置。</p>
            </div>
          </SettingsSection>
          )}

          {notificationChannel === "wecom_bot" && (
          <SettingsSection title="企微机器人" body="使用群聊机器人 Webhook，消息固定发送到机器人所在群聊。">
            <div className="notification-channel-flat">
              <div className="channel-heading">
                <div>
                  <strong>群机器人</strong>
                  <span>使用群聊机器人 webhook，消息固定发送到机器人所在群聊。</span>
                </div>
              </div>
              <SettingsToggle
                label="启用群机器人"
                value={toggleValue("wecom_enabled", config.wecom_enabled)}
                onChange={(value) => update("wecom_enabled", String(value))}
                trueLabel="启用"
                falseLabel="关闭"
              />
              <SettingsInput label="机器人 Key" name="wecom_key" saved={config.has_wecom_key} value={form.wecom_key || ""} onChange={update} secret />
              <div className="channel-test-row">
                <button type="button" className="ghost compact-action" onClick={() => void testNotificationChannel("wecom")} disabled={testingChannel !== null}>
                  {testingChannel === "wecom" && <Spinner />}
                  测试群机器人
                </button>
                {channelResults.wecom && <span className={channelResults.wecom.ok ? "success" : "danger"}>{channelResults.wecom.message}</span>}
              </div>
            </div>
          </SettingsSection>
          )}

          {notificationChannel === "telegram" && (
          <SettingsSection title="Telegram" body="通过 Telegram Bot API 发送通知，也可以接收资源名、指令和按钮操作。">
            <div>
              <SettingsToggle
                label="启用 Telegram"
                value={toggleValue("telegram_enabled", config.telegram_enabled)}
                onChange={(value) => update("telegram_enabled", String(value))}
                trueLabel="启用"
                falseLabel="关闭"
              />
              <SettingsInput label="Bot Token" name="telegram_bot_token" saved={config.has_telegram_token} value={form.telegram_bot_token || ""} onChange={update} secret />
              <SettingsInput label="Chat ID" name="telegram_chat_id" saved={Boolean(config.telegram_chat_id)} value={form.telegram_chat_id || ""} onChange={update} placeholder={config.telegram_chat_id || "-1001234567890"} showSavedValue />
              <SettingsInput
                label="API 地址"
                name="telegram_api_host"
                saved
                value={form.telegram_api_host || ""}
                onChange={update}
                placeholder={config.telegram_api_host || "https://api.telegram.org"}
                showSavedValue
                action={(
                  <button type="button" className="primary compact-action" onClick={() => void testNotificationChannel("telegram")} disabled={testingChannel !== null}>
                    {testingChannel === "telegram" && <Spinner />}
                    测试 Telegram
                  </button>
                )}
                result={channelResults.telegram}
              />
            </div>
            <p className="channel-help">保存 Bot Token 和 Chat ID 后，Telegram 会自动接收与企业微信相同的交互指令；资源选择会显示 Telegram 按钮。交互规则在“交互指令”栏统一配置。</p>
           </SettingsSection>
           )}

          </>}

          {pushSection === "interaction" && (
            <>
              <SettingsSection className="interaction-command-section" title="交互指令" body="企业微信和 Telegram 共用以下设置，不需要分别配置。">
                <div className="interaction-command-summary">
                  <strong>共用交互规则</strong>
                  <span>参与网盘、下载链接自动转存、默认保存路径和内置指令会同时作用于企业微信与 Telegram。</span>
                </div>
                <div className="direct-download-settings">
                  <div className="interaction-provider-settings">
                    <div className="interaction-provider-heading">
                      <strong>参与交互的网盘</strong>
                      <span>资源名、分享链接和智能追更会同时提交到已勾选的网盘。</span>
                    </div>
                    <div className="interaction-provider-grid">
                      {(["qas", "p115"] as CloudProvider[]).map((provider) => (
                        <SettingsToggle
                          key={provider}
                          label={provider === "qas" ? "夸克" : "115"}
                          value={interactionProviders().includes(provider)}
                          onChange={(value) => setInteractionProvider(provider, value)}
                          trueLabel="参与"
                          falseLabel="不参与"
                        />
                      ))}
                    </div>
                  </div>
                  <SettingsToggle
                    label="下载链接自动转存"
                    help="开启后，分享链接会直接转存；夸克和 115 分享链接会按链接类型使用对应网盘。磁力、电驴和普通 HTTP 链接使用下面设置的优先网盘。"
                    value={toggleValue("direct_download_enabled", config.direct_download_enabled)}
                    onChange={(value) => update("direct_download_enabled", String(value))}
                    trueLabel="启用"
                    falseLabel="关闭"
                  />
                  <div className="direct-download-grid">
                    <div className="settings-field compact-select-field">
                      <span>磁力 / 电驴默认网盘</span>
                      <strong>115（离线下载）</strong>
                    </div>
                    <SettingsInput
                      label="默认保存路径"
                      helpTooltip="收到分享链接后，会先反馈可选子文件夹；确认选择后再转存到对应目录。"
                      name="direct_download_save_path"
                      saved={Boolean(config.direct_download_save_path)}
                      value={form.direct_download_save_path || ""}
                      onChange={update}
                      placeholder={config.direct_download_save_path || "留空则使用所选网盘根目录下的 /下载链接"}
                      showSavedValue
                      action={(
                        <button
                          type="button"
                          className="ghost compact-action"
                          onClick={() => pickDirectDownloadPath()}
                          disabled={directDownloadProvider() === "p115" ? !config.has_p115_cookie : !config.has_qas}
                        >
                          <FolderOpen size={16} />
                          选择路径
                        </button>
                      )}
                    />
                    {directDownloadProvider() === "p115" && (
                      <p className="settings-help">115 分享链接转存和离线下载需要配置有效 Cookie。</p>
                    )}
                  </div>
                </div>
                <CommandReference />
              </SettingsSection>
              <section className="interaction-overview" aria-labelledby="interaction-overview-title">
                <div>
                  <strong id="interaction-overview-title">交互指令支持企业微信和 Telegram</strong>
                  <p>两端使用同一套资源搜索、链接转存、编号选择和状态查询逻辑；Telegram 通过 Bot API 轮询消息。</p>
                </div>
                <div className="interaction-capabilities">
                  <span><CheckCircle size={17} />企业微信自建应用：可接收指令</span>
                  <span><CheckCircle size={17} />Telegram：支持按钮交互</span>
                  <span><Info size={17} />群机器人：仅发送通知</span>
                </div>
              </section>
            </>
          )}

          {pushSection === "records" && <WecomTransferRecords records={wecomRecords} />}

          {pushSection !== "records" && <div className="settings-footer">
            <span>{saving ? "正在保存通知设置" : Object.keys(form).length ? "当前有尚未保存的修改" : "本页设置已与服务端同步"}</span>
            <button type="submit" className="primary compact-action" disabled={saving || Object.keys(form).length === 0}>
              {saving ? <Spinner /> : <FloppyDisk size={16} />}
              {saving ? "保存中" : "保存本页设置"}
            </button>
          </div>}
          {message && <div className="notice">{message}</div>}
        </form>
      )}
      {providerDirectoryPicker && (
        <ProviderDirectoryPicker
          provider={providerDirectoryPicker.provider}
          label={providerDirectoryPicker.label}
          startPath={providerDirectoryPicker.startPath}
          onClose={() => setProviderDirectoryPicker(null)}
          onSelect={(path) => {
            providerDirectoryPicker.onSelect(path);
            setProviderDirectoryPicker(null);
          }}
        />
      )}
    </section>
  );
}

function buildPushConfigPayload(form: Record<string, string>) {
  const payload: Record<string, string | number | boolean> = {};
  const booleanKeys = ["notification_external_enabled", "telegram_enabled", "wecom_enabled", "wecom_app_enabled", "wecom_callback_enabled", "direct_download_enabled"];
  const clearableKeys = ["wecom_app_to_user", "wecom_app_to_party", "wecom_app_to_tag", "wecom_callback_allowed_users", "wecom_callback_url", "direct_download_save_path"];
  Object.entries(form).forEach(([key, value]) => {
    if (booleanKeys.includes(key)) {
      payload[key] = value === "true";
    } else if (key === "wecom_app_agent_id") {
      if (value.trim()) payload[key] = Number(value);
    } else if (value.trim() || clearableKeys.includes(key)) {
      payload[key] = value.trim();
    }
  });
  return payload;
}

function SettingsPage({ section, onDirtyChange }: { section: Exclude<SettingsTab, "notifications">; onDirtyChange?: (dirty: boolean) => void }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [testingTmdb, setTestingTmdb] = useState(false);
  const [tmdbTestResult, setTmdbTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [testingQas, setTestingQas] = useState(false);
  const [qasTestResult, setQasTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [testingP115, setTestingP115] = useState(false);
  const [p115Result, setP115Result] = useState<{ ok: boolean; message: string } | null>(null);
  const [cookieHelpOpen, setCookieHelpOpen] = useState(false);
  const [qasPansouEnabled, setQasPansouEnabled] = useState<boolean | null>(null);
  const [settingQasPansou, setSettingQasPansou] = useState(false);
  const [providerSettingsTab, setProviderSettingsTab] = useState<"qas" | "p115">("qas");
  const [testingOpenList, setTestingOpenList] = useState(false);
  const [openListResult, setOpenListResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [directoryPicker, setDirectoryPicker] = useState<{ key: string; label: string; onSelect?: (path: string) => void } | null>(null);
  const [providerDirectoryPicker, setProviderDirectoryPicker] = useState<{ provider: "qas" | "p115"; label: string; startPath: string; onSelect: (path: string) => void } | null>(null);
  const [openListTab, setOpenListTab] = useState<"settings" | "auto">("settings");

  useEffect(() => {
    api.config().then(setConfig);
    api.qasPansouStatus().then((result) => {
      if (result.ok && typeof result.enabled === "boolean") setQasPansouEnabled(result.enabled);
    }).catch(() => setQasPansouEnabled(null));
  }, []);

  useEffect(() => {
    onDirtyChange?.(Object.keys(form).length > 0);
    return () => onDirtyChange?.(false);
  }, [form, onDirtyChange]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await api.saveConfig(buildConfigPayload(form));
      const next = await api.config();
      setConfig(next);
      setForm({});
      setMessage("已保存配置");
      window.dispatchEvent(new Event("mediaindex:providers-changed"));
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  function update(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function selectCategoryPath(provider: "qas" | "p115", key: string, label: string) {
    const root = normalizeOpenListPath(
      provider === "p115"
        ? form.p115_root_path || config?.p115_root_path || "/"
        : form.qas_save_path || config?.qas_root || config?.cloud_root || "/",
    );
    const current = normalizeOpenListPath(form[`${provider}_category_paths.${key}`] || (provider === "p115" ? config?.p115_category_paths?.[key] : config?.qas_category_paths?.[key]) || `/${key}`);
    const startPath = current === "/" ? root : normalizeOpenListPath(`${root}/${current.replace(/^\/+/, "")}`);
    setProviderDirectoryPicker({
      provider,
      label: `${label}分类路径`,
      startPath,
      onSelect: (selectedPath) => {
        const normalized = normalizeOpenListPath(selectedPath);
        const relative = root && (normalized === root || normalized.startsWith(`${root}/`))
          ? normalized.slice(root.length) || "/"
          : normalized;
        update(`${provider}_category_paths.${key}`, normalizeCategoryInputPath(relative));
      },
    });
  }

  function selectProviderSavePath(provider: "qas" | "p115", key: string, label: string, savedPath: string) {
    setProviderDirectoryPicker({
      provider,
      label,
      startPath: normalizeOpenListPath(form[key] || savedPath || "/"),
      onSelect: (selectedPath) => update(key, normalizeOpenListPath(selectedPath)),
    });
  }

  async function testTmdb() {
    setTestingTmdb(true);
    setTmdbTestResult(null);
    try {
      const result = await api.testTmdb();
      setTmdbTestResult({ ok: result.ok, message: result.message });
    } catch (error) {
      setTmdbTestResult({ ok: false, message: error instanceof ApiError ? error.message : "TMDB 连接失败" });
    } finally {
      setTestingTmdb(false);
    }
  }

  async function testQas() {
    setTestingQas(true);
    setQasTestResult(null);
    try {
      const result = await api.testQas();
      setQasTestResult({ ok: result.ok, message: result.message });
    } catch (error) {
      setQasTestResult({ ok: false, message: error instanceof ApiError ? error.message : "QAS 连接失败" });
    } finally {
      setTestingQas(false);
    }
  }

  async function testP115() {
    setTestingP115(true);
    setP115Result(null);
    try {
      const result = await api.testP115();
      setP115Result({ ok: result.ok, message: result.message });
    } catch (error) {
      setP115Result({ ok: false, message: error instanceof ApiError ? error.message : "115 连接失败" });
    } finally {
      setTestingP115(false);
    }
  }

  async function testOpenList() {
    setTestingOpenList(true);
    setOpenListResult(null);
    try {
      const result = await api.testOpenList();
      setOpenListResult({ ok: result.ok, message: result.message });
    } catch (error) {
      setOpenListResult({ ok: false, message: error instanceof ApiError ? error.message : "OpenList 连接失败" });
    } finally {
      setTestingOpenList(false);
    }
  }

  function setProviderEnabled(provider: CloudProvider, enabled: boolean) {
    const current = (form.enabled_providers || config?.enabled_providers.filter((value) => value !== "moviepilot_115").join(",") || "qas")
      .split(",")
      .filter((value): value is CloudProvider => value === "qas" || value === "quark" || value === "p115");
    const next = enabled ? [...new Set([...current, provider])] : current.filter((value) => value !== provider);
    if (!next.length) {
      setMessage("至少保留一个网盘 Provider");
      return;
    }
    setForm((values) => ({ ...values, enabled_providers: next.join(","), default_provider: next[0] }));
  }

  async function setQasPansou(enabled: boolean) {
    setSettingQasPansou(true);
    setMessage("");
    try {
      const result = await api.setQasPansou(enabled);
      if (result.ok && typeof result.enabled === "boolean") setQasPansouEnabled(result.enabled);
      setMessage(result.message);
    } catch {
      setMessage(`${enabled ? "启用" : "禁用"} QAS 自带搜索失败`);
    } finally {
      setSettingQasPansou(false);
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>{section === "basic" ? "全局设置" : section === "drives" ? "网盘设置" : section === "network" ? "网络代理" : section === "wishlist" ? "巡检" : "OpenList 同步"}</h1>
          <p>{section === "basic" ? "管理全局资料服务与配置备份；网盘、命名和质量规则均在对应流程页面维护。" : section === "drives" ? "分别管理夸克与 115 的连接、保存目录和分类路径。" : section === "network" ? "统一配置服务端访问外部网络时使用的代理。" : section === "wishlist" ? "统一设置愿望单和智能追更的巡检策略。" : "配置 OpenList 连接、挂载目录和自动同步方向；手动跨盘复制在一级菜单中执行。"}</p>
        </div>
      </div>
      {!config && <div className="list-skeleton" />}
      {config && (
        <form id={`${section}-settings-form`} className="settings-form" onSubmit={save}>
          {section === "basic" && (
          <>
          <SettingsSection title="影视资料服务" body="TMDB 为发现、详情核对和刮削提供媒体资料；网盘连接与资源来源在网盘工作台维护。">
            <SettingsInput
              label="TMDB API Key"
              name="tmdb_api_key"
              saved={config.has_tmdb_key}
              value={form.tmdb_api_key || ""}
              onChange={update}
              secret
              action={(
                <button type="button" className="primary compact-action" onClick={() => void testTmdb()} disabled={testingTmdb || saving}>
                  {testingTmdb && <Spinner />}
                  {testingTmdb ? "测试中" : "测试连接"}
                </button>
              )}
              result={tmdbTestResult}
            />
          </SettingsSection>

          <ConfigBackupSettings onImported={async () => setConfig(await api.config())} spinner={() => <Spinner />} />
          </>
          )}

          {section === "drives" && (
          <section className="provider-settings-shell" aria-label="网盘独立设置">
            <div className="provider-settings-tabs" role="tablist" aria-label="选择网盘设置">
              <button type="button" role="tab" aria-selected={providerSettingsTab === "qas"} className={providerSettingsTab === "qas" ? "active" : ""} onClick={() => setProviderSettingsTab("qas")}>
                <span className="provider-tab-icon">夸克（QAS）</span>
              </button>
              <button type="button" role="tab" aria-selected={providerSettingsTab === "p115"} className={providerSettingsTab === "p115" ? "active" : ""} onClick={() => setProviderSettingsTab("p115")}>
                <span className="provider-tab-icon">115</span>
              </button>
            </div>
            <div className="provider-settings-panel" role="tabpanel">
              <header className="provider-panel-heading">
                <div>
                  <h2>{providerSettingsTab === "qas" ? "夸克（QAS）" : "115"}</h2>
                </div>
                <span className={`provider-state ${(form.enabled_providers || config.enabled_providers.join(",")).split(",").includes(providerSettingsTab) ? "enabled" : ""}`}>
                  {(form.enabled_providers || config.enabled_providers.join(",")).split(",").includes(providerSettingsTab) ? "已启用" : "已停用"}
                </span>
              </header>

              {providerSettingsTab === "qas" ? (
                <div className="provider-module-grid">
                  <SettingsSection title="服务连接" body="连接 QAS，负责夸克分享读取、转存和改名。">
                    <SettingsInput label="QAS 地址" name="qas_base_url" saved={Boolean(config.qas_base_url)} value={form.qas_base_url || ""} onChange={update} placeholder={config.qas_base_url || "http://your-qas-host:5005"} showSavedValue />
                    <SettingsInput label="QAS Token" name="qas_token" saved={config.has_qas} value={form.qas_token || ""} onChange={update} secret />
                    <div className="settings-action-strip provider-connection-actions">
                      <button type="button" className="primary compact-action provider-test-button" onClick={() => void testQas()} disabled={testingQas || saving}>
                        {testingQas && <Spinner />}
                        {testingQas ? "测试中" : "测试连接"}
                      </button>
                      <ProviderConnectionStatus connected={config.has_qas} label="QAS" />
                      {qasTestResult && <div className={`settings-inline-result ${qasTestResult.ok ? "success" : "error"}`}>{qasTestResult.message}</div>}
                    </div>
                    <SettingsToggle
                      label="QAS 自带搜索"
                      help="QAS 内置的 PanSou 数据源可能比独立 PanSou 少，建议停用，避免重复检索或结果冲突。"
                      value={qasPansouEnabled ?? false}
                      onChange={(enabled) => void setQasPansou(enabled)}
                      trueLabel="启用"
                      falseLabel="停用"
                      disabled={qasPansouEnabled === null || settingQasPansou}
                      busy={settingQasPansou}
                    />
                  </SettingsSection>
                  <SettingsSection title="保存路径" body="只用于夸克，不与 115 共用。">
                    <SettingsInput
                      label="夸克保存根路径"
                      name="qas_save_path"
                      saved
                      value={form.qas_save_path || ""}
                      onChange={update}
                      placeholder={config.qas_root}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("qas", "qas_save_path", "夸克保存根路径", config.qas_root)} disabled={!config.has_qas} title="选择目录" aria-label="选择夸克保存根路径"><FolderOpen size={18} /></button>}
                    />
                    <SettingsInput
                      label="本地保存根路径"
                      name="local_save_path"
                      saved
                      value={form.local_save_path || ""}
                      onChange={update}
                      placeholder={config.local_root}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("qas", "local_save_path", "本地保存根路径", config.local_root)} disabled={!config.has_qas} title="选择目录" aria-label="选择本地保存根路径"><FolderOpen size={18} /></button>}
                    />
                    <p className="settings-help">本地保存由 QAS 执行，因此与夸克路径放在同一模块管理。</p>
                  </SettingsSection>
                  <SettingsSection title="分类路径" body="夸克根目录下的分类子目录，可增加自定义分类。">
                    <CategoryPathSettings config={config} form={form} onChange={setForm} provider="qas" canPickPath={config.has_qas} onPickPath={(key, label) => selectCategoryPath("qas", key, label)} />
                  </SettingsSection>
                </div>
              ) : (
                <div className="provider-module-grid">
                  <SettingsSection title="115 服务连接" body="使用 115 Cookie 连接个人网盘。">
                    <SettingsInput
                      label="115 Cookie"
                      name="p115_cookie"
                      saved={config.has_p115_cookie}
                      value={form.p115_cookie || ""}
                      onChange={update}
                      secret
                      action={(
                        <button type="button" className="icon settings-info-button" onClick={() => setCookieHelpOpen(true)} title="查看 Cookie 获取说明" aria-label="查看 Cookie 获取说明">
                          <Info size={18} />
                        </button>
                      )}
                    />
                    <div className="settings-action-strip provider-connection-actions">
                      <button type="button" className="primary compact-action provider-test-button" onClick={() => void testP115()} disabled={testingP115 || saving}>
                        {testingP115 && <Spinner />}
                        {testingP115 ? "测试中" : "测试连接"}
                      </button>
                      <ProviderConnectionStatus connected={config.has_p115_cookie} label="115" />
                      {p115Result && <div className={`settings-inline-result ${p115Result.ok ? "success" : "error"}`}>{p115Result.message}</div>}
                    </div>
                  </SettingsSection>
                  <SettingsSection title="保存路径" body="只用于 115，不与夸克共用；暂存目录用于安全改名和移动。">
                    <SettingsInput
                      label="115 保存根目录"
                      name="p115_root_path"
                      saved
                      value={form.p115_root_path || ""}
                      onChange={update}
                      placeholder={config.p115_root_path}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("p115", "p115_root_path", "115 保存根目录", config.p115_root_path)} disabled={!config.has_p115_cookie} title="选择目录" aria-label="选择 115 保存根目录"><FolderOpen size={18} /></button>}
                    />
                    <SettingsInput
                      label="115 网盘暂存目录"
                      name="p115_staging_path"
                      saved
                      value={form.p115_staging_path || ""}
                      onChange={update}
                      placeholder={config.p115_staging_path}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("p115", "p115_staging_path", "115 网盘暂存目录", config.p115_staging_path)} disabled={!config.has_p115_cookie} title="选择目录" aria-label="选择 115 网盘暂存目录"><FolderOpen size={18} /></button>}
                    />
                    <p className="settings-help">暂存目录位于 115 网盘内，仅用于接收、核对、改名后再移动到最终媒体目录，不是 NAS 本地目录。</p>
                    <SettingsInput
                      label="115 转存本地目录"
                      name="p115_local_path"
                      saved
                      value={form.p115_local_path || ""}
                      onChange={update}
                      placeholder={config.p115_local_path || "/downloads"}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("p115", "p115_local_path", "115 转存本地目录", config.p115_local_path || "/downloads")} disabled={!config.has_p115_cookie} title="选择目录" aria-label="选择 115 转存本地目录"><FolderOpen size={18} /></button>}
                    />
                    <p className="settings-help">可选，用于 MP 整理等非直接保存的路径。</p>
                  </SettingsSection>
                  <SettingsSection title="分类路径" body="115 根目录下的分类子目录，可增加自定义分类。">
                    <CategoryPathSettings config={config} form={form} onChange={setForm} provider="p115" canPickPath={config.has_p115_cookie} onPickPath={(key, label) => selectCategoryPath("p115", key, label)} />
                  </SettingsSection>
                </div>
              )}
            </div>
          </section>
          )}

          {section === "openlist" && (
          <>
          <div className="openlist-mode-tabs" role="tablist" aria-label="OpenList 功能">
            {([["settings", "目录配置"], ["auto", "自动同步"]] as const).map(([value, label]) => (
              <button type="button" role="tab" aria-selected={openListTab === value} className={openListTab === value ? "active" : ""} onClick={() => setOpenListTab(value)} key={value}>{label}</button>
            ))}
          </div>
          {openListTab === "settings" && (
          <SettingsSection title="OpenList 网盘间同步" body="通过 OpenList API 在已挂载的夸克媒体库和 115 媒体库之间复制缺失文件；不影响 MediaIndex 原生转存。">
            <SettingsToggle label="启用 OpenList 功能" value={form.openlist_enabled === undefined ? config.openlist_enabled : form.openlist_enabled === "true"} onChange={(value) => update("openlist_enabled", String(value))} trueLabel="启用" falseLabel="停用" />
            <SettingsToggle label="允许自动同步" help="开启后，仅在双网盘转存完成或智能追更执行同步时，按对应媒体目录复制缺失文件；不会定时复制整个媒体库。" value={form.openlist_auto_sync === undefined ? config.openlist_auto_sync : form.openlist_auto_sync === "true"} onChange={(value) => update("openlist_auto_sync", String(value))} trueLabel="允许" falseLabel="关闭" />
            <SettingsInput label="OpenList 地址" name="openlist_url" saved={Boolean(config.openlist_url)} value={form.openlist_url || ""} onChange={update} placeholder={config.openlist_url || "http://openlist:5244"} showSavedValue />
            <SettingsInput label="OpenList Token" name="openlist_token" saved={config.has_openlist_token} value={form.openlist_token || ""} onChange={update} secret />
            <SettingsInput label="夸克媒体库目录" help="填写 OpenList 挂载路径及其下的目录，例如 /夸克/strm，不是本地文件系统路径。" name="openlist_qas_library_path" saved value={form.openlist_qas_library_path || ""} onChange={update} placeholder={config.openlist_qas_library_path} showSavedValue action={<button type="button" className="ghost compact-action" onClick={() => setDirectoryPicker({ key: "openlist_qas_library_path", label: "夸克媒体库目录" })} disabled={!config.has_openlist_token}>选择目录</button>} />
            <SettingsInput label="115 媒体库目录" help="填写 OpenList 挂载路径及其下的目录，例如 /115/媒体库，不是本地文件系统路径。" name="openlist_p115_library_path" saved value={form.openlist_p115_library_path || ""} onChange={update} placeholder={config.openlist_p115_library_path} showSavedValue action={<button type="button" className="ghost compact-action" onClick={() => setDirectoryPicker({ key: "openlist_p115_library_path", label: "115 媒体库目录" })} disabled={!config.has_openlist_token}>选择目录</button>} />
            <div className="settings-action-strip">
              <button type="button" className="primary compact-action" onClick={() => void testOpenList()} disabled={testingOpenList || saving || !config.openlist_enabled}>
                {testingOpenList && <Spinner />}{testingOpenList ? "测试中" : "测试连接"}
              </button>
              {openListResult && <div className={`settings-inline-result ${openListResult.ok ? "success" : "error"}`}>{openListResult.message}</div>}
            </div>
            <p className="settings-help">这里仅维护连接与挂载目录；选择源、目标和创建复制任务请前往一级菜单“跨盘转存”。</p>
          </SettingsSection>
          )}
          {openListTab === "auto" && (
            <SettingsSection title="追更自动补齐" body="智能追更发现某一集只存在一个网盘时，只复制这一集到缺失网盘，不进行全量同步。">
              <SettingsToggle label="允许自动同步" help="开启后，MediaIndex 会在双网盘转存完成、智能追更转存完成后自动对比两边目录，缺哪边就从另一边复制过去。" value={form.openlist_auto_sync === undefined ? config.openlist_auto_sync : form.openlist_auto_sync === "true"} onChange={(value) => update("openlist_auto_sync", String(value))} trueLabel="允许" falseLabel="关闭" />
              <div className="settings-field openlist-direction-setting">
                <span>自动同步方向</span>
                <Segmented
                  value={form.openlist_auto_sync_direction || config.openlist_auto_sync_direction || "bidirectional"}
                  items={[["qas_to_p115", "夸克 → 115"], ["p115_to_qas", "115 → 夸克"], ["bidirectional", "双向同步"]]}
                  onChange={(value) => update("openlist_auto_sync_direction", value)}
                />
              </div>
              <p className="settings-help">自动同步已接入执行任务窗口；相同目录正在同步时不会重复提交。需要两个媒体库目录都能通过 OpenList Token 读取，并且目标网盘允许复制写入。</p>
              <p className="settings-help">方向只约束链接转存、发现卡片、愿望单巡检和智能追更完成后触发的自动复制；手动同步与追更卡片中的手动补齐不受限制。</p>
            </SettingsSection>
          )}
          <OpenListTaskPanel limit={20} />
          </>
          )}

          {section === "network" && (
          <SettingsSection title="网络代理" body="用于 TMDB、PanSou 等公共网络请求；留空时直接连接。">
            <SettingsInput
              label="代理地址"
              name="proxy_url"
              saved={config.has_proxy}
              value={form.proxy_url ?? ""}
              onChange={update}
              placeholder={config.proxy_url || "http://192.168.1.2:7890"}
            />
            <p className="settings-help">支持 HTTP/HTTPS 代理；如果需要认证，可填写带用户名和密码的完整地址。</p>
          </SettingsSection>
          )}

          {section === "wishlist" && (<>
          <SettingsSection title="愿望单" body={`默认在 TMDB 日期当天 ${String(config.wishlist_default_check_hour).padStart(2, "0")}:00 检查，每张愿望单仍可单独调整。`}>
            <SettingsToggle
              label="启用自动巡检"
              value={form.wishlist_scheduler_enabled === undefined ? config.wishlist_scheduler_enabled : form.wishlist_scheduler_enabled === "true"}
              onChange={(value) => update("wishlist_scheduler_enabled", String(value))}
            />
            <SettingsNumberInput label="巡检周期（分钟）" name="wishlist_poll_minutes" value={form.wishlist_poll_minutes || ""} placeholder={String(config.wishlist_poll_minutes)} min={1} max={1440} onChange={update} />
            <SettingsNumberInput label="默认检查小时" name="wishlist_default_check_hour" value={form.wishlist_default_check_hour || ""} placeholder={String(config.wishlist_default_check_hour)} min={0} max={23} onChange={update} />
          </SettingsSection>
          <SettingsSection title="智能追更" body="在 TMDB 更新日期当天的设定时间开始检查；资源尚未发布时静默重试，只有发现当前文件但无法安全匹配时才请求确认。">
            <SettingsToggle label="启用自动巡检" help="关闭后仍可在智能追更卡片中手动执行。" value={form.tracking_scheduler_enabled === undefined ? config.tracking_scheduler_enabled : form.tracking_scheduler_enabled === "true"} onChange={(value) => update("tracking_scheduler_enabled", String(value))} />
            <label className="settings-field"><span>追更时间</span><input type="time" value={form.tracking_check_time || config.tracking_check_time} onChange={(event) => update("tracking_check_time", event.target.value)} /></label>
            <SettingsNumberInput label="巡检轮询周期（分钟）" name="tracking_poll_minutes" value={form.tracking_poll_minutes || ""} placeholder={String(config.tracking_poll_minutes)} min={1} max={1440} onChange={update} />
            <SettingsNumberInput label="重试间隔（分钟）" name="tracking_retry_interval_minutes" value={form.tracking_retry_interval_minutes || ""} placeholder={String(config.tracking_retry_interval_minutes)} min={1} max={1440} onChange={update} />
            <SettingsNumberInput label="巡检次数" name="tracking_max_retries" value={form.tracking_max_retries || ""} placeholder={String(config.tracking_max_retries)} min={1} max={20} onChange={update} />
          </SettingsSection>
          </>)}
          <div className="settings-footer">
            <span>版本 {config.version}</span>
            <span>{saving ? "正在保存" : Object.keys(form).length ? "当前有尚未保存的修改" : "本页设置已与服务端同步"}</span>
            <button type="submit" className="primary compact-action" disabled={saving || Object.keys(form).length === 0}>
              {saving ? <Spinner /> : <FloppyDisk size={16} />}
              {saving ? "保存中" : "保存本页设置"}
            </button>
          </div>
          {message && <div className="notice">{message}</div>}
        </form>
      )}
      {cookieHelpOpen && (
        <div className="modal-backdrop" onClick={() => setCookieHelpOpen(false)}>
          <article className="settings-help-modal" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => setCookieHelpOpen(false)} title="关闭">×</button>
            <Info size={28} weight="fill" />
            <h2>115 Cookie 获取方式</h2>
            <p>MediaIndex 使用 115 Cookie 连接个人网盘。Cookie 必须包含 UID、CID、SEID。</p>
            <ol>
              <li><strong>直接粘贴：</strong>登录 115 网页端，按 OpenList 文档中的 Cookie 获取说明取得 Cookie，再粘贴到这里。</li>
            </ol>
            <p className="settings-help">Cookie 等同账号登录凭据，只会保存在 MediaIndex 服务端；不要截图、转发或提交到 Git。</p>
            <a className="primary compact-action settings-help-link" href="https://docs.openlist.team/zh/guide/drivers/115" target="_blank" rel="noreferrer">
              查看 OpenList 115 获取文档 <ArrowSquareOut size={16} />
            </a>
          </article>
        </div>
      )}
      {directoryPicker && (
        <OpenListDirectoryPicker
          label={directoryPicker.label}
          onClose={() => setDirectoryPicker(null)}
          onSelect={(path) => {
            if (directoryPicker.onSelect) {
              directoryPicker.onSelect(path);
            } else {
              update(directoryPicker.key, path);
            }
            setDirectoryPicker(null);
          }}
        />
      )}
      {providerDirectoryPicker && (
        <ProviderDirectoryPicker
          provider={providerDirectoryPicker.provider}
          label={providerDirectoryPicker.label}
          startPath={providerDirectoryPicker.startPath}
          onClose={() => setProviderDirectoryPicker(null)}
          onSelect={(path) => {
            providerDirectoryPicker.onSelect(path);
            setProviderDirectoryPicker(null);
          }}
        />
      )}
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
