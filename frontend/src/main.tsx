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
  GithubLogo,
  File,
  FolderOpen,
  Info,
  MagnifyingGlass,
  Moon,
  MinusCircle,
  Pause,
  PaperPlaneTilt,
  Play,
  PlusCircle,
  Question,
  ShareNetwork,
  SignOut,
  Sun,
  TerminalWindow,
  Trash,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { api, ApiError, ConfigStatus, Genre, MediaItem, NotificationItem, OpenListEntry, ResourceStatus, ReviewCandidate, TrackingProviderState, TrackingTask, TransferBatch, TransferJob, WishlistItem } from "./lib/api";
import { ConfigBackupSettings } from "./features/settings/ConfigBackupSettings";
import "./styles.css";

type Page = "discover" | "tracking" | "wishlist" | "review" | "settings";
type SettingsTab = "basic" | "drives" | "openlist" | "notifications" | "wishlist" | "network";
type Theme = "light" | "dark";
type CloudProvider = "qas" | "p115";

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
      setError("鐢ㄦ埛鍚嶆垨瀵嗙爜涓嶆纭?);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-panel" onSubmit={submit}>
        <BrandLogo login />
        <h1>Media Index</h1>
        <p>鐧诲綍浣犵殑 NAS 濯掍綋鑷姩鍖栨帶鍒跺彴銆?/p>
        <label>
          鐢ㄦ埛鍚?
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
        </label>
        <label>
          瀵嗙爜
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? "鐧诲綍涓? : "鐧诲綍"}
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
  const [page, setPage] = useState<Page>(() => {
    const hashPage = window.location.hash.replace("#", "");
    if (hashPage === "push" || hashPage.startsWith("settings-")) return "settings";
    return isPage(hashPage) ? hashPage : "discover";
  });
  const [enabledProviders, setEnabledProviders] = useState<CloudProvider[]>([]);
  const nav = [
    ["discover", "鍙戠幇"],
    ["tracking", "鏅鸿兘杩芥洿"],
    ["wishlist", "宸℃"],
    ["review", "寰呯‘璁?],
    ["settings", "璁剧疆"],
  ] as const;

  useEffect(() => {
    let active = true;
    async function refreshProviders() {
      try {
        const config = await api.config();
        if (!active) return;
        setEnabledProviders((["qas", "p115"] as const).filter((value) => config.enabled_providers.includes(value)));
      } catch {
        if (active) setEnabledProviders(["qas"]);
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

  function navigate(next: Page) {
    setPage(next);
    window.history.replaceState(null, "", next === "discover" ? window.location.pathname : `#${next}`);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="wordmark" onClick={() => navigate("discover")}>
          <BrandLogo />
          Media Index
        </button>
        <nav>
          {nav.map(([key, label]) => (
            <button key={key} className={page === key ? "active" : ""} onClick={() => navigate(key)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="top-actions">
          <span className="user-pill">{user}</span>
          <ActivityCenter />
          <NotificationCenter onNavigate={navigate} />
          <a
            className="icon"
            href="https://github.com/xudong7587/media-index"
            target="_blank"
            rel="noreferrer"
            title="鎵撳紑 GitHub 浠撳簱"
            aria-label="鎵撳紑 Media Index GitHub 浠撳簱"
          >
            <GithubLogo size={18} weight="fill" />
          </a>
          <button className="icon" onClick={() => setTheme(theme === "light" ? "dark" : "light")} title="鍒囨崲涓婚">
            {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <button className="icon" onClick={logout} title="閫€鍑?>
            <SignOut size={18} />
          </button>
        </div>
      </header>
      <main className="content">
        {page === "discover" && <DiscoverPage enabledProviders={enabledProviders} />}
        {page === "tracking" && <TrackingPage enabledProviders={enabledProviders} />}
        {page === "wishlist" && <WishlistPage enabledProviders={enabledProviders} />}
        {page === "review" && <ReviewPage enabledProviders={enabledProviders} />}
        {page === "settings" && <SettingsHub />}
      </main>
    </div>
  );
}

function DiscoverPage({ enabledProviders }: { enabledProviders: CloudProvider[] }) {
  const [mediaType, setMediaType] = useState<"movie" | "tv" | "variety" | "concert" | "documentary" | "anime">("movie");
  const [region, setRegion] = useState("");
  const [sort, setSort] = useState("hot");
  const [genre, setGenre] = useState("");
  const [genres, setGenres] = useState<Genre[]>([]);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<MediaItem | null>(null);
  const [trackingSelection, setTrackingSelection] = useState<MediaItem | null>(null);
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [trackingAction, setTrackingAction] = useState("");
  const [pageMessage, setPageMessage] = useState("");
  const [discoverPage, setDiscoverPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [genreExpanded, setGenreExpanded] = useState(false);

  async function load(page = discoverPage, refresh = false) {
    setLoading(true);
    setError("");
    try {
      const res = query.trim() ? await api.search(query.trim()) : await api.discover(mediaType, region, sort, genre, 0, page, 24, refresh);
      setItems(res.results || []);
      setTotalPages("total_pages" in res && typeof res.total_pages === "number" ? res.total_pages || 1 : 1);
      if ("page" in res && typeof res.page === "number") setDiscoverPage(res.page);
      if ("error" in res && res.error) setError("TMDB 灏氭湭閰嶇疆");
    } catch {
      setError("鍔犺浇澶辫触");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setDiscoverPage(1);
    void load(1);
  }, [mediaType, region, sort, genre]);

  useEffect(() => {
    setGenre("");
    api.genres(mediaType).then(setGenres).catch(() => setGenres([]));
  }, [mediaType]);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  async function addTrackingFromDiscover(item: MediaItem) {
    const actionKey = `${item.media_type}-${item.tmdb_id}`;
    setTrackingAction(actionKey);
    setPageMessage("");
    try {
      const detail = await api.details(item.media_type, item.tmdb_id);
      const media = { ...detail, category: item.category || detail.category || item.media_type };
      const seasons = (detail.seasons || []).filter((season) => season.season_number > 0);
      const latest = seasons.at(-1)?.season_number ?? 1;
      const providers = enabledProviders.length ? enabledProviders : (["qas"] as CloudProvider[]);
      await Promise.all(providers.map((provider) => api.createTracking(media, latest, "cloud", provider)));
      const ongoingText = detail.status && detail.status !== "Ended" ? "锛岃繛杞戒腑濯掍綋宸叉寜鏈€鏂板杩芥洿" : "";
      setPageMessage(`宸插皢銆?{item.title}銆嬪姞鍏ユ櫤鑳借拷鏇?{ongoingText}銆俙);
    } catch (error) {
      setPageMessage(error instanceof Error ? error.message : "鍔犲叆鏅鸿兘杩芥洿澶辫触");
    } finally {
      setTrackingAction("");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>鍙戠幇</h1>
          <p>浠?TMDB 鍙戠幇鍐呭锛岀‘璁ゅ悗浜ょ粰宸插惎鐢ㄧ殑缃戠洏鎵ц杞瓨銆?/p>
        </div>
        <form
          className="search"
          onSubmit={(event) => {
            event.preventDefault();
            setDiscoverPage(1);
            void load(1);
          }}
        >
          <MagnifyingGlass size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="鎼滅储鐢靛奖銆佸墽闆嗐€佺患鑹虹瓑鍐呭" />
        </form>
      </div>

      <div className="toolbar">
        <Segmented
          value={mediaType}
          items={[
            ["movie", "鐢靛奖"],
            ["tv", "鐢佃鍓?],
            ["variety", "缁艰壓"],
            ["concert", "婕斿敱浼?],
            ["documentary", "绾綍鐗?],
            ["anime", "鍔ㄦ极"],
          ]}
          onChange={(value) => setMediaType(value as typeof mediaType)}
        />
        <Segmented
          value={region}
          items={[
            ["", "鍏ㄩ儴"],
            ["cn", "鍗庤"],
          ]}
          onChange={setRegion}
        />
        <button className="ghost" onClick={() => void load(discoverPage, true)} disabled={loading}>
          <ArrowClockwise size={16} />
          鍒锋柊
        </button>
      </div>
      <div className="filter-panel">
        <FilterRow label="鎺掑簭">
          <Segmented
            value={sort}
            items={[
              ["latest", "鏈€鏂?],
              ["hot", "鐑棬"],
              ["rating", "璇勫垎"],
            ]}
            onChange={setSort}
          />
        </FilterRow>
        <FilterRow label="椋庢牸">
          <div className="genre-filter">
            <button className="genre-toggle" onClick={() => setGenreExpanded((value) => !value)} aria-expanded={genreExpanded}>
              <CaretDown size={15} className={genreExpanded ? "expanded" : ""} />
              {genreExpanded ? "鏀惰捣椋庢牸" : "灞曞紑椋庢牸"}
              {!genreExpanded && genre && <span>{genres.find((item) => String(item.id) === genre)?.name}</span>}
            </button>
            {genreExpanded && (
              <div className="chip-row">
                <button className={genre === "" ? "chip active" : "chip"} onClick={() => setGenre("")}>
                  鍏ㄩ儴
                </button>
                {genres.map((g) => (
                  <button key={g.id} className={genre === String(g.id) ? "chip active" : "chip"} onClick={() => setGenre(String(g.id))}>
                    {g.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </FilterRow>
      </div>

      {loading && <PosterSkeleton />}
      {!loading && error && <Empty title={error} body="璇峰埌璁剧疆椤电‘璁?TMDB 閰嶇疆銆? />}
      {pageMessage && <div className="notice page-notice">{pageMessage}</div>}
      {!loading && !error && items.length === 0 && <Empty title="娌℃湁缁撴灉" body="鎹釜鍏抽敭璇嶆垨鍒嗙被璇曡瘯銆? />}
      {!loading && !error && (
        <>
          <div className="poster-grid">
            {items.map((item) => {
              const canTrack = canSmartTrackMedia(item, mediaType);
              return (
                <article className="poster-card" key={`${item.media_type}-${item.tmdb_id}`}>
                  <button className="poster-card-main" onClick={() => setSelected(item)} aria-label={`鏌ョ湅${item.title}璇︽儏`}>
                    <Poster item={item} />
                    <span className="poster-title">{item.title}</span>
                    <span className="poster-meta">{item.release_date ? `鍙戣 ${item.release_date}` : item.year ? `鍙戣 ${item.year}` : "鍙戣鏃ユ湡寰呭畾"}</span>
                  </button>
                  {canTrack && (
                    <button
                      type="button"
                      className="poster-track-action"
                      onClick={() => setTrackingSelection(item)}
                      aria-label={`灏?{item.title}鍔犲叆鏅鸿兘杩芥洿`}
                      disabled={trackingAction === `${item.media_type}-${item.tmdb_id}`}
                    >
                      {trackingAction === `${item.media_type}-${item.tmdb_id}` ? <Spinner /> : <Eye size={15} />}
                      {trackingAction === `${item.media_type}-${item.tmdb_id}` ? "鍔犲叆涓? : "鍔犲叆鏅鸿兘杩芥洿"}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
          {!query.trim() && items.length > 0 && (
            <div className="pagination-bar" aria-label="鍙戠幇鍒嗛〉">
              <span>绗?{discoverPage} 椤?/ 鍏?{totalPages} 椤?/span>
              <button
                className="pagination-arrow"
                disabled={discoverPage <= 1 || loading}
                onClick={() => {
                  const prev = Math.max(1, discoverPage - 1);
                  setDiscoverPage(prev);
                  void load(prev);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                title="涓婁竴椤?
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
                title="涓嬩竴椤?
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
      {selected && <MediaDialog item={selected} onClose={() => setSelected(null)} enabledProviders={enabledProviders} />}
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
  const actionText = action === "transfer" ? "杞瓨鍒扮綉鐩? : "鍔犲叆鏅鸿兘杩芥洿";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="tracking-category-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="鍏抽棴">脳</button>
        <div className="tracking-category-heading">
          <div>
            <h2>閫夋嫨濯掍綋搴撶洰褰?/h2>
            <p>{item.title}灏嗘寜鎵€閫夊垎绫粄actionText}銆?/p>
          </div>
          <FolderOpen size={28} aria-hidden />
        </div>
        <div className="tracking-category-options">
          {categories.map((category) => {
            const fallback = configuredPaths[category] || "鏈缃?;
            const qasPath = qasPaths[category] || fallback;
            const p115Path = p115Paths[category] || fallback;
            return (
              <button type="button" className="tracking-category-option" key={category} onClick={() => onSelect(category)}>
                <span className="tracking-category-option-title">{mediaTypeLabel(category)}</span>
                <span>澶稿厠锛歿qasPath}</span>
                <span>115锛歿p115Path}</span>
                <CaretRight size={17} />
              </button>
            );
          })}
        </div>
        {!config && <p className="settings-help">姝ｅ湪璇诲彇宸蹭繚瀛樼殑鐩綍閰嶇疆锛屾湭璇诲彇鍒版椂浠嶅彲缁х画浣跨敤榛樿鍒嗙被銆?/p>}
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
  const [progressProvider, setProgressProvider] = useState<"qas" | "p115" | "">("");
  const [copiedProvider, setCopiedProvider] = useState<"qas" | "p115" | "">("");
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [categoryPrompt, setCategoryPrompt] = useState<"" | "tracking" | "cloud">("");

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

  const media = detail || item;
  const canTrack = canSmartTrackMedia(media);
  const isOngoing = canTrack && media.status !== "Ended";
  const seasons = (media.seasons || []).filter((value) => value.season_number > 0);
  const latestSeason = seasons.at(-1)?.season_number ?? 1;
  const orderedSelection = [...selectedSeasons].sort((a, b) => a - b);
  const allSeasonsSelected = seasons.length > 0 && orderedSelection.length === seasons.length;
  const resourceSelection = canTrack ? orderedSelection : [0];
  const selectedResourceStatuses = resourceSelection.flatMap((number) =>
    enabledProviders.map((provider) => seasonResources[resourceKey(provider, number)]).filter(Boolean),
  );
  const foundProviderItems = resourceSelection.flatMap((number) =>
    enabledProviders.filter((provider) => seasonResources[resourceKey(provider, number)]?.found),
  ).length;
  const readySeasonCount = resourceSelection.filter((number) =>
    enabledProviders.some((provider) => seasonResources[resourceKey(provider, number)]?.found),
  ).length;
  const allResourcesFound = resourceSelection.length > 0 && readySeasonCount === resourceSelection.length;
  const anyRequiresReview = selectedResourceStatuses.some((value) => value.requires_review);
  const isTracked = canTrack && orderedSelection.some((number) => trackingTasks.some((task) => task.tmdb_id === media.tmdb_id && task.season_number === number));
  const localProvider: CloudProvider | undefined = enabledProviders.includes("qas")
    ? "qas"
    : enabledProviders.includes("p115")
      ? "p115"
      : undefined;
  const canSaveCloud = allResourcesFound && !resourceLoading && !busy && !completed;
  const localResourcesFound = Boolean(
    localProvider
    && resourceSelection.every((number) => seasonResources[resourceKey(localProvider, number)]?.found),
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
    ? "姝ｅ湪鍒嗗埆楠岃瘉澶稿厠鍜?115 璧勬簮"
    : !allResourcesFound
      ? "姣忎釜宸查€夊搴﹁嚦灏戦渶瑕佷竴涓綉鐩樻壘鍒板彲鐢ㄨ祫婧?
      : busy
        ? "姝ｅ湪鎵ц杞瓨"
        : completed
          ? "鏈杞瓨宸插畬鎴?
          : "";

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
        let result: ResourceStatus = { ok: false, found: false, message: "璧勬簮鎼滅储澶辫触", provider };
        try {
          result = await api.resources(currentDetail, canTrack ? number : undefined, false, provider);
        } catch {
          result = { ok: false, found: false, message: `${providerLabel(provider)}璧勬簮鎼滅储澶辫触`, provider };
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
      const providers = enabledProviders.length ? enabledProviders : (["qas"] as CloudProvider[]);
      await Promise.allSettled(
        orderedSelection.flatMap((seasonNumber) =>
          providers.map((provider) => api.createTracking(actionMedia, seasonNumber, "cloud", provider)),
        ),
      );
      const latestText = orderedSelection.includes(latestSeason) && isOngoing ? "锛屾渶鏂板浼氭寜杩芥洿鏃堕棿缁х画妫€鏌? : "";
      setMessage(`宸插皢 ${orderedSelection.map((number) => `S${number}`).join("銆?)} 鍔犲叆鏅鸿兘杩芥洿${latestText}銆俙);
      api.tracking().then(setTrackingTasks).catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "鍔犲叆鏅鸿兘杩芥洿澶辫触");
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
            .filter((provider) => seasonResources[resourceKey(provider, seasonNumber)]?.found)
            .map((provider) => ({
              provider,
              season_number: canTrack ? seasonNumber : undefined,
              episode_numbers: selectedSeasonEpisodes[seasonNumber],
            })),
        ).filter((item) => item.episode_numbers === undefined || item.episode_numbers.length > 0);
        if (!batchItems.length) {
          setMessage("褰撳墠娌℃湁宸查獙璇佸彲鐢ㄧ殑缃戠洏璧勬簮銆?);
          return;
        }
        const started = await api.createTransferBatch(actionMedia, batchItems);
        const batch = await waitForTransferBatch(started.id, (current) => {
          const running = current.children.find((child) => child.status === "running");
          if (running) {
            setProgressStage(running.stage);
            setProgressSeason(running.season_number || 0);
            setProgressProvider(running.provider === "p115" ? "p115" : "qas");
          }
        });
        const successful = batch.children.filter((child) => child.status === "done" || child.status === "triggered").length;
        const failed = batch.children.length - successful;
        const trackedProviders = batch.children
          .filter((child) => (child.status === "done" || child.status === "triggered") && child.season_number === latestSeason && (child.provider === "qas" || child.provider === "p115"))
          .map((child) => child.provider as CloudProvider);
        if (isOngoing && trackedProviders.length) {
          await Promise.allSettled([...new Set(trackedProviders)].map((provider) => api.createTracking(actionMedia, latestSeason, "cloud", provider)));
          api.tracking().then(setTrackingTasks).catch(() => undefined);
        }
        if (successful) setCompleted("cloud");
        setMessage(
          failed
            ? `宸插畬鎴?${successful} 涓綉鐩樹换鍔★紝${failed} 涓け璐ユ垨闇€瑕佺‘璁わ紱鎴愬姛缃戠洏宸茬户缁浆瀛樸€俙
            : `宸插畬鎴?${successful} 涓綉鐩樹换鍔?{isOngoing && trackedProviders.length ? "锛屾渶鏂板宸插姞鍏ユ櫤鑳借拷鏇? : ""}銆俙,
        );
        return;
      }
      const results: TransferJob[] = [];
      for (const seasonNumber of orderedSelection) {
        setProgressSeason(seasonNumber);
        setProgressProvider(localProvider || "qas");
        const started = await api.createTransfer(actionMedia, target, canTrack ? seasonNumber : undefined, localProvider);
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
        setMessage(`宸插鐞?${successful} 瀛?{isOngoing && orderedSelection.includes(latestSeason) ? "锛屾渶鏂板宸插姞鍏ユ櫤鑳借拷鏇? : ""}銆俙);
      } else {
        setMessage(`宸插鐞?${successful} 瀛ｏ紝${failed} 瀛ｆ湭瀹屾垚锛屽彲璋冩暣閫夋嫨鍚庨噸璇曘€俙);
      }
    } catch {
      setMessage("鍒涘缓浠诲姟澶辫触");
    } finally {
      setBusy("");
      setProgressStage("");
      setProgressSeason(0);
      setProgressProvider("");
    }
  }

  async function transferProvider(provider: "qas" | "p115") {
    setBusy("cloud");
    setProgressProvider(provider);
    setMessage("");
    try {
      const items = resourceSelection
        .filter((number) => seasonResources[resourceKey(provider, number)]?.found)
        .map((number) => ({ provider, season_number: canTrack ? number : undefined, episode_numbers: selectedSeasonEpisodes[number] }))
        .filter((item) => item.episode_numbers === undefined || item.episode_numbers.length > 0);
      if (!items.length) return;
      const started = await api.createTransferBatch(media, items);
      const batch = await waitForTransferBatch(started.id, (current) => {
        const running = current.children.find((child) => child.status === "running");
        if (running) setProgressStage(running.stage);
      });
      const successful = batch.children.filter((child) => child.status === "done" || child.status === "triggered").length;
      setMessage(successful ? `${providerLabel(provider)}宸插畬鎴?${successful} 涓浆瀛樹换鍔°€俙 : `${providerLabel(provider)}杞瓨鏈畬鎴愶紝璇锋煡鐪嬮€氱煡銆俙);
    } finally {
      setBusy("");
      setProgressProvider("");
      setProgressStage("");
    }
  }

  async function copyProviderShare(provider: "qas" | "p115") {
    const url = resourceSelection
      .map((number) => {
        const status = seasonResources[resourceKey(provider, number)];
        return status?.share_url || status?.source_share_url;
      })
      .find(Boolean);
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopiedProvider(provider);
    setMessage(`宸插鍒?{providerLabel(provider)}鍒嗕韩閾炬帴锛堝寘鍚彁鍙栫爜锛夈€俙);
    window.setTimeout(() => setCopiedProvider((current) => current === provider ? "" : current), 1800);
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
      let result: ResourceStatus = { ok: false, found: false, message: "璧勬簮鍒锋柊澶辫触", provider };
      try {
        result = await api.resources(detail, canTrack ? number : undefined, true, provider);
      } catch (error) {
        result = { ok: false, found: false, message: error instanceof Error ? error.message : `${providerLabel(provider)}璧勬簮鍒锋柊澶辫触`, provider };
      }
      setSeasonResources((current) => ({ ...current, [key]: result }));
      setResourceLoadingKeys((current) => current.filter((value) => value !== key));
    }));
    setResourceLoadingKeys([]);
    setResourceLoading(false);
    setMessage("宸查噸鏂版悳绱㈠綋鍓嶉€夋嫨鐨勮祫婧愩€?);
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
    setMessage(nextEnabled ? "OpenList 鑷姩鍚屾宸叉墦寮€銆? : "OpenList 鑷姩鍚屾宸插叧闂€?);
    try {
      await api.saveConfig({ openlist_auto_sync: nextEnabled });
      window.dispatchEvent(new CustomEvent("mediaindex:providers-changed"));
    } catch (error) {
      setConfig({ ...config, openlist_auto_sync: !nextEnabled });
      setMessage(error instanceof Error ? error.message : "OpenList 鑷姩鍚屾璁剧疆淇濆瓨澶辫触");
    }
  }

  return (
    <>
    <div className="modal-backdrop" onClick={onClose}>
      <article className="media-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="鍏抽棴">
          脳
        </button>
        <div className="modal-hero">
          {media.backdrop_url && <img src={media.backdrop_url} alt="" />}
        </div>
        <div className="modal-body">
          <Poster item={media} compact />
          <div className="modal-main">
            <h2>{media.title}</h2>
            <p className="muted">{[media.year, media.genres?.join(" / "), media.status].filter(Boolean).join(" / ")}</p>
            {canTrack && Boolean(media.seasons?.length) && (
              <div className="season-row season-selector">
                <button className={`season-select-all ${allSeasonsSelected ? "active" : ""}`} onClick={selectAllSeasons} aria-label="鍏ㄩ€夊搴? title="鍏ㄩ€夊搴?>
                  <CheckSquare size={16} weight={allSeasonsSelected ? "fill" : "regular"} />
                  <span>鍏ㄩ€?/span>
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
                    `${providerShortLabel(provider)}${loading ? "鈥? : status?.found ? "鉁? : status ? "脳" : "路"}`,
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
                        title={`灞曞紑 S${s.season_number} 宸叉绱㈠墽闆哷}
                        aria-label={`灞曞紑 S${s.season_number} 宸叉绱㈠墽闆哷}
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
                  <strong>S{expandedSeason} 宸叉绱㈠墽闆?/strong>
                  <span>鍕鹃€夊悗浠呰浆瀛樻墍閫夐泦</span>
                </div>
                <div className="season-episode-picker-list">
                  {availableSeasonEpisodes(expandedSeason).map((episodeNumber) => {
                    const selected = (selectedSeasonEpisodes[expandedSeason] || availableSeasonEpisodes(expandedSeason)).includes(episodeNumber);
                    return <button type="button" key={episodeNumber} className={selected ? "selected" : ""} onClick={() => toggleSeasonEpisode(expandedSeason, episodeNumber)}>E{String(episodeNumber).padStart(2, "0")}</button>;
                  })}
                </div>
              </div>
            )}
            <p>{media.overview || "鏆傛棤绠€浠嬨€?}</p>
            {isTracked && <div className="tracking-lock"><CheckCircle size={17} /> 閫変腑鐨勫搴︿腑鏈夊凡鍔犲叆鏅鸿兘杩芥洿鐨勯」鐩紝浠嶅彲鎵嬪姩杞瓨</div>}
            <div className="provider-progress-grid" aria-label="缃戠洏璧勬簮楠岃瘉鐘舵€?>
              {enabledProviders.map((provider) => {
                const statuses = resourceSelection.map((number) => seasonResources[resourceKey(provider, number)]).filter(Boolean);
                const found = statuses.filter((status) => status.found).length;
                const transferable = statuses.filter((status) => status.ready ?? (status.found && !status.requires_review)).length;
                const reviewCount = statuses.filter((status) => status.requires_review).length;
                const candidateCount = statuses.reduce((count, status) => count + (status.candidate_count || 0), 0);
                const transferableFiles = statuses.reduce((count, status) => count + ((status.ready ?? (status.found && !status.requires_review)) ? Math.max(1, status.file_count || 0) : 0), 0);
                const loading = resourceSelection.some((number) => resourceLoadingKeys.includes(resourceKey(provider, number)));
                const hasShareLink = statuses.some((status) => status.share_url || status.source_share_url);
                const cardState = reviewCount ? "review" : transferable ? "found" : candidateCount ? "candidate" : "";
                const statusLabel = loading
                  ? "妫€绱腑鈥?
                  : canTrack
                    ? transferable
                      ? `${transferable}/${resourceSelection.length} 瀛ｅ彲杞瓨`
                      : reviewCount
                        ? `${reviewCount} 瀛ｅ€欓€夊緟纭`
                        : candidateCount
                          ? `${candidateCount} 涓€欓€夎祫婧恅
                          : "鏆傛棤鍙敤璧勬簮"
                    : transferable
                      ? `${transferableFiles} 涓祫婧愬彲杞瓨`
                      : reviewCount
                        ? `${reviewCount} 涓€欓€夊緟纭`
                        : candidateCount
                          ? `${candidateCount} 涓€欓€夎祫婧恅
                          : "鏆傛棤鍙敤璧勬簮";
                const hint = loading
                  ? "姝ｅ湪楠岃瘉璧勬簮"
                  : reviewCount
                    ? "鐐瑰嚮杩涘叆纭"
                    : transferable
                      ? "鐐瑰嚮杞瓨鑷宠缃戠洏"
                      : candidateCount
                        ? "鍊欓€夊皻鏈畬鎴愰獙璇?
                        : "绛夊緟鍙敤璧勬簮";
                return (
                  <div className={`provider-progress-card ${cardState}`} key={provider}>
                    <button type="button" className="provider-progress-main" disabled={!found || Boolean(busy)} onClick={() => void transferProvider(provider)}>
                      {loading ? <Spinner /> : reviewCount || candidateCount ? <WarningCircle size={17} /> : transferable === resourceSelection.length ? <CheckCircle size={17} /> : <CloudArrowDown size={17} />}
                      <strong>{providerLabel(provider)}</strong>
                      <span>{statusLabel}</span>
                      <small>{hint}</small>
                    </button>
                    {found > 0 && (
                      <button type="button" className={`provider-share-action ${copiedProvider === provider ? "copied" : ""}`} title={hasShareLink ? copiedProvider === provider ? "宸插鍒? : "鍒嗕韩閾炬帴" : "鏆傛棤鍙鍒跺垎浜摼鎺?} aria-label={hasShareLink ? copiedProvider === provider ? `宸插鍒?{providerLabel(provider)}鍒嗕韩閾炬帴` : `鍒嗕韩${providerLabel(provider)}閾炬帴` : `${providerLabel(provider)}鏆傛棤鍙鍒跺垎浜摼鎺} disabled={!hasShareLink} onClick={() => void copyProviderShare(provider)}>
                        {copiedProvider === provider ? <Check size={16} weight="bold" /> : <ShareNetwork size={16} weight="bold" />}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="action-row">
              {canTrack && (
                <button className="secondary action-button" onClick={() => setCategoryPrompt("tracking")} disabled={Boolean(busy)}>
                  <Eye size={18} />
                  <span>{isTracked ? "鏇存柊杩芥洿璺緞" : "鍔犲叆鏅鸿兘杩芥洿"}</span>
                </button>
              )}
              <button className="primary action-button" onClick={() => canTrack ? setCategoryPrompt("cloud") : void transfer("cloud")} disabled={!canSaveCloud} title={saveDisabledReason}>
                {completed === "cloud" ? <CheckCircle size={18} /> : busy === "cloud" ? <Spinner /> : <CloudArrowDown size={18} />}
                <span>{completed === "cloud" ? "宸插畬鎴? : busy === "cloud" ? `${progressProvider ? `${providerShortLabel(progressProvider)} ` : ""}${progressSeason ? `S${progressSeason} ` : ""}${transferStageLabel(progressStage)}` : "杞瓨鍏ㄩ儴缃戠洏"}</span>
              </button>
              {localProvider && (
                <button className="secondary action-button" onClick={() => transfer("local")} disabled={!canSaveLocal} title={saveDisabledReason}>
                  {completed === "local" ? <CheckCircle size={18} /> : busy === "local" ? <Spinner /> : <HardDrives size={18} />}
                  <span>{completed === "local" ? "宸插畬鎴? : busy === "local" ? `${progressSeason ? `S${progressSeason} ` : ""}${transferStageLabel(progressStage)}` : "瀛樻湰鍦?}</span>
                </button>
              )}
              <button
                className="secondary action-button"
                onClick={() => void refreshSelectedResources()}
                disabled={resourceLoading || Boolean(busy)}
                title="閲嶆柊鎼滅储褰撳墠閫夋嫨鐨勮祫婧?
              >
                {resourceLoading ? <Spinner /> : <ArrowClockwise size={18} />}
                <span>{resourceLoading ? resourceSearchLabel(resourceStage) : "鍒锋柊璧勬簮"}</span>
              </button>
              <button
                className={`ghost action-button resource-button resource-status-button ${canToggleOpenListAutoSync ? "with-sync-toggle" : "full-row"} ${allResourcesFound ? "found" : ""} ${resourceLoading ? "loading" : ""}`}
                disabled={resourceLoading || Boolean(busy)}
                title={resourceSelection.flatMap((number) => enabledProviders.map((provider) => `${canTrack ? `S${number} ` : ""}${providerLabel(provider)}锛?{seasonResources[resourceKey(provider, number)]?.message || "绛夊緟妫€鏌?}`)).join("\n")}
                onClick={() => {
                  if (!allResourcesFound) {
                    const missing = resourceSelection.filter((number) => !enabledProviders.some((provider) => seasonResources[resourceKey(provider, number)]?.found));
                    void Promise.all(missing.map((number) => api.addWishlist(media, canTrack ? number : undefined))).then(() =>
                      setMessage(`宸插皢 ${missing.length} 涓殏鏃犺祫婧愮殑瀛ｅ害鍔犲叆鎰挎湜鍗曘€俙),
                    );
                  }
                }}
              >
                {resourceLoading ? <Spinner /> : allResourcesFound ? <CheckCircle size={18} /> : <Heart size={18} />}
                <span>{resourceLoading ? resourceSearchLabel(resourceStage) : canTrack ? anyRequiresReview ? `宸查獙璇?${foundProviderItems} 涓綉鐩樿祫婧愶紝閮ㄥ垎闇€纭` : allResourcesFound ? `${readySeasonCount}/${resourceSelection.length} 瀛ｈ嚦灏戜竴涓綉鐩樺彲鐢╜ : `${readySeasonCount}/${resourceSelection.length} 瀛ｅ彲鐢紝鍔犲叆缂哄け鎰挎湜鍗昤 : allResourcesFound ? `${foundProviderItems} 涓綉鐩樿祫婧愬彲鐢╜ : "鏆傛棤璧勬簮锛屽姞鍏ユ効鏈涘崟"}</span>
              </button>
              {canToggleOpenListAutoSync && (
                <button
                  type="button"
                  className={`secondary action-button openlist-auto-toggle ${config?.openlist_auto_sync ? "active" : ""}`}
                  onClick={() => void toggleOpenListAutoSync()}
                  disabled={Boolean(busy)}
                  title="鑷姩鎶婃柊澧為泦鍚屾鍒板彟涓€涓綉鐩?
                >
                  {config?.openlist_auto_sync ? <Checks size={18} /> : <ArrowClockwise size={18} />}
                  <span>{config?.openlist_auto_sync ? "鑷姩鍚屾寮€" : "鑷姩鍚屾鍏?}</span>
                </button>
              )}
            </div>
            {message && <div className="notice">{message}</div>}
          </div>
        </div>
      </article>
    </div>
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
    </>
  );
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

function resourceSearchLabel(stage: number) {
  return ["姝ｅ湪鑾峰彇濯掍綋淇℃伅锛岃鍕垮叧闂崱鐗?, "姝ｅ湪鑾峰彇 PanSou 璧勬簮锛岃鍕垮叧闂崱鐗?, "姝ｅ湪楠岃瘉閾炬帴鏈夋晥鎬э紝璇峰嬁鍏抽棴鍗＄墖", "姝ｅ湪涓?TMDB 鏍稿锛岃鍕垮叧闂崱鐗?][stage] || "姝ｅ湪鎼滅储璧勬簮锛岃鍕垮叧闂崱鐗?;
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
    setActionLabel("姝ｅ湪閫氳繃 PanSou 妫€鏌ヨ祫婧愨€?);
    const stageTimer = window.setTimeout(() => setActionLabel("姝ｅ湪楠岃瘉骞惰浆瀛樷€?), 1200);
    try {
      await Promise.all(item.provider_states.filter((state) => enabledProviders.includes(state.provider)).map((state) => api.runWishlist(state.id)));
      await load();
    } finally {
      window.clearTimeout(stageTimer);
      setActionLabel("");
      setBusy(null);
    }
  }

  async function setWishlistProvider(item: WishlistItem, provider: "qas" | "p115") {
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
      <div className="page-head">
        <div>
          <h1>鎰挎湜鍗?/h1>
          <p>鏆傛椂娌℃湁璧勬簮鐨勫奖鐗囦細鍏堟斁鍦ㄨ繖閲岋紝鍚庣画鎸夎缃嚜鍔ㄥ贰妫€銆?/p>
        </div>
        <button className="ghost" onClick={() => void load()}>
          <ArrowClockwise size={16} />
          鍒锋柊
        </button>
      </div>
      {loading && <div className="list-skeleton" />}
      {!loading && items.length === 0 && <Empty title="鎰挎湜鍗曟槸绌虹殑" body="鍦ㄨ鎯呴〉閬囧埌鏆傛棤璧勬簮鏃讹紝鍙互鍏堝姞鍏ユ効鏈涘崟銆? />}
      <div className="task-list">
        {items.map((item) => (
          <article className="task-row" key={item.id}>
            <Poster item={wishlistToMedia(item)} compact />
            <div className="task-main">
              <div className="task-title-line">
                <h3>{item.title}</h3>
                <span className="status">{wishlistStateLabel(item.status)}</span>
              </div>
              <p className="task-overview">{item.overview || "鏆傛棤绠€浠嬨€?}</p>
              <p>{[item.year, mediaTypeLabel(item.category || item.media_type), `鍔犲叆鏃堕棿 ${item.created_at?.slice(0, 10)}`].filter(Boolean).join(" / ")}</p>
              <p>
                {item.tmdb_date ? `TMDB 鏃ユ湡 ${item.tmdb_date}` : "绛夊緟 TMDB 鏇存柊鏃ユ湡"}
                {item.next_check_at ? ` / 涓嬫妫€鏌?${formatTrackingTime(item.next_check_at)}` : ""}
              </p>
              {item.last_error && <p className="danger">{item.last_error}</p>}
            </div>
            <div className="row-actions wishlist-control-panel">
              <div className="schedule-picker">
                <button
                  className="schedule-button"
                  title={item.next_check_at ? `涓嬫妫€鏌?${formatTrackingTime(item.next_check_at)}` : "璁剧疆姣忔棩妫€鏌ユ椂闂?}
                  onClick={() => setScheduleOpen(scheduleOpen === item.id ? null : item.id)}
                  disabled={busy === item.id}
                >
                  {String(item.check_hour ?? 9).padStart(2, "0")}:00
                </button>
                {scheduleOpen === item.id && (
                  <div className="schedule-menu" role="menu" aria-label="閫夋嫨妫€鏌ユ椂闂?>
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
              <div className="provider-choice row-provider-choice" aria-label="鎰挎湜鍗曠綉鐩?>
                {enabledProviders.map((provider) => (
                  <button type="button" className={item.provider_states.some((state) => state.provider === provider) ? "active" : ""} onClick={() => void setWishlistProvider(item, provider)} disabled={busy === item.id} key={provider}>
                    {item.provider_states.some((state) => state.provider === provider) && <Check size={14} />}
                    {providerLabel(provider)}
                  </button>
                ))}
              </div>
              <button className="ghost immediate-run" title="绔嬪嵆鎵ц" onClick={() => void runNow(item)} disabled={busy === item.id}>
                {busy === item.id ? <Spinner /> : <ArrowClockwise size={16} />}
                {busy === item.id ? actionLabel : "绔嬪嵆鎵ц"}
              </button>
              <button className="icon danger-icon" title="鍒犻櫎" onClick={() => void remove(item)}>
                <Trash size={16} />
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function TrackingPage({ enabledProviders }: { enabledProviders: CloudProvider[] }) {
  const [items, setItems] = useState<TrackingTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [taskAction, setTaskAction] = useState("");
  const [actionNotice, setActionNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [scheduleDrafts, setScheduleDrafts] = useState<Record<number, string>>({});
  const [expandedTask, setExpandedTask] = useState<number | null>(null);
  const [taskEpisodes, setTaskEpisodes] = useState<Record<number, { episode_number: number; status: string; title: string; air_date: string; aired: boolean }[]>>({});
  const [selectedMissing, setSelectedMissing] = useState<Record<number, number[]>>({});
  const [shareLinkDrafts, setShareLinkDrafts] = useState<Record<number, string>>({});
  const [actionLabel, setActionLabel] = useState("");
  const [openListAutoSync, setOpenListAutoSync] = useState(false);
  const [trackingSchedulerEnabled, setTrackingSchedulerEnabled] = useState(true);
  const [schedulerSaving, setSchedulerSaving] = useState(false);
  const [autoSyncingProviders, setAutoSyncingProviders] = useState<Record<string, boolean>>({});
  const [trackingDirectoryPicker, setTrackingDirectoryPicker] = useState<{ state: TrackingProviderState; title: string } | null>(null);
  const enabledStates = (task: TrackingTask) => task.provider_states.filter((state) => enabledProviders.includes(state.provider));
  const autoSyncKey = (taskId: number, provider: CloudProvider) => `${taskId}:${provider}`;

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
    return () => window.clearInterval(timer);
  }, []);

  async function toggleTask(task: TrackingTask) {
    const states = enabledStates(task);
    const paused = states.every((state) => state.status === "paused");
    await Promise.all(states.map((state) => paused ? api.resumeTracking(state.id) : api.pauseTracking(state.id)));
    await load();
  }

  async function deleteTask(task: TrackingTask) {
    if (!window.confirm(`鍒犻櫎銆?{task.title}銆嶇殑杩芥洿浠诲姟锛焋)) return;
    await Promise.all(task.provider_states.map((state) => api.deleteTracking(state.id)));
    await load();
  }

  async function runTask(task: TrackingTask) {
    setTaskAction(`run:${task.id}`);
    setActionLabel("姝ｅ湪妫€鏌ョ綉鐩樷€?);
    const stageTimer = window.setTimeout(() => setActionLabel("姝ｅ湪閫氳繃 PanSou 鎼滅储璧勬簮鈥?), 1200);
    setActionNotice(null);
    const runningStates = enabledStates(task);
    const syncingKeys = openListAutoSync
      ? runningStates
          .map((state) => state.provider === "qas" ? "p115" : "qas")
          .filter((provider): provider is CloudProvider => enabledProviders.includes(provider as CloudProvider))
          .map((provider) => autoSyncKey(task.id, provider))
      : [];
    if (syncingKeys.length) {
      setAutoSyncingProviders((current) => ({ ...current, ...Object.fromEntries(syncingKeys.map((key) => [key, true])) }));
    }
    try {
      await Promise.all(runningStates.map((state) => api.runTracking(state.id)));
      await load();
      window.dispatchEvent(new CustomEvent("mediaindex:notifications", { detail: { open: true } }));
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "鎵嬪姩杩芥洿鎵ц澶辫触" });
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
        const message = failures.map((failure) => failure.reason instanceof Error ? failure.reason.message : "缃戠洏鐘舵€佽鍙栧け璐?).join("锛?);
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
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "涓よ竟缃戠洏鍚屾澶辫触" });
    } finally {
      setTaskAction("");
      setAutoSyncingProviders((current) => {
        const next = { ...current };
        syncingKeys.forEach((key) => delete next[key]);
        return next;
      });
    }
  }

  async function setTrackingProvider(task: TrackingTask, provider: "qas" | "p115") {
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
      try {
        await api.refreshTrackingStorage(state.id);
        await load();
      } catch (error) {
        setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "缃戠洏鐘舵€佽鍙栧け璐? });
      }
      const result = await api.trackingEpisodes(state.id);
      setTaskEpisodes((current) => ({ ...current, [state.id]: result.episodes }));
    }
  }

  async function fillEpisodes(state: TrackingProviderState) {
    const episodes = selectedMissing[state.id] || [];
    if (!episodes.length) return;
    setTaskAction(`fill:${state.id}`);
    setActionLabel("姝ｅ湪鏍稿缂洪泦鈥?);
    const stageTimer = window.setTimeout(() => setActionLabel("姝ｅ湪閫氳繃 PanSou 鏌ユ壘骞惰浆瀛樷€?), 1200);
    setActionNotice(null);
    try {
      const result = await api.fillTrackingEpisodes(state.id, episodes);
      setSelectedMissing((current) => ({ ...current, [state.id]: [] }));
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.message || (result.ok ? "琛ラ泦澶勭悊瀹屾垚" : "琛ラ泦鏈畬鎴愶紝璇风◢鍚庨噸璇?) });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "琛ラ綈鎵€閫夊け璐? });
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
    setActionLabel("姝ｅ湪鏍稿鍏ㄩ儴缂洪泦鈥?);
    const stageTimer = window.setTimeout(() => setActionLabel("姝ｅ湪閫氳繃 PanSou 鏌ユ壘骞惰浆瀛樼己闆嗏€?), 1200);
    setActionNotice(null);
    try {
      const result = await api.fillTrackingEpisodes(state.id, episodes);
      setSelectedMissing((current) => ({ ...current, [state.id]: [] }));
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.message || (result.ok ? "琛ラ泦澶勭悊瀹屾垚" : "琛ラ泦鏈畬鎴愶紝璇风◢鍚庨噸璇?) });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "琛ラ綈鍏ㄩ儴澶辫触" });
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
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "鍚屾鎵€閫夊け璐? });
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
      setActionNotice({ kind: "success", message: enabled ? "鏅鸿兘杩芥洿鑷姩宸℃宸插紑鍚? : "鏅鸿兘杩芥洿鑷姩宸℃宸插叧闂紝浠嶅彲鎵嬪姩鎵ц" });
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "宸℃寮€鍏充繚瀛樺け璐? });
    } finally {
      setSchedulerSaving(false);
    }
  }

  async function updateTrackingSavePath(state: TrackingProviderState, path: string) {
    setTaskAction(`path:${state.id}`);
    setActionNotice(null);
    try {
      const result = await api.updateTrackingSavePath(state.id, normalizeOpenListPath(path));
      setActionNotice({ kind: result.storage_refreshed ? "success" : "error", message: result.storage_refreshed ? "淇濆瓨璺緞宸叉洿鏂帮紝骞跺凡鍒锋柊宸插瓨闆嗘暟" : result.message });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "杩芥洿淇濆瓨璺緞鏇存柊澶辫触" });
    } finally {
      setTaskAction("");
    }
  }

  async function fillEpisodesFromShare(state: TrackingProviderState) {
    const episodes = selectedMissing[state.id] || [];
    const shareUrl = (shareLinkDrafts[state.id] || "").trim();
    if (!episodes.length || !shareUrl) return;
    setTaskAction(`share:${state.id}`);
    setActionLabel("姝ｅ湪璇诲彇鍒嗕韩閾炬帴骞舵牳瀵规墍閫夐泦鈥?);
    setActionNotice(null);
    try {
      const result = await api.fillTrackingEpisodesFromShare(state.id, episodes, shareUrl);
      setSelectedMissing((current) => ({ ...current, [state.id]: [] }));
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.message || (result.ok ? "宸叉彁浜ゆ墍閫夐泦" : "鍒嗕韩閾炬帴琛ラ綈澶辫触") });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "鍒嗕韩閾炬帴琛ラ綈澶辫触" });
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
      setActionNotice({ kind: result.ok ? "success" : "error", message: result.message || (result.ok ? "宸插悓姝ユ墍鏈夊凡瀛橀泦" : "鍚屾鎵€鏈夊け璐?) });
      await load();
    } catch (error) {
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "鍚屾鎵€鏈夊け璐? });
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
      setActionNotice({ kind: "error", message: error instanceof Error ? error.message : "杩芥洿鏃堕棿淇濆瓨澶辫触" });
    } finally {
      setTaskAction("");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>鏅鸿兘杩芥洿</h1>
          <p>绯荤粺浼氬湪璁惧畾鏃堕棿鏍稿 TMDB 宸叉挱闆嗘暟涓庣綉鐩樺瓨閲忥紝浠呭湪鍙戠幇缂洪泦鏃舵悳绱㈣祫婧愩€?/p>
        </div>
        <div className="tracking-page-actions">
          <label className="tracking-scheduler-switch">
            <span>鑷姩宸℃</span>
            <button type="button" role="switch" aria-checked={trackingSchedulerEnabled} className={trackingSchedulerEnabled ? "active" : ""} disabled={schedulerSaving} onClick={() => void setTrackingScheduler(!trackingSchedulerEnabled)}>
              {schedulerSaving ? <Spinner /> : trackingSchedulerEnabled ? "寮€鍚? : "鍏抽棴"}
            </button>
          </label>
          <button className="ghost" onClick={() => void load()}>
            <ArrowClockwise size={16} />
            鍒锋柊
          </button>
        </div>
      </div>
      {actionNotice && <div className={`tracking-action-notice ${actionNotice.kind}`}>{actionNotice.message}</div>}
      {loading && <div className="list-skeleton" />}
      {!loading && items.length === 0 && <Empty title="杩樻病鏈夎拷鏇翠换鍔? body="杩炶浇鍓ч泦鐐瑰瓨缃戠洏鎴栧瓨鏈湴鍚庯紝浼氳嚜鍔ㄥ嚭鐜板湪杩欓噷銆? />}
      <div className="task-list">
        {items.map((task) => (
          <article className="task-row" key={task.id}>
            <Poster item={taskToMedia(task)} compact />
            <div className="task-main">
              <div className="task-title-line">
                <h3>{task.title}</h3>
                <span className={`status ${enabledStates(task).every((state) => state.status === "paused") ? "paused" : "active"}`}>{enabledStates(task).every((state) => state.status === "paused") ? "宸叉殏鍋? : "杩愯涓?}</span>
              </div>
              <p className="task-overview">{task.overview || "鏆傛棤绠€浠嬨€?}</p>
              <p>{[task.year, mediaTypeLabel(task.category || task.media_type)].filter(Boolean).join(" / ")}</p>
              <p className="tracking-progress-summary">
                <strong>杩涘害锛歋{task.season_number} 鍏?{Math.max(...enabledStates(task).map((state) => state.episode_count), 0)} 闆?/strong>
                <span>
                  {enabledStates(task).map((state) => `${providerLabel(state.provider)}宸茬‘璁?${state.saved_count} 闆哷).join(" / ")}
                </span>
              </p>
              <p>
                {task.next_check_at ? `涓嬫宸℃锛?{formatTrackingTime(task.next_check_at)}` : trackingStateLabel(task.decision_state)}
              </p>
              {task.last_error && task.last_error !== task.storage_check_message && (
                <p className="danger">{task.last_error}</p>
              )}
            </div>
            <div className="row-actions tracking-control-panel">
              <div className="tracking-time-field" title="鎸夋湰鍦版椂鍖鸿缃鍓у彂甯冩棩鐨勮拷鏇存椂闂?>
                <span>杩芥洿鏃堕棿</span>
                <div className="tracking-time-action">
                  <input
                    type="time"
                    value={scheduleDrafts[task.id] ?? task.check_time ?? "10:00"}
                    aria-label={`${task.title}杩芥洿鏃堕棿`}
                    onChange={(event) => setScheduleDrafts((current) => ({ ...current, [task.id]: event.target.value }))}
                    disabled={Boolean(taskAction)}
                  />
                  <button
                    type="button"
                    className="ghost tracking-time-save"
                    aria-label="淇濆瓨杩芥洿鏃堕棿"
                    title="淇濆瓨杩芥洿鏃堕棿"
                    onClick={() => void updateSchedule(task, scheduleDrafts[task.id] ?? task.check_time)}
                    disabled={
                      Boolean(taskAction)
                      || !scheduleDrafts[task.id]
                      || scheduleDrafts[task.id] === task.check_time
                    }
                  >
                    {taskAction === `schedule:${task.id}` ? <Spinner /> : <Check size={16} />}
                  </button>
                </div>
              </div>
              <button className="tracking-control-button" title="鍒锋柊鍚勭綉鐩樺凡瀛樼姸鎬? aria-label="鍒锋柊鍚勭綉鐩樺凡瀛樼姸鎬? onClick={() => void refreshTaskStorage(task)} disabled={Boolean(taskAction)}>
                {taskAction === `refresh:${task.id}` ? <Spinner /> : <ArrowClockwise size={16} />}
                <span>鍒锋柊</span>
              </button>
              <button className="tracking-control-button" title="鍚屾涓よ竟缃戠洏缂哄け闆? aria-label="鍚屾涓よ竟缃戠洏缂哄け闆? onClick={() => void syncTaskStorage(task)} disabled={enabledStates(task).length < 2 || Boolean(taskAction)}>
                {taskAction === `sync:${task.id}` ? <Spinner /> : <ArrowClockwise size={16} />}
                <span>{taskAction === `sync:${task.id}` ? "鍚屾涓? : "鍚屾"}</span>
              </button>
              <button className="tracking-control-button" title="绔嬪嵆鎵ц涓€娆¤拷鏇? aria-label="绔嬪嵆鎵ц涓€娆¤拷鏇? onClick={() => void runTask(task)} disabled={!enabledStates(task).length || enabledStates(task).every((state) => state.status === "paused") || Boolean(taskAction)}>
                {taskAction === `run:${task.id}` ? <Spinner /> : <Play size={16} />}
                <span>{taskAction === `run:${task.id}` ? "鎵ц涓? : "鎵ц"}</span>
              </button>
              <button className="tracking-control-button" title={task.provider_states.every((state) => state.status === "paused") ? "鎭㈠杩芥洿" : "鏆傚仠杩芥洿"} aria-label={task.provider_states.every((state) => state.status === "paused") ? "鎭㈠杩芥洿" : "鏆傚仠杩芥洿"} onClick={() => void toggleTask(task)}>
                {task.provider_states.every((state) => state.status === "paused") ? <Play size={16} /> : <Pause size={16} />}
                <span>{task.provider_states.every((state) => state.status === "paused") ? "鎭㈠" : "鏆傚仠"}</span>
              </button>
              <button className="tracking-control-button danger-control" title="鍒犻櫎杩芥洿" aria-label="鍒犻櫎杩芥洿" onClick={() => void deleteTask(task)}>
                <Trash size={16} />
                <span>鍒犻櫎</span>
              </button>
              <div className="tracking-provider-storage-list" aria-label="杩芥洿缃戠洏">
              {enabledProviders.map((provider) => {
                const state = task.provider_states.find((entry) => entry.provider === provider);
                const autoSyncing = Boolean(autoSyncingProviders[autoSyncKey(task.id, provider)] || state?.storage_syncing);
                const reverseOpenListSyncUnavailable = provider === "qas";
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
                      {providerLabel(provider)}{autoSyncing ? "鍚屾涓? : state ? "杩芥洿涓? : "鏈惎鐢?}
                    </button>
                    {state && <div className="tracking-provider-path" title={state.save_path}>
                      <span>{state.save_path}</span>
                      <button type="button" className="icon tracking-path-picker" title={`閫夋嫨${providerLabel(provider)}杩芥洿淇濆瓨璺緞`} aria-label={`閫夋嫨${providerLabel(provider)}杩芥洿淇濆瓨璺緞`} disabled={Boolean(taskAction)} onClick={() => setTrackingDirectoryPicker({ state, title: `${providerLabel(provider)}杩芥洿淇濆瓨璺緞` })}>
                        {taskAction === `path:${state.id}` ? <Spinner /> : <FolderOpen size={16} />}
                      </button>
                    </div>}
                  </div>
                  {state ? <>
                  <div className={`tracking-storage-dropdown ${expandedTask === state.id ? "open" : ""}`}>
                    <button type="button" className="season-storage-toggle" onClick={() => void toggleEpisodePanel(state)} aria-expanded={expandedTask === state.id}>
                      <span>
                        {autoSyncing ? `${providerLabel(state.provider)} 路 鍚屾涓璥 : `${providerLabel(state.provider)} 路 S${task.season_number} 宸插瓨 ${state.saved_count} 闆哷}
                        {!autoSyncing && Boolean(state.last_saved_episode) && ` 路 鑷?E${state.last_saved_episode}`}
                      </span>
                      {autoSyncing ? <Spinner /> : <CaretDown size={14} />}
                    </button>
                  </div>
                  {expandedTask === state.id && (
                  <div className="missing-episode-panel tracking-provider-menu">
                    <p className="manual-fill-hint">
                      <WarningCircle size={16} weight="fill" />
                      鐢变簬 PanSou 浠ヨ繎鏈熻祫婧愪负涓伙紝鍙戝竷鏃堕棿杈冩棭鐨勮祫婧愬彲鑳芥棤娉曟壘鍒般€?
                    </p>
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
                        aria-label={`${providerLabel(state.provider)}鎵嬪姩鍒嗕韩閾炬帴`}
                        value={shareLinkDrafts[state.id] || ""}
                        placeholder="绮樿创澶稿厠鎴?115 鍒嗕韩閾炬帴"
                        onChange={(event) => setShareLinkDrafts((current) => ({ ...current, [state.id]: event.target.value }))}
                        disabled={Boolean(taskAction)}
                      />
                      <button type="button" className="secondary compact-action" disabled={!(selectedMissing[state.id] || []).length || !(shareLinkDrafts[state.id] || "").trim() || Boolean(taskAction)} onClick={() => void fillEpisodesFromShare(state)}>
                        {taskAction === `share:${state.id}` ? <Spinner /> : <CloudArrowDown size={15} />} {taskAction === `share:${state.id}` ? "澶勭悊涓? : "閾炬帴琛ラ綈鎵€閫?}
                      </button>
                    </div>
                    <div className="missing-episode-actions">
                      <button type="button" className="ghost compact-action" title={reverseOpenListSyncUnavailable ? "鏆備笉鏀寔浠?115 澶嶅埗鍒板じ鍏? : "鍚屾鎵€閫夐泦鍒板綋鍓嶇綉鐩?} disabled={reverseOpenListSyncUnavailable || !(selectedMissing[state.id] || []).length || Boolean(taskAction)} onClick={() => void syncSelectedEpisodes(state)}>
                        {taskAction === `sync-selected:${state.id}` ? <Spinner /> : <ArrowClockwise size={15} />} {taskAction === `sync-selected:${state.id}` ? "鍚屾涓? : "鍚屾鎵€閫?}
                      </button>
                      <button type="button" className="ghost compact-action" title={reverseOpenListSyncUnavailable ? "鏆備笉鏀寔浠?115 澶嶅埗鍒板じ鍏? : "鍚屾鍏ㄩ儴缂哄け闆嗗埌褰撳墠缃戠洏"} disabled={reverseOpenListSyncUnavailable || enabledStates(task).length < 2 || Boolean(taskAction)} onClick={() => void syncAllEpisodes(state)}>
                        {taskAction === `sync-all:${state.id}` ? <Spinner /> : <ArrowClockwise size={15} />} {taskAction === `sync-all:${state.id}` ? "鍚屾涓? : "鍚屾鎵€鏈?}
                      </button>
                      <button type="button" className="primary compact-action" disabled={!(selectedMissing[state.id] || []).length || Boolean(taskAction)} onClick={() => void fillEpisodes(state)}>
                        {taskAction === `fill:${state.id}` ? <Spinner /> : <Play size={15} />} {taskAction === `fill:${state.id}` ? "澶勭悊涓? : "琛ラ綈鎵€閫?}
                      </button>
                      <button type="button" className="ghost compact-action" disabled={!(taskEpisodes[state.id] || []).some((episode) => episode.status !== "saved" && episode.aired) || Boolean(taskAction)} onClick={() => void fillAllEpisodes(state)}>
                        {taskAction === `fill:${state.id}` ? "澶勭悊涓? : "琛ラ綈鎵€鏈?}
                      </button>
                    </div>
                  </div>
                )}
                  </> : <div className="tracking-provider-empty">鏈惎鐢紝鐐瑰嚮宸︿晶鎸夐挳寮€鍚?/div>}
                </div>
                );
              })}
              </div>
            </div>
          </article>
        ))}
      </div>
      {trackingDirectoryPicker && (
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

function resourceKey(provider: "qas" | "p115", seasonNumber: number) {
  return `${provider}:${seasonNumber}`;
}

function canSmartTrackMedia(item: Pick<MediaItem, "media_type" | "category">, fallbackType = "") {
  const type = item.category || (fallbackType === "movie" ? "" : fallbackType) || item.media_type;
  return type === "tv" || type === "variety" || type === "anime" || type === "documentary";
}

function providerLabel(provider: "qas" | "p115") {
  return provider === "p115" ? "115" : "澶稿厠";
}

function providerShortLabel(provider: "qas" | "p115") {
  return provider === "p115" ? "115" : "澶稿厠";
}

function transferStageLabel(stage: string) {
  const labels: Record<string, string> = {
    tmdb_resolving: "姝ｅ湪鍖归厤 TMDB",
    validating_link: "姝ｅ湪妫€鏌ユ棫閾炬帴",
    searching_sources: "姝ｅ湪閫氳繃 PanSou 鎼滅储璧勬簮",
    matching_files: "姝ｅ湪鍖归厤鏂囦欢",
    preparing_names: "姝ｅ湪鐢熸垚鏂囦欢鍚?,
    qas_transferring: "姝ｅ湪鎵ц杞瓨",
    provider_submitting: "姝ｅ湪鎵ц杞瓨",
    openlist_sync: "姝ｅ湪鍚屾 OpenList",
    openlist_sync_done: "OpenList 鍚屾瀹屾垚",
    openlist_sync_failed: "OpenList 鍚屾澶辫触",
    stopped: "浠诲姟宸茬粓姝?,
  };
  return labels[stage] || "姝ｅ湪澶勭悊";
}

function transferJobTitle(job: TransferJob) {
  if (job.provider === "openlist") return job.display_title || "OpenList 濯掍綋搴撳悓姝?;
  const provider = job.provider === "qas" ? "澶稿厠" : job.provider === "p115" ? "115" : job.provider === "moviepilot_115" ? "MoviePilot 115" : "鏈湴";
  const action = job.target === "local" ? "鏈湴淇濆瓨" : "缃戠洏杞瓨";
  return job.display_title ? `${provider} ${action} 路 ${job.display_title}` : `${provider} ${action}`;
}

function transferJobStatus(job: TransferJob) {
  if (job.status === "stopped") return "宸茬敱鐢ㄦ埛缁堟";
  if (job.status === "done" || job.status === "triggered") return `${transferStageLabel(job.stage)}锛?{job.message || "宸插畬鎴?}`;
  if (job.status === "failed") return `鎵ц澶辫触锛?{job.message || "璇锋煡鐪嬩换鍔¤鎯?}`;
  if (job.status === "needs_review") return `绛夊緟纭锛?{job.message || "闇€瑕侀€夋嫨璧勬簮"}`;
  return `${transferStageLabel(job.stage)}锛?{job.message || "澶勭悊涓?}`;
}

function formatTrackingTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function wishlistStateLabel(state: string) {
  const labels: Record<string, string> = {
    pending: "绛夊緟 TMDB 鏃ユ湡",
    checking: "姝ｅ湪妫€鏌?,
    retry_wait: "绛夊緟涓嬫妫€鏌?,
    needs_review: "宸查€氱煡纭",
    triggered: "QAS 宸茶Е鍙?,
    completed: "宸插畬鎴?,
  };
  return labels[state] || state;
}

function trackingStateLabel(state?: string) {
  const labels: Record<string, string> = {
    idle: "TMDB 鏆傛棤涓嬩竴闆嗘挱鍑烘棩鏈?,
    pending: "绛夊緟棣栨宸℃",
    retry_wait: "绛夊緟涓嬫鎹㈡簮閲嶈瘯",
    needs_review: "闇€瑕佷汉宸ョ‘璁?,
    awaiting_confirmation: "QAS 宸茶Е鍙戯紝绛夊緟缁撴灉纭",
    paused: "浠诲姟宸叉殏鍋?,
  };
  return labels[state || ""] || "鏆傛棤涓嬩竴娆″贰妫€鏃堕棿";
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
  const enabledCloudTypes: ("quark" | "115")[] = enabledProviders.map((provider) => provider === "qas" ? "quark" : "115");
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
            ? "宸叉彁浜ょ粰 MoviePilot锛涘悗缁浆瀛樸€佹暣鐞嗗拰 STRM 鐢?MoviePilot 澶勭悊銆?
            : "鎵€閫夎祫婧愬凡瀹屾垚鍖归厤銆佹敼鍚嶅苟鎻愪氦杞瓨銆?
          : job.message || "鎵€閫夋枃浠朵粛鏃犳硶瀹夊叏鍖归厤锛岃鏇存崲鏂囦欢鎴栭噸鏂版悳绱€?,
      );
      await load();
    } catch {
      setMessage("鎻愪氦澶辫触锛岃绋嶅悗閲嶈瘯銆?);
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
      setMessage(result.ok ? "宸叉壘鍒板彲鎵ц璧勬簮銆? : result.message || "宸查噸鏂版悳绱紝鏆傛椂浠嶆病鏈夊畨鍏ㄥ€欓€夈€? );
      await load();
    } catch {
      setMessage("閲嶆柊鎼滅储澶辫触锛岃绋嶅悗閲嶈瘯銆?);
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
      setMessage("鍒犻櫎澶辫触锛岃绋嶅悗閲嶈瘯銆?);
    } finally {
      setBusy(null);
      setBusyAction(null);
    }
  }

  if (loading) return <div className="list-skeleton" />;
  if (!items.length) return (
    <section>
      {message && <div className="notice">{message}</div>}
      <Empty title="鏆傛棤寰呯‘璁? body="绯荤粺浼氳嚜鍔ㄥ鐞嗙粷澶у鏁颁换鍔★紱鍙湁鏃犳硶瀹夊叏鍒ゆ柇鏃舵墠鍦ㄨ繖閲屾彁閱掍綘銆? />
    </section>
  );
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>寰呯‘璁?/h1>
          <p>澶稿厠鍊欓€夌敱 QAS 鎵ц锛?15 鍊欓€夌敱 MediaIndex 鍘熺敓楠岃瘉銆佹敼鍚嶅苟杞瓨銆備袱涓綉鐩樼殑纭缁撴灉浜掍笉褰卞搷銆?/p>
        </div>
      </div>
      <div className="segmented review-provider-filter" role="group" aria-label="鍊欓€夌綉鐩樼瓫閫?>
        {([ ["all", "鍏ㄩ儴"], ["quark", "澶稿厠"], ["115", "115"] ] as const)
          .filter(([key]) => key === "all" || enabledCloudTypes.includes(key))
          .map(([key, label]) => (
          <button key={key} className={cloudFilter === key ? "active" : ""} onClick={() => setCloudFilter(key)}>
            {label}
          </button>
        ))}
      </div>
      {message && <div className="notice">{message}</div>}
      <div className="review-list">
        {visibleItems.length === 0 && <Empty title="褰撳墠绛涢€変笅娌℃湁鍊欓€? body="鍙互鍒囨崲鍒板叾浠栫綉鐩樼被鍨嬫煡鐪嬨€? />}
        {visibleItems.map((item) => (
          <article className="review-card" key={item.id}>
            <header className="review-card-head">
              <div>
                <span className={`review-kicker provider-badge ${item.cloud_type || "unknown"}`}>
                  {item.cloud_type === "115" ? "115 鍊欓€? : "澶稿厠鍊欓€?}
                </span>
                <h2>{item.source_title || "鏈懡鍚嶅€欓€?}</h2>
                <p>{[item.search_query, item.source, item.season_number ? `S${item.season_number}` : ""].filter(Boolean).join(" / ")}</p>
              </div>
              <span className="review-score">鍖归厤鍒?{Math.round(item.score)}</span>
            </header>

            <div className="review-link-row">
              <div>
                <strong>{item.cloud_type === "115" ? "115 鍒嗕韩" : "澶稿厠鍒嗕韩"}</strong>
                <span>{item.share_url}</span>
              </div>
              <a className="secondary review-open-link" href={item.share_url} target="_blank" rel="noreferrer">
                <ArrowSquareOut size={17} />
                鎵撳紑鏌ョ湅
              </a>
            </div>

            <div className="review-evidence">
              {(item.reasons.length ? item.reasons : [item.job_message || "鏂囦欢鍚嶄笌 TMDB 淇℃伅鏃犳硶褰㈡垚鍞竴鍖归厤"]).map((reason) => (
                <span key={reason}>{reviewReasonLabel(reason)}</span>
              ))}
            </div>

            {item.files?.length > 0 && (
              <fieldset className="review-files">
                <legend>閫夋嫨瑕佽浆瀛樼殑鏂囦欢</legend>
                <p>涓嶉€夋嫨鏃剁敱鍚庡彴缁х画鑷姩鍒ゆ柇锛涢€夋嫨鍚庡彧鍦ㄨ繖浜涙枃浠朵腑鍖归厤鍜屾敼鍚嶃€?/p>
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

            {item.review_state === "notification_failed" && <p className="danger">寰呯‘璁ら€氱煡鏈彂閫佹垚鍔燂紝璇锋鏌ュ閮ㄩ€氱煡閰嶇疆銆?/p>}
            {item.provider === "p115" && item.job_provider === "p115" && <p className="muted">纭鍚庣敱 MediaIndex 鍘熺敓璇诲彇 115 鍒嗕韩骞跺畬鎴愮瓫閫夈€佹敼鍚嶃€佽浆瀛樺拰鐩爣鐩綍鏍稿銆?/p>}
            {item.provider === "moviepilot_115" && item.job_provider === "moviepilot_115" && <p className="muted">纭鍚庝細鎶婃鍒嗕韩閾炬帴鎻愪氦缁?MoviePilot锛汳ediaIndex 涓嶄細鐩存帴鎿嶄綔 115銆?/p>}
            {item.provider !== item.job_provider && <p className="muted">姝ゅ€欓€変笌鍘熶换鍔＄綉鐩樹笉涓€鑷达紝璇锋寜鐩爣缃戠洏閲嶆柊鍒涘缓浠诲姟銆?/p>}
            <footer className="review-actions">
              <button className="primary review-confirm" onClick={() => void confirm(item)} disabled={busy !== null || item.provider !== item.job_provider}>
                {busy === item.id && busyAction === "confirm" ? <Spinner /> : <CheckCircle size={17} />}
                <span>
                  {busy === item.id && busyAction === "confirm"
                    ? transferStageLabel(progressStage)
                    : item.provider === "moviepilot_115"
                      ? "鎻愪氦缁?MoviePilot"
                      : (selectedFiles[item.id]?.length || 0) > 0
                      ? `杞瓨鎵€閫夋枃浠?(${selectedFiles[item.id].length})`
                      : "浣跨敤姝よ祫婧?}
                </span>
              </button>
              <button className="ghost" onClick={() => void research(item)} disabled={busy !== null}>
                {busy === item.id && busyAction === "research" ? <Spinner /> : <ArrowClockwise size={17} />}
                PanSou 閲嶆柊鎼滅储
              </button>
              <button className="ghost danger-action" onClick={() => void dismiss(item)} disabled={busy !== null}>
                {busy === item.id && busyAction === "delete" ? <Spinner /> : <Trash size={17} />}
                鍒犻櫎
              </button>
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}

function ActivityCenter() {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<TransferJob[]>([]);
  const [stopping, setStopping] = useState(false);
  const [stoppingJobId, setStoppingJobId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const root = useRef<HTMLDivElement>(null);

  async function load() {
    const next = await api.transfers().catch(() => []);
    setJobs(next.slice(0, 30));
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 8_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    function refreshTasks() { void load(); }
    window.addEventListener("mediaindex:tasks-changed", refreshTasks);
    return () => window.removeEventListener("mediaindex:tasks-changed", refreshTasks);
  }, []);

  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, []);

  async function stopAll() {
    setStopping(true);
    setMessage("");
    try {
      const result = await api.stopActiveTransfers();
      setMessage(result.stopped ? `宸插仠姝?${result.stopped} 涓换鍔 : "褰撳墠娌℃湁鍙仠姝㈢殑浠诲姟");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "鍋滄浠诲姟澶辫触");
    } finally {
      setStopping(false);
    }
  }

  async function stopJob(job: TransferJob) {
    setStoppingJobId(job.id);
    setMessage("");
    try {
      const result = await api.stopTransfer(job.id);
      setMessage(result.message);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "缁堟浠诲姟澶辫触");
    } finally {
      setStoppingJobId(null);
    }
  }

  const activeCount = jobs.filter((job) => ["running", "triggered"].includes(job.status)).length;
  return (
    <div className="notification-center activity-center" ref={root}>
      <button className="icon notification-trigger" onClick={() => setOpen((value) => !value)} title="鎵ц浠诲姟" aria-label={`鎵ц浠诲姟${activeCount ? `锛?{activeCount} 涓繘琛屼腑` : ""}`} aria-expanded={open}>
        <TerminalWindow size={18} />
        {activeCount > 0 && <span className="notification-badge">{activeCount > 99 ? "99+" : activeCount}</span>}
      </button>
      {open && (
        <section className="notification-panel activity-panel" aria-label="MediaIndex 鎵ц浠诲姟">
          <header className="notification-head">
            <div><strong>鎵ц浠诲姟</strong><span>{activeCount ? `${activeCount} 涓繘琛屼腑` : "褰撳墠娌℃湁杩涜涓殑浠诲姟"}</span></div>
            <div className="notification-tools">
              <button onClick={() => void load()} title="鍒锋柊浠诲姟" aria-label="鍒锋柊浠诲姟"><ArrowClockwise size={16} /></button>
              <button onClick={() => void stopAll()} title="鍏ㄩ儴鍋滄" aria-label="鍏ㄩ儴鍋滄" disabled={!activeCount || stopping}>{stopping ? <Spinner /> : <Pause size={16} />}</button>
            </div>
          </header>
          {message && <div className="activity-message">{message}</div>}
          <div className="notification-list">
            {jobs.length === 0 ? (
              <div className="notification-state"><TerminalWindow size={24} /><strong>鏆傛棤浠诲姟璁板綍</strong><span>MediaIndex 寮€濮嬫墽琛屽悗浼氭樉绀哄湪杩欓噷</span></div>
            ) : jobs.map((job) => {
              const running = ["running", "triggered"].includes(job.status);
              return (
              <div className={`activity-item ${job.status}`} key={job.id}>
                <span className={`notification-type info ${running ? "running" : ""}`}>{running ? <Spinner /> : <TerminalWindow size={17} />}</span>
                <span className="notification-copy">
                  <strong>#{job.id} {transferJobTitle(job)}{job.season_number ? ` 路 S${job.season_number}` : ""}</strong>
                  <span>{transferJobStatus(job)}</span>
                  <time>{job.save_path || "鏈寚瀹氱洰鏍囩洰褰?}</time>
                </span>
                {running && (
                  <button className="icon activity-stop-button" onClick={() => void stopJob(job)} title="缁堟浠诲姟" aria-label={`缁堟浠诲姟 #${job.id}`} disabled={stoppingJobId === job.id}>
                    {stoppingJobId === job.id ? <Spinner /> : <Pause size={16} />}
                  </button>
                )}
              </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function NotificationCenter({ onNavigate }: { onNavigate: (page: Page) => void }) {
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
      setError("閫氱煡鏆傛椂鏃犳硶鍔犺浇");
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
    if (isPage(item.action_page)) {
      onNavigate(item.action_page);
      setOpen(false);
    }
  }

  async function readAll() {
    await api.markNotificationRead();
    setFeed((current) => ({ items: current.items.map((item) => ({ ...item, is_read: 1 })), unread_count: 0 }));
  }

  async function clearAll() {
    if (!window.confirm("娓呯┖褰撳墠閫氱煡鍒楄〃锛熷凡娓呯┖鐨勯€氱煡涓嶄細鍐嶆鏄剧ず銆?)) return;
    await api.clearNotifications();
    setFeed({ items: [], unread_count: 0 });
  }

  return (
    <div className="notification-center" ref={root}>
      <button
        className="icon notification-trigger"
        onClick={() => setOpen((value) => !value)}
        title="閫氱煡"
        aria-label={`閫氱煡${feed.unread_count ? `锛?{feed.unread_count} 鏉℃湭璇籤 : ""}`}
        aria-expanded={open}
      >
        <Bell size={18} weight={feed.unread_count ? "fill" : "regular"} />
        {feed.unread_count > 0 && <span className="notification-badge">{feed.unread_count > 99 ? "99+" : feed.unread_count}</span>}
      </button>
      {open && (
        <section className="notification-panel" aria-label="閫氱煡涓績">
          <header className="notification-head">
            <div>
              <strong>閫氱煡</strong>
              <span>{feed.unread_count ? `${feed.unread_count} 鏉℃湭璇籤 : "鍏ㄩ儴宸茶"}</span>
            </div>
            <div className="notification-tools">
              <button onClick={() => void readAll()} disabled={!feed.unread_count} title="鍏ㄩ儴鏍囦负宸茶" aria-label="鍏ㄩ儴鏍囦负宸茶">
                <Checks size={17} />
              </button>
              <button onClick={() => void clearAll()} disabled={!feed.items.length} title="娓呯┖閫氱煡" aria-label="娓呯┖閫氱煡">
                <Trash size={16} />
              </button>
            </div>
          </header>
          <div className="notification-filter" role="group" aria-label="閫氱煡绛涢€?>
            <button className={!unreadOnly ? "active" : ""} onClick={() => setUnreadOnly(false)}>鍏ㄩ儴</button>
            <button className={unreadOnly ? "active" : ""} onClick={() => setUnreadOnly(true)}>鏈</button>
          </div>
          <div className="notification-list">
            {loading ? (
              <NotificationSkeleton />
            ) : error ? (
              <div className="notification-state error-state">
                <XCircle size={22} />
                <span>{error}</span>
                <button onClick={() => void load()}>閲嶈瘯</button>
              </div>
            ) : feed.items.length === 0 ? (
              <div className="notification-state">
                <Bell size={24} />
                <strong>{unreadOnly ? "娌℃湁鏈閫氱煡" : "鏆傛椂娌℃湁閫氱煡"}</strong>
                <span>浠诲姟鏈夋柊杩涘睍鏃朵細鏄剧ず鍦ㄨ繖閲?/span>
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
                  {!item.is_read && <span className="unread-marker" aria-label="鏈" />}
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
    <div className="notification-skeleton" aria-label="姝ｅ湪鍔犺浇閫氱煡">
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

function isPage(value: string): value is Page {
  return ["discover", "tracking", "wishlist", "review", "settings"].includes(value);
}

function formatNotificationTime(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const timestamp = new Date(normalized).getTime();
  if (!Number.isFinite(timestamp)) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "鍒氬垰";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 鍒嗛挓鍓峘;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} 灏忔椂鍓峘;
  if (seconds < 604_800) return `${Math.floor(seconds / 86_400)} 澶╁墠`;
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(timestamp));
}

function reviewReasonLabel(reason: string) {
  if (reason.startsWith("episode_coverage:")) return `闆嗘暟瑕嗙洊 ${reason.split(":")[1]}`;
  const labels: Record<string, string> = {
    title_exact_or_contained: "鏍囬鍖归厤",
    title_partial: "鏍囬閮ㄥ垎鍖归厤",
    season_exact: "瀛ｆ暟鍖归厤",
    year_match: "骞翠唤鍖归厤",
    target_episode_evidence: "鍙戠幇鐩爣闆嗚瘉鎹?,
    derivative_content: "鍙兘鍖呭惈琛嶇敓鍐呭",
    update_lags_target: "璧勬簮灏氭湭鏇存柊鍒扮洰鏍囬泦",
    multiple_close_candidates: "瀛樺湪澶氫釜鐩歌繎鏂囦欢",
    provider_execution_unavailable: "褰撳墠鎵ц鍣ㄥ皻鏈紑鏀?,
    external_organize_requires_confirmation: "闇€纭鍚庢彁浜ょ粰澶栭儴鏁寸悊鍣?,
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
  if (mediaType === "movie") return "鐢靛奖";
  if (mediaType === "variety") return "缁艰壓";
  if (mediaType === "concert") return "婕斿敱浼?;
  if (mediaType === "documentary") return "绾綍鐗?;
  if (mediaType === "anime") return "鍔ㄦ极";
  return "鐢佃鍓?;
}

type PushProvider = "telegram" | "wecom" | "wecom_app";

function SettingsHub() {
  const [tab, setTab] = useState<SettingsTab>(() => {
    if (["#push", "#settings-notifications"].includes(window.location.hash)) return "notifications";
    if (window.location.hash === "#settings-network") return "network";
    if (window.location.hash === "#settings-drives") return "drives";
    if (window.location.hash === "#settings-wishlist") return "wishlist";
    if (window.location.hash === "#settings-openlist") return "openlist";
    return "basic";
  });

  function selectTab(next: SettingsTab) {
    setTab(next);
    const hashes: Record<SettingsTab, string> = {
      basic: "#settings",
      drives: "#settings-drives",
      network: "#settings-network",
      wishlist: "#settings-wishlist",
      openlist: "#settings-openlist",
      notifications: "#settings-notifications",
    };
    window.history.replaceState(null, "", hashes[next]);
  }

  const formId = tab === "notifications" ? "notification-settings-form" : `${tab}-settings-form`;

  return (
    <section className="settings-hub">
      <div className="settings-toolbar">
        <div className="settings-subnav" role="tablist" aria-label="璁剧疆椤甸潰">
          {([
            ["basic", "鍩虹璁剧疆"],
            ["drives", "缃戠洏璁剧疆"],
            ["openlist", "OpenList 鍚屾"],
            ["notifications", "閫氱煡鍜屼氦浜?],
            ["wishlist", "宸℃"],
            ["network", "缃戠粶浠ｇ悊"],
          ] as const).map(([value, label]) => (
            <button type="button" role="tab" aria-selected={tab === value} className={tab === value ? "active" : ""} onClick={() => selectTab(value)} key={value}>
              {label}
            </button>
          ))}
        </div>
        {<button type="submit" className="primary settings-hub-save" form={formId}>
          淇濆瓨璁剧疆
        </button>
      </div>
      {tab === "notifications" ? <PushSettingsPage /> : <SettingsPage section={tab} />}
    </section>
  );
}

function PushSettingsPage() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
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
    api.config().then(setConfig).catch(() => setMessage("閫氱煡閰嶇疆鍔犺浇澶辫触"));
  }, []);

  function update(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggleValue(key: string, saved: boolean) {
    return form[key] === undefined ? saved : form[key] === "true";
  }

  function directDownloadProvider(): "qas" | "p115" {
    const value = form.direct_download_provider || config?.direct_download_provider || "qas";
    return value === "p115" ? "p115" : "qas";
  }

  function providerRoot(provider: "qas" | "p115") {
    return normalizeOpenListPath(provider === "p115" ? config?.p115_root_path || "/" : config?.qas_root || config?.cloud_root || "/");
  }

  function pickDirectDownloadPath() {
    const provider = directDownloadProvider();
    const saved = form.direct_download_save_path || config?.direct_download_save_path || providerRoot(provider);
    setProviderDirectoryPicker({
      provider,
      label: `${provider === "p115" ? "115" : "澶稿厠"}榛樿淇濆瓨璺緞`,
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
      setMessage("閫氱煡閰嶇疆宸蹭繚瀛?);
    } catch {
      setMessage("淇濆瓨澶辫触锛岃妫€鏌ュ湴鍧€銆丄gentId 鍜屽繀濉」");
    } finally {
      setSaving(false);
    }
  }

  async function testNotificationChannel(provider: PushProvider) {
    setTestingChannel(provider);
    setChannelResults((current) => ({ ...current, [provider]: { ok: true, message: "姝ｅ湪鍙戦€佹祴璇曟秷鎭€? } }));
    try {
      const result = await api.testNotificationChannel(provider);
      setChannelResults((current) => ({ ...current, [provider]: { ok: true, message: result.message } }));
    } catch (error) {
      const detail = error instanceof ApiError ? error.message : "鍙戦€佸け璐ワ紝璇峰厛淇濆瓨閰嶇疆骞舵鏌ュ嚟鎹拰鎺ユ敹鑼冨洿";
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
      window.prompt("澶嶅埗浼佷笟寰俊鍥炶皟 URL", callbackUrl);
    }
  }

  return (
    <section>
      <div className="page-head push-page-head">
        <div>
          <h1>閫氱煡璁剧疆</h1>
          <p>閰嶇疆浼佷笟寰俊銆乀elegram銆佹秷鎭洖璋冨拰鎵嬫満绔氦浜掋€傚瘑閽ュ彧淇濆瓨鍦ㄦ湇鍔＄銆?/p>
        </div>
        <PaperPlaneTilt size={32} aria-hidden />
      </div>
      {!config && <div className="list-skeleton" />}
      {config && (
        <form id="notification-settings-form" className="settings-form push-settings-form" onSubmit={save}>
          <SettingsSection title="鎺ㄩ€佹€诲紑鍏? body="鍚敤鍚庯紝鏂颁骇鐢熺殑杞瓨缁撴灉鍜屽緟澶勭悊浜嬮」浼氬彂閫佸埌涓嬫柟宸插惎鐢ㄧ殑娓犻亾銆?>
            <SettingsToggle
              label="澶栭儴娑堟伅鎺ㄩ€?
              value={toggleValue("notification_external_enabled", config.notification_external_enabled)}
              onChange={(value) => update("notification_external_enabled", String(value))}
              trueLabel="鍚敤"
              falseLabel="鍏抽棴"
            />
            <div className="push-event-list" aria-label="鎺ㄩ€佷簨浠?>
              <span><CheckCircle size={17} />杞瓨瀹屾垚</span>
              <span><WarningCircle size={17} />闇€瑕佺‘璁?/span>
              <span><Info size={17} />鏆傛棤璧勬簮</span>
              <span><XCircle size={17} />澶勭悊澶辫触</span>
            </div>
            <SettingsInput
              label="鍏綉璁块棶鍦板潃"
              name="public_base_url"
              saved={Boolean(config.public_base_url)}
              value={form.public_base_url || ""}
              onChange={update}
              placeholder={config.public_base_url || window.location.origin}
              showSavedValue
            />
            <p className="channel-help">鐢ㄤ簬閫氱煡璺宠浆銆佷紒涓氬井淇″洖璋冨拰缂撳瓨娴锋姤璁块棶銆傝濉啓鎵嬫満鍙互璁块棶鐨?MediaIndex 鍦板潃锛屼笉瑕佸甫椤甸潰璺緞銆?/p>
          </SettingsSection>

          <div className="notification-channel-tabs" role="tablist" aria-label="閫氱煡娓犻亾">
            {([
              ["wecom_app", "浼佷笟寰俊"],
              ["wecom_bot", "浼佸井鏈哄櫒浜?],
              ["telegram", "Telegram"],
            ] as const).map(([value, label]) => (
              <button type="button" role="tab" aria-selected={notificationChannel === value} className={notificationChannel === value ? "active" : ""} onClick={() => setNotificationChannel(value)} key={value}>
                {label}
              </button>
            ))}
          </div>

          {notificationChannel === "wecom_app" && (
          <SettingsSection title="浼佷笟寰俊" body="閫氳繃鑷缓搴旂敤瀹氬悜鍙戦€佹秷鎭紝骞跺彲鍚敤鎴愬憳浜や簰鎸囦护銆?>
            <div className="notification-channel-card primary-channel">
              <div className="channel-heading">
                <div>
                  <strong>鑷缓搴旂敤</strong>
                  <span>閫氳繃浼佷笟寰俊搴旂敤娑堟伅鎺ュ彛鍙戦€侊紝鍙帶鍒舵帴鏀惰寖鍥淬€?/span>
                </div>
                <span className="recommended-label">鎺ㄨ崘</span>
              </div>
              <SettingsToggle
                label="鍚敤鑷缓搴旂敤"
                value={toggleValue("wecom_app_enabled", config.wecom_app_enabled)}
                onChange={(value) => update("wecom_app_enabled", String(value))}
                trueLabel="鍚敤"
                falseLabel="鍏抽棴"
              />
              <SettingsInput label="浼佷笟 ID (CorpId)" name="wecom_corp_id" saved={Boolean(config.wecom_corp_id)} value={form.wecom_corp_id || ""} onChange={update} placeholder={config.wecom_corp_id || "wwxxxxxxxxxxxxxxxx"} showSavedValue />
              <SettingsInput label="搴旂敤 Secret" name="wecom_app_secret" saved={config.has_wecom_app_secret} value={form.wecom_app_secret || ""} onChange={update} secret />
              <SettingsNumberInput
                label="AgentId"
                name="wecom_app_agent_id"
                value={form.wecom_app_agent_id || ""}
                placeholder={config.wecom_app_agent_id > 0 ? String(config.wecom_app_agent_id) : "1000002"}
                min={1}
                max={2147483647}
                onChange={update}
              />
              <SettingsInput label="鎺ユ敹鎴愬憳" name="wecom_app_to_user" saved={Boolean(config.wecom_app_to_user)} value={form.wecom_app_to_user ?? ""} onChange={update} placeholder={config.wecom_app_to_user || "@all"} showSavedValue />
              <SettingsInput label="鎺ユ敹閮ㄩ棬" name="wecom_app_to_party" saved={Boolean(config.wecom_app_to_party)} value={form.wecom_app_to_party ?? ""} onChange={update} placeholder={config.wecom_app_to_party || "1|2"} showSavedValue />
              <SettingsInput label="鎺ユ敹鏍囩" name="wecom_app_to_tag" saved={Boolean(config.wecom_app_to_tag)} value={form.wecom_app_to_tag ?? ""} onChange={update} placeholder={config.wecom_app_to_tag || "1|2"} showSavedValue />
              <SettingsInput
                label="寰俊娑堟伅浠ｇ悊鍦板潃"
                help="浠呯敤浜庝唬鐞?MediaIndex 鍚戜紒涓氬井淇″彂閫佸簲鐢ㄦ秷鎭紱鏈娇鐢ㄤ唬鐞嗘椂濉啓 https://qyapi.weixin.qq.com锛屼笉鏄紒涓氬井淇″悗鍙板洖璋冨湴鍧€銆?
                name="wecom_origin"
                saved
                value={form.wecom_origin || ""}
                onChange={update}
                placeholder={config.wecom_origin || "https://qyapi.weixin.qq.com"}
                showSavedValue
                action={(
                  <button type="button" className="primary compact-action" onClick={() => void testNotificationChannel("wecom_app")} disabled={testingChannel !== null}>
                    {testingChannel === "wecom_app" && <Spinner />}
                    娴嬭瘯鑷缓搴旂敤
                  </button>
                )}
                result={channelResults.wecom_app}
              />
              <p className="channel-help">澶氫釜鎴愬憳銆侀儴闂ㄦ垨鏍囩鐢ㄧ珫绾垮垎闅斻€傛帴鏀舵垚鍛樺～鍐?@all 鏃讹紝鍙戦€佺粰搴旂敤鍙鑼冨洿鍐呯殑鍏ㄩ儴鎴愬憳銆?/p>
            </div>

            <div className="notification-channel-card">
              <div className="channel-heading">
                <div>
                  <strong>浜や簰鎸囦护鍥炶皟</strong>
                  <span>鎺ユ敹浼佷笟寰俊鎴愬憳鍙戦€佺粰鑷缓搴旂敤鐨勬枃鏈秷鎭拰鑿滃崟鐐瑰嚮浜嬩欢銆?/span>
                </div>
              </div>
              <SettingsToggle
                label="鍚敤浜や簰鍥炶皟"
                value={toggleValue("wecom_callback_enabled", config.wecom_callback_enabled)}
                onChange={(value) => update("wecom_callback_enabled", String(value))}
                trueLabel="鍚敤"
                falseLabel="鍏抽棴"
              />
              <SettingsInput label="鍥炶皟 Token" name="wecom_callback_token" saved={config.has_wecom_callback_token} value={form.wecom_callback_token || ""} onChange={update} secret />
              <SettingsInput label="EncodingAESKey" name="wecom_callback_aes_key" saved={config.has_wecom_callback_aes_key} value={form.wecom_callback_aes_key || ""} onChange={update} secret />
              <SettingsInput
                label="MediaIndex 鍏綉鍩熷悕"
                help="浼佷笟寰俊鍜屾墜鏈哄彲璁块棶鐨?MediaIndex 鍦板潃锛岀敤浜庤嚜鍔ㄧ粍鍚堟爣鍑嗗洖璋?URL銆?
                name="public_base_url"
                saved={Boolean(config.public_base_url)}
                value={form.public_base_url ?? ""}
                onChange={update}
                placeholder={config.public_base_url || window.location.origin}
                showSavedValue
              />
              <SettingsInput
                label="鍏佽鎸囦护鐨勬垚鍛?
                name="wecom_callback_allowed_users"
                saved={Boolean(config.wecom_callback_allowed_users)}
                value={form.wecom_callback_allowed_users ?? ""}
                onChange={update}
                placeholder={config.wecom_callback_allowed_users || "鐣欑┖鍏佽搴旂敤鍙鑼冨洿鍐呯殑鎴愬憳"}
                showSavedValue
              />
              <SettingsInput
                label="浼佷笟寰俊鍚庡彴鍥炶皟 URL"
                name="wecom_callback_url"
                saved={Boolean(config.wecom_callback_url)}
                value={form.wecom_callback_url ?? ""}
                onChange={update}
                placeholder={config.wecom_callback_url || generatedCallbackUrl}
                showSavedValue
                action={(
                  <button type="button" className="ghost compact-action" onClick={() => void copyCallbackUrl()}>
                    {callbackCopied ? "宸插鍒? : "澶嶅埗 URL"}
                  </button>
                )}
              />
              <div className="direct-download-settings">
                <SettingsToggle
                  label="涓嬭浇閾炬帴鑷姩杞瓨"
                  help="寮€鍚悗锛屽垎浜摼鎺ヤ細鐩存帴杞瓨锛涘叧鑱旂綉鐩樹负 115 鏃讹紝纾佸姏銆佺數椹村拰 HTTP 涓嬭浇閾炬帴浼氭彁浜ゅ埌 115 绂荤嚎涓嬭浇銆備娇鐢ㄨ繖浜涚绾夸笅杞藉姛鑳介渶瑕佸～鍐?115 Cookie銆?
                  value={toggleValue("direct_download_enabled", config.direct_download_enabled)}
                  onChange={(value) => update("direct_download_enabled", String(value))}
                  trueLabel="鍚敤"
                  falseLabel="鍏抽棴"
                />
                <div className="direct-download-grid">
                  <label className="settings-field compact-select-field">
                    <span>鍏宠仈缃戠洏</span>
                    <select
                      value={form.direct_download_provider || config.direct_download_provider || "qas"}
                      onChange={(event) => update("direct_download_provider", event.target.value)}
                      aria-label="涓嬭浇閾炬帴鍏宠仈缃戠洏"
                    >
                      <option value="qas">澶稿厠</option>
                      <option value="p115">115</option>
                    </select>
                  </label>
                  <SettingsInput
                    label="榛樿淇濆瓨璺緞"
                    helpTooltip="鏀跺埌鍒嗕韩閾炬帴鍚庯紝浼氬厛鍙嶉鍙€夊瓙鏂囦欢澶癸紱纭閫夋嫨鍚庡啀杞瓨鍒板搴旂洰褰曘€?
                    name="direct_download_save_path"
                    saved={Boolean(config.direct_download_save_path)}
                    value={form.direct_download_save_path || ""}
                    onChange={update}
                    placeholder={config.direct_download_save_path || "鐣欑┖鍒欎娇鐢ㄦ墍閫夌綉鐩樻牴鐩綍涓嬬殑 /涓嬭浇閾炬帴"}
                    showSavedValue
                    action={(
                      <button
                        type="button"
                        className="ghost compact-action"
                        onClick={() => pickDirectDownloadPath()}
                        disabled={directDownloadProvider() === "p115" ? !(config.has_p115_cookie || config.has_p115_open) : !config.has_qas}
                      >
                        <FolderOpen size={16} />
                        閫夋嫨璺緞
                      </button>
                    )}
                  />
                  {directDownloadProvider() === "p115" && (
                    <p className="settings-help">115 鍒嗕韩閾炬帴杞瓨闇€瑕侀厤缃湁鏁?Cookie锛?15 Open 浠呮敮鎸佷釜浜虹洰褰曡鍙栧拰纾佸姏銆乪d2k銆丠TTP 绂荤嚎涓嬭浇銆?/p>
                  )}
                </div>
              </div>
              <CommandReference />
              <p className="channel-help">鐩存帴鍙戦€佸奖瑙嗚祫婧愬悕浼氳嚜鍔ㄥ尮閰嶅苟淇濆瓨鍒扮綉鐩橈紱鍙戦€佲€滄湰鍦?璧勬簮鍚嶁€濅細淇濆瓨鍒版湰鍦般€傚彂閫佸じ鍏嬫垨 115 鍒嗕韩閾炬帴浼氭寜榛樿璺緞鐩存帴杞瓨锛涘叧鑱旂綉鐩樹负 115 鏃讹紝纾佸姏銆佺數椹村拰 HTTP 涓嬭浇閾炬帴浼氭彁浜ゅ埌 115 绂荤嚎涓嬭浇銆俆oken 鍜?EncodingAESKey 瑕佷笌浼佷笟寰俊绠＄悊鍚庡彴濉啓鐨勫€煎畬鍏ㄤ竴鑷淬€?/p>
            </div>
          </SettingsSection>
          )}

          {notificationChannel === "wecom_bot" && (
          <SettingsSection title="浼佸井鏈哄櫒浜? body="浣跨敤缇よ亰鏈哄櫒浜?Webhook锛屾秷鎭浐瀹氬彂閫佸埌鏈哄櫒浜烘墍鍦ㄧ兢鑱娿€?>
            <div className="notification-channel-card">
              <div className="channel-heading">
                <div>
                  <strong>缇ゆ満鍣ㄤ汉</strong>
                  <span>浣跨敤缇よ亰鏈哄櫒浜?webhook锛屾秷鎭浐瀹氬彂閫佸埌鏈哄櫒浜烘墍鍦ㄧ兢鑱娿€?/span>
                </div>
              </div>
              <SettingsToggle
                label="鍚敤缇ゆ満鍣ㄤ汉"
                value={toggleValue("wecom_enabled", config.wecom_enabled)}
                onChange={(value) => update("wecom_enabled", String(value))}
                trueLabel="鍚敤"
                falseLabel="鍏抽棴"
              />
              <SettingsInput label="鏈哄櫒浜?Key" name="wecom_key" saved={config.has_wecom_key} value={form.wecom_key || ""} onChange={update} secret />
              <div className="channel-test-row">
                <button type="button" className="ghost compact-action" onClick={() => void testNotificationChannel("wecom")} disabled={testingChannel !== null}>
                  {testingChannel === "wecom" && <Spinner />}
                  娴嬭瘯缇ゆ満鍣ㄤ汉
                </button>
                {channelResults.wecom && <span className={channelResults.wecom.ok ? "success" : "danger"}>{channelResults.wecom.message}</span>}
              </div>
            </div>
          </SettingsSection>
          )}

          {notificationChannel === "telegram" && (
          <SettingsSection title="Telegram" body="閫氳繃 Telegram Bot API 鍙戦€佹秷鎭紝鏀寔绉佽亰銆佺兢缁勫拰棰戦亾鐨?Chat ID銆?>
            <SettingsToggle
              label="鍚敤 Telegram"
              value={toggleValue("telegram_enabled", config.telegram_enabled)}
              onChange={(value) => update("telegram_enabled", String(value))}
              trueLabel="鍚敤"
              falseLabel="鍏抽棴"
            />
            <SettingsInput label="Bot Token" name="telegram_bot_token" saved={config.has_telegram_token} value={form.telegram_bot_token || ""} onChange={update} secret />
            <SettingsInput label="Chat ID" name="telegram_chat_id" saved={Boolean(config.telegram_chat_id)} value={form.telegram_chat_id || ""} onChange={update} placeholder={config.telegram_chat_id || "-1001234567890"} showSavedValue />
            <SettingsInput
              label="API 鍦板潃"
              name="telegram_api_host"
              saved
              value={form.telegram_api_host || ""}
              onChange={update}
              placeholder={config.telegram_api_host || "https://api.telegram.org"}
              showSavedValue
              action={(
                <button type="button" className="primary compact-action" onClick={() => void testNotificationChannel("telegram")} disabled={testingChannel !== null}>
                  {testingChannel === "telegram" && <Spinner />}
                  娴嬭瘯 Telegram
                </button>
              )}
              result={channelResults.telegram}
            />
          </SettingsSection>
          )}

          <div className="settings-footer">
            <span>{saving ? "姝ｅ湪淇濆瓨閫氱煡璁剧疆" : "淇敼鍚庝娇鐢ㄩ〉闈㈤《閮ㄧ殑淇濆瓨鎸夐挳"}</span>
          </div>
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
\r\nfunction CommandReference() {
  const commands = [
    ["璧勬簮鍚?, "鎼滅储褰辫锛屽瓨鍦ㄥ涓粨鏋滄椂鍥炲鏁板瓧閫夋嫨"],
    ["鏈湴 璧勬簮鍚?, "鎼滅储褰辫骞跺皢纭鍚庣殑璧勬簮淇濆瓨鍒版湰鍦?],
    ["鍒嗕韩閾炬帴", "澶稿厠鎴?115 鍒嗕韩閾炬帴鐩存帴杞瓨鍒伴粯璁よ矾寰?],
    ["纾佸姏閾炬帴", "鍏宠仈缃戠洏涓?115 鏃舵彁浜ょ绾夸笅杞?],
    ["/review", "鏌ョ湅寰呯‘璁や换鍔★紝骞堕€氳繃缂栧彿閫夋嫨鍊欓€夎祫婧?],
    ["/status", "鏌ョ湅杩芥洿銆佹効鏈涘崟銆佸緟纭鍜屾湭璇婚€氱煡鏁伴噺"],
    ["/tracking", "鏌ョ湅鏈€杩戠殑鏅鸿兘杩芥洿浠诲姟"],
    ["/wishlist", "鏌ョ湅鏈€杩戠殑鎰挎湜鍗曚换鍔?],
    ["/notifications", "鏌ョ湅鏈€杩戦€氱煡"],
    ["/cancel", "鍙栨秷褰撳墠绛夊緟涓殑缂栧彿閫夋嫨"],
    ["/help", "鏌ョ湅浼佷笟寰俊鍐呯疆鎸囦护甯姪"],
  ];
  return (
    <section className="command-reference" aria-labelledby="command-reference-title">
      <div className="command-reference-heading">
        <TerminalWindow size={23} aria-hidden />
        <div>
          <strong id="command-reference-title">鍐呯疆鎸囦护閫熸煡</strong>
          <span>鍦ㄤ紒涓氬井淇¤嚜寤哄簲鐢ㄤ細璇濅腑鐩存帴鍙戦€?/span>
        </div>
      </div>
      <div className="command-reference-grid">
        {commands.map(([command, description]) => (
          <div className="command-reference-item" key={command}>
            <code>{command}</code>
            <span>{description}</span>
          </div>
        ))}
      </div>
      <p>缂栧彿閫夋嫨鏈夋晥鏈熶负 30 鍒嗛挓銆傚洖澶嶆暟瀛楃‘璁ゅ綋鍓嶉€夐」锛屽彂閫佲€滃彇娑堚€濇垨 <code>/cancel</code> 缁堟閫夋嫨銆?/p>
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

function SettingsPage({ section }: { section: Exclude<SettingsTab, "notifications"> }) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [testingPansou, setTestingPansou] = useState(false);
  const [pansouTestResult, setPansouTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [testingTmdb, setTestingTmdb] = useState(false);
  const [tmdbTestResult, setTmdbTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [testingQas, setTestingQas] = useState(false);
  const [qasTestResult, setQasTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [testingP115, setTestingP115] = useState(false);
  const [importingP115, setImportingP115] = useState(false);
  const [p115Result, setP115Result] = useState<{ ok: boolean; message: string } | null>(null);
  const [cookieHelpOpen, setCookieHelpOpen] = useState(false);
  const [qasPansouEnabled, setQasPansouEnabled] = useState<boolean | null>(null);
  const [settingQasPansou, setSettingQasPansou] = useState(false);
  const [providerSettingsTab, setProviderSettingsTab] = useState<"qas" | "p115">("qas");
  const [testingOpenList, setTestingOpenList] = useState(false);
  const [openListResult, setOpenListResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [syncingOpenList, setSyncingOpenList] = useState(false);
  const [directoryPicker, setDirectoryPicker] = useState<{ key: string; label: string; onSelect?: (path: string) => void } | null>(null);
  const [providerDirectoryPicker, setProviderDirectoryPicker] = useState<{ provider: "qas" | "p115"; label: string; startPath: string; onSelect: (path: string) => void } | null>(null);
  const [openListTab, setOpenListTab] = useState<"settings" | "manual" | "auto">("settings");

  useEffect(() => {
    api.config().then(setConfig);
    api.qasPansouStatus().then((result) => {
      if (result.ok && typeof result.enabled === "boolean") setQasPansouEnabled(result.enabled);
    }).catch(() => setQasPansouEnabled(null));
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await api.saveConfig(buildConfigPayload(form));
      const next = await api.config();
      setConfig(next);
      setForm({});
      setMessage("宸蹭繚瀛橀厤缃?);
      window.dispatchEvent(new Event("mediaindex:providers-changed"));
    } catch {
      setMessage("淇濆瓨澶辫触");
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
      label: `${label}鍒嗙被璺緞`,
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

  async function testPansou() {
    setTestingPansou(true);
    setPansouTestResult(null);
    try {
      const result = await api.testPansou();
      setPansouTestResult({ ok: result.ok, message: result.message });
    } catch {
      setPansouTestResult({ ok: false, message: "杩炴帴澶辫触锛岃鍏堜繚瀛樺湴鍧€鍚庨噸璇? });
    } finally {
      setTestingPansou(false);
    }
  }

  async function testTmdb() {
    setTestingTmdb(true);
    setTmdbTestResult(null);
    try {
      const result = await api.testTmdb();
      setTmdbTestResult({ ok: result.ok, message: result.message });
    } catch (error) {
      setTmdbTestResult({ ok: false, message: error instanceof ApiError ? error.message : "TMDB 杩炴帴澶辫触" });
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
      setQasTestResult({ ok: false, message: error instanceof ApiError ? error.message : "QAS 杩炴帴澶辫触" });
    } finally {
      setTestingQas(false);
    }
  }

  async function importP115Cookie() {
    setImportingP115(true);
    setP115Result(null);
    try {
      const result = await api.importP115FromOpenList();
      setP115Result({ ok: result.ok, message: result.message });
      if (result.ok) setConfig(await api.config());
    } catch (error) {
      setP115Result({ ok: false, message: error instanceof ApiError ? error.message : "浠?OpenList 瀵煎叆澶辫触" });
    } finally {
      setImportingP115(false);
    }
  }

  async function clearP115Open() {
    setImportingP115(true);
    setP115Result(null);
    try {
      const result = await api.clearP115Open();
      setP115Result({ ok: result.ok, message: result.message });
      if (result.ok) setConfig(await api.config());
    } catch (error) {
      setP115Result({ ok: false, message: error instanceof ApiError ? error.message : "娓呴櫎 115 Open 鎺堟潈澶辫触" });
    } finally {
      setImportingP115(false);
    }
  }

  async function testP115() {
    setTestingP115(true);
    setP115Result(null);
    try {
      const result = await api.testP115();
      setP115Result({ ok: result.ok, message: result.message });
    } catch (error) {
      setP115Result({ ok: false, message: error instanceof ApiError ? error.message : "115 杩炴帴澶辫触" });
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
      setOpenListResult({ ok: false, message: error instanceof ApiError ? error.message : "OpenList 杩炴帴澶辫触" });
    } finally {
      setTestingOpenList(false);
    }
  }

  async function syncOpenList() {
    setSyncingOpenList(true);
    setOpenListResult(null);
    try {
      const result = await api.syncOpenListLibrary();
      setOpenListResult({ ok: result.ok, message: result.message });
      if (result.ok) window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setOpenListResult({ ok: false, message: error instanceof ApiError ? error.message : "OpenList 鍚屾澶辫触" });
    } finally {
      setSyncingOpenList(false);
    }
  }

  function setProviderEnabled(provider: "qas" | "p115", enabled: boolean) {
    const current = (form.enabled_providers || config?.enabled_providers.filter((value) => value !== "moviepilot_115").join(",") || "qas")
      .split(",")
      .filter((value): value is "qas" | "p115" => value === "qas" || value === "p115");
    const next = enabled ? [...new Set([...current, provider])] : current.filter((value) => value !== provider);
    if (!next.length) {
      setMessage("鑷冲皯淇濈暀涓€涓綉鐩?Provider");
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
      setMessage(`${enabled ? "鍚敤" : "绂佺敤"} QAS 鑷甫鎼滅储澶辫触`);
    } finally {
      setSettingQasPansou(false);
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>{section === "basic" ? "鍩虹璁剧疆" : section === "drives" ? "缃戠洏璁剧疆" : section === "network" ? "缃戠粶浠ｇ悊" : section === "wishlist" ? "宸℃" : "OpenList 鍚屾"}</h1>
          <p>{section === "basic" ? "绠＄悊閫氱敤鏈嶅姟銆佸懡鍚嶈鍒欏拰閰嶇疆澶囦唤銆? : section === "drives" ? "鍒嗗埆绠＄悊澶稿厠涓?115 鐨勮繛鎺ャ€佷繚瀛樼洰褰曞拰鍒嗙被璺緞銆? : section === "network" ? "缁熶竴閰嶇疆鏈嶅姟绔闂閮ㄧ綉缁滄椂浣跨敤鐨勪唬鐞嗐€? : section === "wishlist" ? "缁熶竴璁剧疆鎰挎湜鍗曞拰鏅鸿兘杩芥洿鐨勫贰妫€绛栫暐銆? : "閰嶇疆 OpenList 鎸傝浇鐩綍锛屼互鍙婂じ鍏嬪獟浣撳簱鍒?115 濯掍綋搴撶殑鍙€夊悓姝ャ€?}</p>
        </div>
      </div>
      {!config && <div className="list-skeleton" />}
      {config && (
        <form id={`${section}-settings-form`} className="settings-form" onSubmit={save}>
          {section === "basic" && (
          <>
          <SettingsSection title="閫氱敤鏈嶅姟" body="TMDB 鍜?PanSou 鐢辨墍鏈夌綉鐩樺叡鐢紱缃戠洏寮€鍏冲喅瀹氬彂鐜般€佹効鏈涘崟鍜岃拷鏇翠腑鍙€夋嫨鐨勭洰鏍囥€?>
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
                  {testingTmdb ? "娴嬭瘯涓? : "娴嬭瘯杩炴帴"}
                </button>
              )}
              result={tmdbTestResult}
            />
            <SettingsInput
              label="PanSou 鍦板潃"
              name="pansou_url"
              saved={Boolean(config.pansou_url)}
              value={form.pansou_url || ""}
              onChange={update}
              placeholder={config.pansou_url || "http://your-pansou-host:your-pansou-port"}
              showSavedValue
              action={(
                <button type="button" className="primary compact-action" onClick={() => void testPansou()} disabled={testingPansou || saving}>
                  {testingPansou && <Spinner />}
                  {testingPansou ? "娴嬭瘯涓? : "娴嬭瘯杩炴帴"}
                </button>
              )}
              result={pansouTestResult}
            />
            <div className="provider-master-switches">
              <SettingsToggle
                label="澶稿厠锛圦AS锛?
                value={(form.enabled_providers || config.enabled_providers.join(",")).split(",").includes("qas")}
                onChange={(enabled) => setProviderEnabled("qas", enabled)}
                trueLabel="宸插惎鐢?
                falseLabel="宸插仠鐢?
              />
              <SettingsToggle
                label="115锛堝師鐢燂級"
                value={(form.enabled_providers || config.enabled_providers.join(",")).split(",").includes("p115")}
                onChange={(enabled) => setProviderEnabled("p115", enabled)}
                trueLabel="宸插惎鐢?
                falseLabel="宸插仠鐢?
              />
            </div>
          </SettingsSection>

          <SettingsSection title="鍛藉悕涓庡垎瀛? body="涓よ竟缃戠洏鍏辩敤鍚屼竴濂楀懡鍚嶈鍒欙紱鍏抽棴鍒嗗鍚庡彧褰卞搷鏂扮敓鎴愮殑璺緞锛屾棫浠诲姟淇濇寔鍏煎銆?>
            <SettingsInput label="濯掍綋鏂囦欢澶瑰懡鍚嶈鍒? name="media_folder_naming_rule" saved value={form.media_folder_naming_rule || ""} onChange={update} placeholder={config.media_folder_naming_rule} showSavedValue />
            <SettingsInput label="瀛ｆ枃浠跺す鍛藉悕瑙勫垯" name="season_folder_naming_rule" saved value={form.season_folder_naming_rule || ""} onChange={update} placeholder={config.season_folder_naming_rule} showSavedValue />
            <SettingsInput label="鐢靛奖鍛藉悕瑙勫垯" name="movie_naming_rule" saved value={form.movie_naming_rule || ""} onChange={update} placeholder={config.movie_naming_rule} showSavedValue />
            <SettingsInput label="鍓ч泦鍛藉悕瑙勫垯" name="episode_naming_rule" saved value={form.episode_naming_rule || ""} onChange={update} placeholder={config.episode_naming_rule} showSavedValue />
            <div className="settings-help naming-help">
              <span>濯掍綋鏂囦欢澶癸細{`{title}`}銆亄`{year}`}锛屼緥濡?{`{title} ({year})`}銆?/span>
              <span>瀛ｆ枃浠跺す锛歿`{season}`} 鎴?{`{season:02d}`}锛屼緥濡?{`Season {season}`}銆亄`S{season:02d}`}銆?/span>
              <span>鏂囦欢鍛藉悕锛氱數褰辩敤 {`{title}`}銆亄`{year}`}锛涘墽闆嗗彟鍙敤 {`{season:02d}`}銆亄`{episode:02d}`}銆?/span>
            </div>
            <SettingsToggle
              label="鍓ч泦鎸夊鍒嗙洰褰?
              help="寮€鍚悗鏂颁换鍔￠粯璁や繚瀛樺埌濯掍綋鐩綍涓嬬殑 Season N锛涚郴缁熶粛浼氳瘑鍒棫鐨勫獟浣撶洰褰曡矾寰勩€?
              value={form.season_subdirectory_enabled === undefined ? config.season_subdirectory_enabled : form.season_subdirectory_enabled === "true"}
              onChange={(value) => update("season_subdirectory_enabled", String(value))}
              trueLabel="寮€鍚?
              falseLabel="鍏抽棴"
            />
          </SettingsSection>

          <ConfigBackupSettings onImported={async () => setConfig(await api.config())} spinner={() => <Spinner />} />
          </>
          )}

          {section === "drives" && (
          <section className="provider-settings-shell" aria-label="缃戠洏鐙珛璁剧疆">
            <div className="provider-settings-tabs" role="tablist" aria-label="閫夋嫨缃戠洏璁剧疆">
              <button type="button" role="tab" aria-selected={providerSettingsTab === "qas"} className={providerSettingsTab === "qas" ? "active" : ""} onClick={() => setProviderSettingsTab("qas")}>
                <span className="provider-tab-icon">澶稿厠</span>
              </button>
              <button type="button" role="tab" aria-selected={providerSettingsTab === "p115"} className={providerSettingsTab === "p115" ? "active" : ""} onClick={() => setProviderSettingsTab("p115")}>
                <span className="provider-tab-icon">115</span>
              </button>
            </div>
            <div className="provider-settings-panel" role="tabpanel">
              <header className="provider-panel-heading">
                <div>
                  <h2>{providerSettingsTab === "qas" ? "澶稿厠锛圦AS锛? : "115"}</h2>
                </div>
                <span className={`provider-state ${(form.enabled_providers || config.enabled_providers.join(",")).split(",").includes(providerSettingsTab) ? "enabled" : ""}`}>
                  {(form.enabled_providers || config.enabled_providers.join(",")).split(",").includes(providerSettingsTab) ? "宸插惎鐢? : "宸插仠鐢?}
                </span>
              </header>

              {providerSettingsTab === "qas" ? (
                <div className="provider-module-grid">
                  <SettingsSection title="鏈嶅姟杩炴帴" body="杩炴帴 QAS锛岃礋璐ｅじ鍏嬪垎浜鍙栥€佽浆瀛樺拰鏀瑰悕銆?>
                    <SettingsInput label="QAS 鍦板潃" name="qas_base_url" saved={Boolean(config.qas_base_url)} value={form.qas_base_url || ""} onChange={update} placeholder={config.qas_base_url || "http://your-qas-host:5005"} showSavedValue />
                    <SettingsInput label="QAS Token" name="qas_token" saved={config.has_qas} value={form.qas_token || ""} onChange={update} secret />
                    <div className="settings-action-strip provider-connection-actions">
                      <button type="button" className="primary compact-action provider-test-button" onClick={() => void testQas()} disabled={testingQas || saving}>
                        {testingQas && <Spinner />}
                        {testingQas ? "娴嬭瘯涓? : "娴嬭瘯杩炴帴"}
                      </button>
                      <ProviderConnectionStatus connected={config.has_qas} label="QAS" />
                      {qasTestResult && <div className={`settings-inline-result ${qasTestResult.ok ? "success" : "error"}`}>{qasTestResult.message}</div>}
                    </div>
                    <SettingsToggle
                      label="QAS 鑷甫鎼滅储"
                      help="QAS 鍐呯疆鐨?PanSou 鏁版嵁婧愬彲鑳芥瘮鐙珛 PanSou 灏戯紝寤鸿鍋滅敤锛岄伩鍏嶉噸澶嶆绱㈡垨缁撴灉鍐茬獊銆?
                      value={qasPansouEnabled ?? false}
                      onChange={(enabled) => void setQasPansou(enabled)}
                      trueLabel="鍚敤"
                      falseLabel="鍋滅敤"
                      disabled={qasPansouEnabled === null || settingQasPansou}
                      busy={settingQasPansou}
                    />
                  </SettingsSection>
                  <SettingsSection title="淇濆瓨璺緞" body="鍙敤浜庡じ鍏嬶紝涓嶄笌 115 鍏辩敤銆?>
                    <SettingsInput
                      label="澶稿厠淇濆瓨鏍硅矾寰?
                      name="qas_save_path"
                      saved
                      value={form.qas_save_path || ""}
                      onChange={update}
                      placeholder={config.qas_root}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("qas", "qas_save_path", "澶稿厠淇濆瓨鏍硅矾寰?, config.qas_root)} disabled={!config.has_qas} title="閫夋嫨鐩綍" aria-label="閫夋嫨澶稿厠淇濆瓨鏍硅矾寰?><FolderOpen size={18} /></button>}
                    />
                    <SettingsInput
                      label="鏈湴淇濆瓨鏍硅矾寰?
                      name="local_save_path"
                      saved
                      value={form.local_save_path || ""}
                      onChange={update}
                      placeholder={config.local_root}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("qas", "local_save_path", "鏈湴淇濆瓨鏍硅矾寰?, config.local_root)} disabled={!config.has_qas} title="閫夋嫨鐩綍" aria-label="閫夋嫨鏈湴淇濆瓨鏍硅矾寰?><FolderOpen size={18} /></button>}
                    />
                    <p className="settings-help">鏈湴淇濆瓨鐢?QAS 鎵ц锛屽洜姝や笌澶稿厠璺緞鏀惧湪鍚屼竴妯″潡绠＄悊銆?/p>
                  </SettingsSection>
                  <SettingsSection title="鍒嗙被璺緞" body="澶稿厠鏍圭洰褰曚笅鐨勫垎绫诲瓙鐩綍锛屽彲澧炲姞鑷畾涔夊垎绫汇€?>
                    <CategoryPathSettings config={config} form={form} onChange={setForm} provider="qas" canPickPath={config.has_qas} onPickPath={(key, label) => selectCategoryPath("qas", key, label)} />
                  </SettingsSection>
                </div>
              ) : (
                <div className="provider-module-grid">
                  <SettingsSection title="115 鏈嶅姟杩炴帴" body="鏀寔鐩存帴浣跨敤 Cookie锛屾垨浠?OpenList 瀵煎叆 115 / 115 Open 鐨勫嚟鎹€?>
                    <SettingsInput
                      label="115 Cookie"
                      name="p115_cookie"
                      saved={config.has_p115_cookie}
                      value={form.p115_cookie || ""}
                      onChange={update}
                      secret
                      action={(
                        <button type="button" className="icon settings-info-button" onClick={() => setCookieHelpOpen(true)} title="鏌ョ湅 Cookie 鑾峰彇璇存槑" aria-label="鏌ョ湅 Cookie 鑾峰彇璇存槑">
                          <Info size={18} />
                        </button>
                      )}
                    />
                    <div className="settings-action-strip provider-connection-actions">
                      <button type="button" className="primary compact-action provider-test-button" onClick={() => void testP115()} disabled={testingP115 || saving || importingP115}>
                        {testingP115 && <Spinner />}
                        {testingP115 ? "娴嬭瘯涓? : "娴嬭瘯杩炴帴"}
                      </button>
                      <ProviderConnectionStatus connected={config.has_p115_cookie || config.has_p115_open} label="115" />
                      {p115Result && <div className={`settings-inline-result ${p115Result.ok ? "success" : "error"}`}>{p115Result.message}</div>}
                    </div>
                    <div className="settings-action-strip">
                      <span className="settings-help">浼氫紭鍏堝鍏?OpenList 鐨?115 Cookie锛涙病鏈?Cookie 鏃惰嚜鍔ㄤ娇鐢?115 Open access/refresh token銆?/span>
                      <button type="button" className="ghost compact-action" onClick={() => void importP115Cookie()} disabled={importingP115 || saving || !config.has_openlist_token}>
                        {importingP115 && <Spinner />}
                        {importingP115 ? "瀵煎叆涓? : "浠?OpenList 瀵煎叆"}
                      </button>
                      {config.has_p115_open && <button type="button" className="ghost compact-action" onClick={() => void clearP115Open()} disabled={importingP115 || saving}>
                        {importingP115 && <Spinner />}
                        娓呴櫎 115 Open 鎺堟潈
        </button>
                    </div>
                  </SettingsSection>
                  <SettingsSection title="淇濆瓨璺緞" body="鍙敤浜?115锛屼笉涓庡じ鍏嬪叡鐢紱鏆傚瓨鐩綍鐢ㄤ簬瀹夊叏鏀瑰悕鍜岀Щ鍔ㄣ€?>
                    <SettingsInput
                      label="115 淇濆瓨鏍圭洰褰?
                      name="p115_root_path"
                      saved
                      value={form.p115_root_path || ""}
                      onChange={update}
                      placeholder={config.p115_root_path}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("p115", "p115_root_path", "115 淇濆瓨鏍圭洰褰?, config.p115_root_path)} disabled={!(config.has_p115_cookie || config.has_p115_open)} title="閫夋嫨鐩綍" aria-label="閫夋嫨 115 淇濆瓨鏍圭洰褰?><FolderOpen size={18} /></button>}
                    />
                    <SettingsInput
                      label="115 缃戠洏鏆傚瓨鐩綍"
                      name="p115_staging_path"
                      saved
                      value={form.p115_staging_path || ""}
                      onChange={update}
                      placeholder={config.p115_staging_path}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("p115", "p115_staging_path", "115 缃戠洏鏆傚瓨鐩綍", config.p115_staging_path)} disabled={!(config.has_p115_cookie || config.has_p115_open)} title="閫夋嫨鐩綍" aria-label="閫夋嫨 115 缃戠洏鏆傚瓨鐩綍"><FolderOpen size={18} /></button>}
                    />
                    <p className="settings-help">鏆傚瓨鐩綍浣嶄簬 115 缃戠洏鍐咃紝浠呯敤浜庢帴鏀躲€佹牳瀵广€佹敼鍚嶅悗鍐嶇Щ鍔ㄥ埌鏈€缁堝獟浣撶洰褰曪紝涓嶆槸 NAS 鏈湴鐩綍銆?/p>
                    <SettingsInput
                      label="115 杞瓨鏈湴鐩綍"
                      name="p115_local_path"
                      saved
                      value={form.p115_local_path || ""}
                      onChange={update}
                      placeholder={config.p115_local_path || "/downloads"}
                      showSavedValue
                      action={<button type="button" className="ghost compact-action path-picker-button" onClick={() => selectProviderSavePath("p115", "p115_local_path", "115 杞瓨鏈湴鐩綍", config.p115_local_path || "/downloads")} disabled={!(config.has_p115_cookie || config.has_p115_open)} title="閫夋嫨鐩綍" aria-label="閫夋嫨 115 杞瓨鏈湴鐩綍"><FolderOpen size={18} /></button>}
                    />
                    <p className="settings-help">鍙€夛紝鐢ㄤ簬 MP 鏁寸悊绛夐潪鐩存帴淇濆瓨鐨勮矾寰勩€?/p>
                  </SettingsSection>
                  <SettingsSection title="鍒嗙被璺緞" body="115 鏍圭洰褰曚笅鐨勫垎绫诲瓙鐩綍锛屽彲澧炲姞鑷畾涔夊垎绫汇€?>
                    <CategoryPathSettings config={config} form={form} onChange={setForm} provider="p115" canPickPath={config.has_p115_cookie || config.has_p115_open} onPickPath={(key, label) => selectCategoryPath("p115", key, label)} />
                  </SettingsSection>
                </div>
              )}
            </div>
          </section>
          )}

          {section === "openlist" && (
          <>
          <div className="openlist-mode-tabs" role="tablist" aria-label="OpenList 鍔熻兘">
            {([["settings", "鐩綍閰嶇疆"], ["manual", "鎵嬪姩鍚屾"], ["auto", "鑷姩鍚屾"]] as const).map(([value, label]) => (
              <button type="button" role="tab" aria-selected={openListTab === value} className={openListTab === value ? "active" : ""} onClick={() => setOpenListTab(value)} key={value}>{label}</button>
            ))}
          </div>
          {openListTab === "settings" && (
          <SettingsSection title="OpenList 缃戠洏闂村悓姝? body="閫氳繃 OpenList API 鍦ㄥ凡鎸傝浇鐨勫じ鍏嬪獟浣撳簱鍜?115 濯掍綋搴撲箣闂村鍒剁己澶辨枃浠讹紱涓嶅奖鍝嶅師鐢?QAS/115 杞瓨銆傛殏涓嶆敮鎸佷粠 115 澶嶅埗鍒板じ鍏嬨€?>
            <SettingsToggle label="鍚敤 OpenList 鍔熻兘" value={form.openlist_enabled === undefined ? config.openlist_enabled : form.openlist_enabled === "true"} onChange={(value) => update("openlist_enabled", String(value))} trueLabel="鍚敤" falseLabel="鍋滅敤" />
            <SettingsToggle label="鍏佽鑷姩鍚屾" help="寮€鍚悗锛屼粎鍦ㄥ弻缃戠洏杞瓨瀹屾垚鎴栨櫤鑳借拷鏇存墽琛屽悓姝ユ椂锛屾寜瀵瑰簲濯掍綋鐩綍澶嶅埗缂哄け鏂囦欢锛涗笉浼氬畾鏃跺鍒舵暣涓獟浣撳簱銆? value={form.openlist_auto_sync === undefined ? config.openlist_auto_sync : form.openlist_auto_sync === "true"} onChange={(value) => update("openlist_auto_sync", String(value))} trueLabel="鍏佽" falseLabel="鍏抽棴" />
            <SettingsInput label="OpenList 鍦板潃" name="openlist_url" saved={Boolean(config.openlist_url)} value={form.openlist_url || ""} onChange={update} placeholder={config.openlist_url || "http://openlist:5244"} showSavedValue />
            <SettingsInput label="OpenList Token" name="openlist_token" saved={config.has_openlist_token} value={form.openlist_token || ""} onChange={update} secret />
            <SettingsInput label="澶稿厠濯掍綋搴撶洰褰? help="濉啓 OpenList 鎸傝浇璺緞鍙婂叾涓嬬殑鐩綍锛屼緥濡?/澶稿厠/strm锛屼笉鏄湰鍦版枃浠剁郴缁熻矾寰勩€? name="openlist_qas_library_path" saved value={form.openlist_qas_library_path || ""} onChange={update} placeholder={config.openlist_qas_library_path} showSavedValue action={<button type="button" className="ghost compact-action" onClick={() => setDirectoryPicker({ key: "openlist_qas_library_path", label: "澶稿厠濯掍綋搴撶洰褰? })} disabled={!config.has_openlist_token}>閫夋嫨鐩綍</button>} />
            <SettingsInput label="115 濯掍綋搴撶洰褰? help="濉啓 OpenList 鎸傝浇璺緞鍙婂叾涓嬬殑鐩綍锛屼緥濡?/115/濯掍綋搴擄紝涓嶆槸鏈湴鏂囦欢绯荤粺璺緞銆? name="openlist_p115_library_path" saved value={form.openlist_p115_library_path || ""} onChange={update} placeholder={config.openlist_p115_library_path} showSavedValue action={<button type="button" className="ghost compact-action" onClick={() => setDirectoryPicker({ key: "openlist_p115_library_path", label: "115 濯掍綋搴撶洰褰? })} disabled={!config.has_openlist_token}>閫夋嫨鐩綍</button>} />
            <div className="settings-action-strip">
              <button type="button" className="primary compact-action" onClick={() => void testOpenList()} disabled={testingOpenList || saving || !config.openlist_enabled}>
                {testingOpenList && <Spinner />}{testingOpenList ? "娴嬭瘯涓? : "娴嬭瘯杩炴帴"}
              </button>
              <button type="button" className="ghost compact-action" title="鏆備笉鏀寔浠?115 澶嶅埗鍒板じ鍏嬶紝鎵嬪姩鍚屾宸叉殏鏃跺仠鐢? onClick={() => void syncOpenList()} disabled>
                {syncingOpenList && <Spinner />}{syncingOpenList ? "鍚屾涓? : "绔嬪嵆鍚屾濯掍綋搴?}
              </button>
              {openListResult && <div className={`settings-inline-result ${openListResult.ok ? "success" : "error"}`}>{openListResult.message}</div>}
            </div>
            <p className="settings-help">OpenList 鐨勬墜鍔ㄥ悓姝ユ殏鏃跺仠鐢細115 鈫?澶稿厠澶嶅埗浼氬湪 OpenList 涓婁紶闃舵澶辫触銆傚じ鍏?鈫?115 鐨勮嚜鍔ㄥ悓姝ュ拰杩芥洿鍚屾浠嶅彲鐢ㄣ€?/p>
          </SettingsSection>
          )}
          {openListTab === "manual" && <OpenListManualSync qasPath={form.openlist_qas_library_path || config.openlist_qas_library_path} p115Path={form.openlist_p115_library_path || config.openlist_p115_library_path} enabled={config.openlist_enabled && config.has_openlist_token} copyDisabled copyDisabledReason="鏆備笉鏀寔浠?115 澶嶅埗鍒板じ鍏嬶紱鎵嬪姩澶嶅埗鏆傛椂鍋滅敤銆? />}
          {openListTab === "auto" && (
            <SettingsSection title="杩芥洿鑷姩琛ラ綈" body="鏅鸿兘杩芥洿鍙戠幇鏌愪竴闆嗗彧瀛樺湪涓€涓綉鐩樻椂锛屽彧澶嶅埗杩欎竴闆嗗埌缂哄け缃戠洏锛屼笉杩涜鍏ㄩ噺鍚屾銆?>
              <SettingsToggle label="鍏佽鑷姩鍚屾" help="寮€鍚悗锛孧ediaIndex 浼氬湪鍙岀綉鐩樿浆瀛樺畬鎴愩€佹櫤鑳借拷鏇磋浆瀛樺畬鎴愬悗鑷姩瀵规瘮涓よ竟鐩綍锛岀己鍝竟灏变粠鍙︿竴杈瑰鍒惰繃鍘汇€? value={form.openlist_auto_sync === undefined ? config.openlist_auto_sync : form.openlist_auto_sync === "true"} onChange={(value) => update("openlist_auto_sync", String(value))} trueLabel="鍏佽" falseLabel="鍏抽棴" />
              <p className="settings-help">鑷姩鍚屾宸叉帴鍏ユ墽琛屼换鍔＄獥鍙ｏ紱鐩稿悓鐩綍姝ｅ湪鍚屾鏃朵笉浼氶噸澶嶆彁浜ゃ€傞渶瑕佷袱涓獟浣撳簱鐩綍閮借兘閫氳繃 OpenList Token 璇诲彇锛屽苟涓旂洰鏍囩綉鐩樺厑璁稿鍒跺啓鍏ャ€?/p>
            </SettingsSection>
          )}
          </>
          )}

          {section === "network" && (
          <SettingsSection title="缃戠粶浠ｇ悊" body="鐢ㄤ簬 TMDB銆丳anSou 绛夊叕鍏辩綉缁滆姹傦紱鐣欑┖鏃剁洿鎺ヨ繛鎺ャ€?>
            <SettingsInput
              label="浠ｇ悊鍦板潃"
              name="proxy_url"
              saved={config.has_proxy}
              value={form.proxy_url ?? ""}
              onChange={update}
              placeholder={config.proxy_url || "http://192.168.1.2:7890"}
            />
            <p className="settings-help">鏀寔 HTTP/HTTPS 浠ｇ悊锛涘鏋滈渶瑕佽璇侊紝鍙～鍐欏甫鐢ㄦ埛鍚嶅拰瀵嗙爜鐨勫畬鏁村湴鍧€銆?/p>
          </SettingsSection>
          )}

          {section === "wishlist" && (<>
          <SettingsSection title="鎰挎湜鍗? body={`榛樿鍦?TMDB 鏃ユ湡褰撳ぉ ${String(config.wishlist_default_check_hour).padStart(2, "0")}:00 妫€鏌ワ紝姣忓紶鎰挎湜鍗曚粛鍙崟鐙皟鏁淬€俙}>
            <SettingsToggle
              label="鍚敤鑷姩宸℃"
              value={form.wishlist_scheduler_enabled === undefined ? config.wishlist_scheduler_enabled : form.wishlist_scheduler_enabled === "true"}
              onChange={(value) => update("wishlist_scheduler_enabled", String(value))}
            />
            <SettingsNumberInput label="宸℃鍛ㄦ湡锛堝垎閽燂級" name="wishlist_poll_minutes" value={form.wishlist_poll_minutes || ""} placeholder={String(config.wishlist_poll_minutes)} min={1} max={1440} onChange={update} />
            <SettingsNumberInput label="榛樿妫€鏌ュ皬鏃? name="wishlist_default_check_hour" value={form.wishlist_default_check_hour || ""} placeholder={String(config.wishlist_default_check_hour)} min={0} max={23} onChange={update} />
          </SettingsSection>
          <SettingsSection title="鏅鸿兘杩芥洿" body="鍦?TMDB 鏇存柊鏃ユ湡褰撳ぉ鐨勮瀹氭椂闂村紑濮嬫鏌ワ紝澶辫触鎴栫瓑寰呬笂浼犳椂鎸夐棿闅旈噸璇曪紝杈惧埌娆℃暟鍚庢殏鍋滃苟鎻愮ず澶勭悊銆?>
            <SettingsToggle label="鍚敤鑷姩宸℃" help="鍏抽棴鍚庝粛鍙湪鏅鸿兘杩芥洿鍗＄墖涓墜鍔ㄦ墽琛屻€? value={form.tracking_scheduler_enabled === undefined ? config.tracking_scheduler_enabled : form.tracking_scheduler_enabled === "true"} onChange={(value) => update("tracking_scheduler_enabled", String(value))} />
            <label className="settings-field"><span>杩芥洿鏃堕棿</span><input type="time" value={form.tracking_check_time || config.tracking_check_time} onChange={(event) => update("tracking_check_time", event.target.value)} /></label>
            <SettingsNumberInput label="宸℃杞鍛ㄦ湡锛堝垎閽燂級" name="tracking_poll_minutes" value={form.tracking_poll_minutes || ""} placeholder={String(config.tracking_poll_minutes)} min={1} max={1440} onChange={update} />
            <SettingsNumberInput label="閲嶈瘯闂撮殧锛堝垎閽燂級" name="tracking_retry_interval_minutes" value={form.tracking_retry_interval_minutes || ""} placeholder={String(config.tracking_retry_interval_minutes)} min={1} max={1440} onChange={update} />
            <SettingsNumberInput label="宸℃娆℃暟" name="tracking_max_retries" value={form.tracking_max_retries || ""} placeholder={String(config.tracking_max_retries)} min={1} max={20} onChange={update} />
          </SettingsSection>
          </>)}
          <div className="settings-footer">
            <span>鐗堟湰 {config.version}</span>
            <span>{saving ? "姝ｅ湪淇濆瓨" : "淇敼鍚庝娇鐢ㄩ〉闈㈤《閮ㄧ殑淇濆瓨鎸夐挳"}</span>
          </div>
          {message && <div className="notice">{message}</div>}
        </form>
      )}
      {cookieHelpOpen && (
        <div className="modal-backdrop" onClick={() => setCookieHelpOpen(false)}>
          <article className="settings-help-modal" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => setCookieHelpOpen(false)} title="鍏抽棴">脳</button>
            <Info size={28} weight="fill" />
            <h2>115 Cookie 鑾峰彇鏂瑰紡</h2>
            <p>MediaIndex 鍙互鐩存帴浣跨敤 Cookie锛屼篃鍙互浠?OpenList 瀵煎叆 115 鎴?115 Open 鍑嵁銆侰ookie 蹇呴』鍖呭惈 UID銆丆ID銆丼EID銆?/p>
            <ol>
              <li><strong>鐩存帴绮樿创锛?/strong>鐧诲綍 115 缃戦〉绔紝鎸?OpenList 鏂囨。涓殑 Cookie 鑾峰彇璇存槑鍙栧緱 Cookie锛屽啀绮樿创鍒拌繖閲屻€?/li>
              <li><strong>浠?OpenList 瀵煎叆锛?/strong>鍏堜繚瀛?OpenList 鍦板潃鍜?Token锛屽啀鍒扮綉鐩樿缃偣鍑烩€滀粠 OpenList 瀵煎叆鈥濄€?/li>
            </ol>
            <p className="settings-help">Cookie 绛夊悓璐﹀彿鐧诲綍鍑嵁锛屽彧浼氫繚瀛樺湪 MediaIndex 鏈嶅姟绔紱涓嶈鎴浘銆佽浆鍙戞垨鎻愪氦鍒?Git銆?/p>
            <a className="primary compact-action settings-help-link" href="https://docs.openlist.team/zh/guide/drivers/115" target="_blank" rel="noreferrer">
              鏌ョ湅 OpenList 115 鑾峰彇鏂囨。 <ArrowSquareOut size={16} />
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

function SettingsSection({ title, body, children }: { title: string; body: string; children: React.ReactNode }) {
  return (
    <section className="settings-section">
      <header>
        <strong>{title}</strong>
        <span>{body}</span>
      </header>
      <div className="settings-section-body">{children}</div>
    </section>
  );
}

function normalizeOpenListPath(value: string) {
  const parts = String(value || "").replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length ? `/${parts.join("/")}` : "/";
}

function normalizeCategoryInputPath(value: string) {
  const parts = String(value || "").replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length ? `/${parts.join("/")}` : "/";
}

function OpenListDirectoryPicker({
  label,
  onClose,
  onSelect,
}: {
  label: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const [path, setPath] = useState("/");
  const [directories, setDirectories] = useState<{ name: string; is_dir: boolean }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextPath: string) {
    setLoading(true);
    setError("");
    try {
      const result = await api.browseOpenList(nextPath);
      setPath(result.path);
      setDirectories(result.directories);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "璇诲彇 OpenList 鐩綍澶辫触");
      setDirectories([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("/");
  }, []);

  function parentPath() {
    if (path === "/") return "/";
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    return parts.length ? `/${parts.join("/")}` : "/";
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="directory-picker-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="鍏抽棴">脳</button>
        <div className="directory-picker-heading">
          <div>
            <h2>閫夋嫨{label}</h2>
            <p>閫氳繃 OpenList Token 璇诲彇鍙闂殑鐩綍銆?/p>
          </div>
          <FolderOpen size={28} aria-hidden />
        </div>
        <div className="directory-picker-path" title={path}>{path}</div>
        <div className="directory-picker-actions">
          <button type="button" className="ghost compact-action" onClick={() => void load("/")} disabled={loading || path === "/"}>鏍圭洰褰?/button>
          <button type="button" className="ghost compact-action" onClick={() => void load(parentPath())} disabled={loading || path === "/"}>杩斿洖涓婄骇</button>
          <button type="button" className="primary compact-action" onClick={() => onSelect(path)} disabled={loading}>閫夋嫨褰撳墠鐩綍</button>
        </div>
        {loading && <div className="directory-picker-empty">璇诲彇涓€?/div>}
        {!loading && error && <div className="settings-inline-result error">{error}</div>}
        {!loading && !error && !directories.length && <div className="directory-picker-empty">褰撳墠鐩綍娌℃湁鍙繘鍏ョ殑瀛愮洰褰?/div>}
        {!loading && !error && directories.length > 0 && (
          <div className="directory-picker-list">
            {directories.map((directory) => {
              const nextPath = `${path === "/" ? "" : path}/${directory.name}`;
              return (
                <button type="button" className="directory-picker-item" key={nextPath} onClick={() => void load(nextPath)}>
                  <FolderOpen size={19} />
                  <span>{directory.name}</span>
                  <CaretRight size={17} />
                </button>
              );
            })}
          </div>
        )}
      </article>
    </div>
  );
}

function ProviderDirectoryPicker({
  provider,
  label,
  startPath,
  onClose,
  onSelect,
}: {
  provider: "qas" | "p115";
  label: string;
  startPath: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const [path, setPath] = useState(normalizeOpenListPath(startPath || "/"));
  const [directories, setDirectories] = useState<{ name: string; is_dir: boolean }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextPath: string) {
    setLoading(true);
    setError("");
    try {
      const result = await api.browseProviderPath(provider, normalizeOpenListPath(nextPath));
      setPath(result.path);
      setDirectories(result.directories);
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "璇诲彇缃戠洏鐩綍澶辫触");
      setDirectories([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(normalizeOpenListPath(startPath || "/"));
  }, [provider, startPath]);

  function parentPath() {
    if (path === "/") return "/";
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    return parts.length ? `/${parts.join("/")}` : "/";
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="directory-picker-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="鍏抽棴">脳</button>
        <div className="directory-picker-heading">
          <div>
            <h2>閫夋嫨{label}</h2>
            <p>閫氳繃宸查厤缃殑缃戠洏鍑嵁璇诲彇鐩綍銆?/p>
          </div>
          <FolderOpen size={28} aria-hidden />
        </div>
        <div className="directory-picker-path" title={path}>{path}</div>
        <div className="directory-picker-actions">
          <button type="button" className="ghost compact-action" onClick={() => void load("/")} disabled={loading || path === "/"}>鏍圭洰褰?/button>
          <button type="button" className="ghost compact-action" onClick={() => void load(parentPath())} disabled={loading || path === "/"}>杩斿洖涓婄骇</button>
          <button type="button" className="primary compact-action" onClick={() => onSelect(path)} disabled={loading}>閫夋嫨褰撳墠鐩綍</button>
        </div>
        {loading && <div className="directory-picker-empty">璇诲彇涓€?/div>}
        {!loading && error && <div className="settings-inline-result error">{error}</div>}
        {!loading && !error && !directories.length && <div className="directory-picker-empty">褰撳墠鐩綍娌℃湁鍙繘鍏ョ殑瀛愮洰褰?/div>}
        {!loading && !error && directories.length > 0 && (
          <div className="directory-picker-list">
            {directories.map((directory) => {
              const nextPath = `${path === "/" ? "" : path}/${directory.name}`;
              return (
                <button type="button" className="directory-picker-item" key={nextPath} onClick={() => void load(nextPath)}>
                  <FolderOpen size={19} />
                  <span>{directory.name}</span>
                  <CaretRight size={17} />
                </button>
              );
            })}
          </div>
        )}
      </article>
    </div>
  );
}

type OpenListSortKey = "name" | "type" | "time";
type OpenListSortState = { key: OpenListSortKey; direction: "asc" | "desc" };

function OpenListManualSync({ qasPath, p115Path, enabled, copyDisabled = false, copyDisabledReason = "" }: { qasPath: string; p115Path: string; enabled: boolean; copyDisabled?: boolean; copyDisabledReason?: string }) {
  const [leftPath, setLeftPath] = useState(qasPath || "/");
  const [rightPath, setRightPath] = useState(p115Path || "/");
  const [leftEntries, setLeftEntries] = useState<OpenListEntry[]>([]);
  const [rightEntries, setRightEntries] = useState<OpenListEntry[]>([]);
  const [leftSelected, setLeftSelected] = useState<string[]>([]);
  const [rightSelected, setRightSelected] = useState<string[]>([]);
  const [leftSort, setLeftSort] = useState<OpenListSortState>({ key: "type", direction: "asc" });
  const [rightSort, setRightSort] = useState<OpenListSortState>({ key: "type", direction: "asc" });
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function load(path: string, side: "left" | "right") {
    try {
      const result = await api.listOpenListEntries(path);
      if (side === "left") { setLeftPath(result.path); setLeftEntries(result.entries); setLeftSelected([]); }
      else { setRightPath(result.path); setRightEntries(result.entries); setRightSelected([]); }
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "璇诲彇 OpenList 鐩綍澶辫触");
    }
  }

  useEffect(() => {
    if (enabled) { void load(leftPath, "left"); void load(rightPath, "right"); }
  }, [enabled]);

  function parent(path: string) {
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    return parts.length ? `/${parts.join("/")}` : "/";
  }

  function toggleSort(side: "left" | "right", key: OpenListSortKey) {
    const setSort = side === "left" ? setLeftSort : setRightSort;
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }

  function sortedEntries(entries: OpenListEntry[], sort: OpenListSortState) {
    return [...entries].sort((a, b) => {
      let result = 0;
      if (sort.key === "type") {
        result = Number(b.is_dir) - Number(a.is_dir);
      } else if (sort.key === "time") {
        result = Date.parse(a.modified || "") - Date.parse(b.modified || "");
      } else {
        result = a.name.localeCompare(b.name, "zh-CN", { numeric: true, sensitivity: "base" });
      }
      if (result === 0) result = a.name.localeCompare(b.name, "zh-CN", { numeric: true, sensitivity: "base" });
      return sort.direction === "asc" ? result : -result;
    });
  }

  function formatEntryTime(value?: string) {
    if (!value) return "";
    const timestamp = Date.parse(value);
    if (Number.isNaN(timestamp)) return value;
    return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(timestamp));
  }

  async function copy(direction: "left-to-right" | "right-to-left") {
    if (copyDisabled) {
      setMessage(copyDisabledReason || "鎵嬪姩澶嶅埗鏆傛椂鍋滅敤");
      return;
    }
    const sourcePath = direction === "left-to-right" ? leftPath : rightPath;
    const targetPath = direction === "left-to-right" ? rightPath : leftPath;
    const names = direction === "left-to-right" ? leftSelected : rightSelected;
    if (!names.length) { setMessage("璇峰厛鍕鹃€夎澶嶅埗鐨勬枃浠舵垨鐩綍"); return; }
    setBusy(true); setMessage("");
    try {
      const result = await api.syncSelectedOpenList({ source_dir: sourcePath, target_dir: targetPath, names, overwrite });
      setMessage(result.message);
      if (result.ok) window.dispatchEvent(new Event("mediaindex:tasks-changed"));
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "鎻愪氦鍚屾澶辫触");
    } finally { setBusy(false); }
  }

  function column(title: string, path: string, entries: OpenListEntry[], selected: string[], setSelected: (value: string[]) => void, side: "left" | "right") {
    const sort = side === "left" ? leftSort : rightSort;
    const visibleEntries = sortedEntries(entries, sort);
    const sortOptions: { key: OpenListSortKey; label: string }[] = [
      { key: "name", label: "鏂囦欢鍚? },
      { key: "type", label: "绫诲瀷" },
      { key: "time", label: "鏃堕棿" },
    ];
    const toggleSelected = (name: string, checked?: boolean) => {
      const shouldSelect = checked ?? !selected.includes(name);
      setSelected(shouldSelect ? [...selected, name] : selected.filter((item) => item !== name));
    };
    return (
      <section className="openlist-sync-column">
        <header><strong>{title}</strong><code>{path}</code></header>
        <div className="openlist-sync-column-actions">
          <button type="button" className="ghost compact-action" onClick={() => void load(parent(path), side)} disabled={!enabled || path === "/" || busy}>杩斿洖涓婄骇</button>
          <button type="button" className="ghost compact-action" onClick={() => void load(path, side)} disabled={!enabled || busy}>鍒锋柊</button>
        <div className="openlist-sync-sortbar" aria-label={`${title}鎺掑簭`}>
          {sortOptions.map((option) => {
            const active = sort.key === option.key;
            const DirectionIcon = sort.direction === "asc" ? CaretUp : CaretDown;
            return (
              <button
                type="button"
                key={option.key}
                className={active ? "active" : ""}
                onClick={() => toggleSort(side, option.key)}
                title={`${option.label}${active && sort.direction === "desc" ? "鍊掑簭" : "姝ｅ簭"}`}
              >
                <span>{option.label}</span>
                {active && <DirectionIcon size={14} weight="bold" />}
              </button>
            );
          })}
        </div>
        </div>
        <div className="openlist-sync-entry-list">
          {!enabled && <p className="settings-help">璇峰厛鍚敤 OpenList 骞朵繚瀛?Token銆?/p>}
          {enabled && !entries.length && <p className="settings-help">褰撳墠鐩綍涓虹┖锛屾垨娌℃湁鍙鍙栫殑椤圭洰銆?/p>}
          {visibleEntries.map((entry) => (
            <div className="openlist-sync-entry" key={entry.name}>
              <input type="checkbox" checked={selected.includes(entry.name)} onChange={(event) => toggleSelected(entry.name, event.target.checked)} />
              <button
                type="button"
                className="openlist-sync-entry-main"
                title={entry.is_dir ? "杩涘叆鐩綍" : entry.name}
                onClick={() => {
                  if (entry.is_dir) void load(`${path === "/" ? "" : path}/${entry.name}`, side);
                  else toggleSelected(entry.name);
                }}
              >
                {entry.is_dir ? <FolderOpen size={18} /> : <File size={18} />}
                <span>{entry.name}</span>
              </button>
              {entry.modified && <time dateTime={entry.modified}>{formatEntryTime(entry.modified)}</time>}
            </div>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="openlist-manual-sync">
      <div className="openlist-sync-options">
        <span>宸插嬀閫夊悗澶嶅埗</span>
        <label><input type="radio" checked={!overwrite} onChange={() => setOverwrite(false)} />璺宠繃宸插瓨鍦?/label>
        <label><input type="radio" checked={overwrite} onChange={() => setOverwrite(true)} />瑕嗙洊宸插瓨鍦?/label>
      </div>
      {copyDisabled && <p className="settings-help">{copyDisabledReason}</p>}
      <div className="openlist-sync-columns">
        {column("澶稿厠濯掍綋搴?, leftPath, leftEntries, leftSelected, setLeftSelected, "left")}
        <div className="openlist-sync-arrows" aria-label="澶嶅埗鏂瑰悜">
          <button type="button" className="primary icon" title={copyDisabled ? copyDisabledReason : "浠庡じ鍏嬪鍒跺埌 115"} onClick={() => void copy("left-to-right")} disabled={!enabled || busy || copyDisabled}>鈫?/button>
          <button type="button" className="primary icon" title={copyDisabled ? copyDisabledReason : "浠?115 澶嶅埗鍒板じ鍏?} onClick={() => void copy("right-to-left")} disabled={!enabled || busy || copyDisabled}>鈫?/button>
        </div>
        {column("115 濯掍綋搴?, rightPath, rightEntries, rightSelected, setRightSelected, "right")}
      </div>
      {message && <div className="settings-inline-result">{message}</div>}
    </section>
  );
}

function buildConfigPayload(form: Record<string, string>) {
  const payload: Record<string, string | number | boolean | string[] | Record<string, string>> = {};
  const categoryPaths: Record<string, string> = {};
  const qasCategoryPaths: Record<string, string> = {};
  const p115CategoryPaths: Record<string, string> = {};
  Object.entries(form).forEach(([key, value]) => {
    if (key.startsWith("category_paths.")) {
      categoryPaths[key.replace("category_paths.", "")] = value.trim();
      return;
    }
    if (key.startsWith("qas_category_paths.")) {
      qasCategoryPaths[key.replace("qas_category_paths.", "")] = value.trim();
      return;
    }
    if (key.startsWith("p115_category_paths.")) {
      p115CategoryPaths[key.replace("p115_category_paths.", "")] = value.trim();
      return;
    }
    if (!value.trim() && key !== "proxy_url") return;
    if (["wishlist_scheduler_enabled", "tracking_scheduler_enabled", "notification_external_enabled", "telegram_enabled", "wecom_enabled", "season_subdirectory_enabled", "openlist_enabled", "openlist_auto_sync"].includes(key)) {
      payload[key] = value === "true";
      return;
    }
    if (["wishlist_poll_minutes", "wishlist_default_check_hour", "tracking_poll_minutes", "tracking_retry_interval_minutes", "tracking_max_retries"].includes(key)) {
      payload[key] = Number(value);
      return;
    }
    if (key === "enabled_providers") {
      payload[key] = value.split(",").map((item) => item.trim()).filter(Boolean);
      return;
    }
    payload[key] = value.trim();
  });
  if (Object.keys(categoryPaths).length) {
    payload.category_paths = categoryPaths;
  }
  if (Object.keys(qasCategoryPaths).length) payload.qas_category_paths = qasCategoryPaths;
  if (Object.keys(p115CategoryPaths).length) payload.p115_category_paths = p115CategoryPaths;
  return payload;
}

function SettingsToggle({
  label,
  help,
  value,
  onChange,
  trueLabel = "寮€",
  falseLabel = "鍏?,
  disabled = false,
  busy = false,
}: {
  label: string;
  help?: string;
  value: boolean;
  onChange: (value: boolean) => void;
  trueLabel?: string;
  falseLabel?: string;
  disabled?: boolean;
  busy?: boolean;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  return (
    <div className="settings-field">
      <span className="settings-label">
        {label}
        {help && (
          <span className="inline-help-wrap">
            <button
              type="button"
              className="inline-help"
              aria-label={`${label}璇存槑`}
              aria-expanded={helpOpen}
              onClick={() => setHelpOpen((current) => !current)}
              onBlur={() => window.setTimeout(() => setHelpOpen(false), 120)}
            >
              <Question size={15} weight="bold" />
            </button>
            <span className={`inline-help-popover ${helpOpen ? "open" : ""}`} role="tooltip">{help}</span>
          </span>
        )}
      </span>
      <div className="toggle-group" role="group" aria-label={label}>
        <button type="button" className={value ? "active" : ""} onClick={() => onChange(true)} disabled={disabled}>
          {busy && value && <Spinner />}
          {trueLabel}
        </button>
        <button type="button" className={!value ? "active" : ""} onClick={() => onChange(false)} disabled={disabled}>
          {busy && !value && <Spinner />}
          {falseLabel}
        </button>
      </div>
    </div>
  );
}

const defaultCategoryRows = [
  ["movie", "鐢靛奖"],
  ["tv", "鐢佃鍓?],
  ["variety", "缁艰壓"],
  ["concert", "婕斿敱浼?],
  ["documentary", "绾綍鐗?],
  ["anime", "鍔ㄦ极"],
] as const;

const defaultCategoryPaths: Record<string, string> = {
  movie: "/01鐢靛奖",
  tv: "/03鐢佃鍓?,
  variety: "/04缁艰壓",
  concert: "/05婕斿敱浼?,
  documentary: "/06绾綍鐗?,
  anime: "/12鍔ㄦ极",
};

function CategoryPathSettings({
  config,
  form,
  onChange,
  provider = "qas",
  canPickPath = false,
  onPickPath,
}: {
  config: ConfigStatus;
  form: Record<string, string>;
  onChange: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  provider?: "qas" | "p115";
  canPickPath?: boolean;
  onPickPath?: (key: string, label: string) => void;
}) {
  const prefix = `${provider}_category_paths`;
  const configured = provider === "p115" ? config.p115_category_paths : config.qas_category_paths;
  const [visibleKeys, setVisibleKeys] = useState<string[]>(() => {
    const configuredKeys = Object.keys(configured || {});
    return [
      ...defaultCategoryRows.map(([key]) => key).filter((key) => configuredKeys.includes(key)),
      ...configuredKeys.filter((key) => !defaultCategoryRows.some(([known]) => known === key)),
    ];
  });
  function updatePath(key: string, value: string) {
    onChange((current) => ({ ...current, [`${prefix}.${key}`]: value }));
  }
  function currentPath(key: string) {
    return form[`${prefix}.${key}`] ?? configured?.[key] ?? defaultCategoryPaths[key] ?? `/${key}`;
  }
  function removePath(key: string) {
    if (visibleKeys.length <= 1) return;
    const remaining = visibleKeys.filter((item) => item !== key);
    onChange((current) => {
      const next = { ...current, [`${prefix}.${key}`]: "" };
      remaining.forEach((item) => {
        next[`${prefix}.${item}`] = current[`${prefix}.${item}`] ?? configured?.[item] ?? defaultCategoryPaths[item] ?? `/${item}`;
      });
      return next;
    });
    setVisibleKeys(remaining);
  }

  const cloudRoot = (
    provider === "p115"
      ? form.p115_root_path || config.p115_root_path
      : form.qas_save_path || config.qas_root || config.cloud_root
  ).replace(/\/$/, "");
  const localRoot = (form.local_save_path || config.local_root || "/涓嬭浇_鏈暣鐞?).replace(/\/$/, "");
  const tvCategory = (form[`${prefix}.variety`] || configured?.variety || "/tv").replace(/^\/?/, "/");

  return (
    <>
      <p className="muted">
        缁艰壓璺緞绀轰緥锛氱綉鐩?<code>{cloudRoot}{tvCategory}</code>锛涙湰鍦?<code>{localRoot}{tvCategory}</code>銆傚獟浣撳悕绉颁細缁х画杩藉姞鍦ㄥ悗闈€?
      </p>
      <div className="category-path-grid">
        {visibleKeys.map((key) => {
          const label = defaultCategoryRows.find(([known]) => known === key)?.[1] || key;
          const current = currentPath(key);
          return (
            <div className="category-path-field" key={key}>
              <label>
                <span>{label}</span>
                <input
                  value={current}
                  placeholder={current}
                  onChange={(event) => updatePath(key, event.target.value)}
                />
              </label>
              <button type="button" className="category-row-action pick" onClick={() => onPickPath?.(key, label)} disabled={!canPickPath || !onPickPath} title={`閫夋嫨${label}璺緞`} aria-label={`閫夋嫨${label}璺緞`}>
                <FolderOpen size={20} weight="bold" />
              </button>
              <button type="button" className="category-row-action remove" onClick={() => removePath(key)} disabled={visibleKeys.length <= 1} title={`鍒犻櫎${label}`} aria-label={`鍒犻櫎${label}`}>
                <MinusCircle size={21} weight="bold" />
              </button>
            </div>
          );
        })}
        <button type="button" className="category-add" onClick={() => {
          const key = window.prompt("鑷畾涔夊垎绫绘爣璇嗭紙濡?documentary锛?)?.trim();
          if (key && /^[a-zA-Z0-9_-]+$/.test(key) && !visibleKeys.includes(key)) {
            setVisibleKeys((current) => [...current, key]);
            updatePath(key, `/${key}`);
          }
        }}>
          <PlusCircle size={22} weight="bold" />
          <span>鑷畾涔夊垎绫?/span>
        </button>
      </div>
    </>
  );
}

function SettingsNumberInput({
  label,
  name,
  value,
  placeholder,
  min,
  max,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  placeholder: string;
  min: number;
  max: number;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <input
        type="number"
        inputMode="numeric"
        value={value}
        placeholder={`${placeholder}锛岃寖鍥?${min}-${max}`}
        min={min}
        max={max}
        onChange={(event) => onChange(name, event.target.value)}
      />
    </label>
  );
}

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="filter-row">
      <span>{label}</span>
      {children}
    </div>
  );
}

function ProviderConnectionStatus({ connected, label }: { connected: boolean; label: string }) {
  const text = connected ? `${label} 宸茶繛鎺 : `${label} 鏈繛鎺;
  return (
    <span className={`provider-connection-status ${connected ? "connected" : "disconnected"}`} title={text} aria-label={text}>
      {connected ? <CheckCircle size={20} weight="fill" /> : <WarningCircle size={20} weight="fill" />}
    </span>
  );
}

function SettingsInput({
  label,
  name,
  value,
  saved,
  help,
  helpTooltip,
  secret,
  placeholder,
  showSavedValue,
  onChange,
  action,
  result,
}: {
  label: string;
  name: string;
  value: string;
  saved: boolean;
  help?: string;
  helpTooltip?: string;
  secret?: boolean;
  placeholder?: string;
  showSavedValue?: boolean;
  onChange: (key: string, value: string) => void;
  action?: React.ReactNode;
  result?: { ok: boolean; message: string } | null;
}) {
  const savedPlaceholder = savedInputPlaceholder(name, placeholder, Boolean(showSavedValue), Boolean(secret));
  return (
    <div className="settings-field">
      <span className="settings-label">{label}{helpTooltip && <InlineHelp label={label} text={helpTooltip} />}{help && <small className="settings-field-help">{help}</small>}</span>
      <div className="settings-input-content">
        <div className="settings-input-action">
          <input
            aria-label={label}
            type={secret ? "password" : "text"}
            value={value}
            placeholder={saved ? savedPlaceholder : placeholder || "鏈厤缃?}
            onChange={(event) => onChange(name, event.target.value)}
          />
          {action}
        </div>
        {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
      </div>
    </div>
  );
}

function InlineHelp({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="inline-help-wrap">
      <button type="button" className="inline-help" aria-label={`${label}璇存槑`} aria-expanded={open} onClick={() => setOpen((current) => !current)} onBlur={() => window.setTimeout(() => setOpen(false), 120)}>
        <Question size={15} weight="bold" />
      </button>
      <span className={`inline-help-popover ${open ? "open" : ""}`} role="tooltip">{text}</span>
    </span>
  );
}

function savedInputPlaceholder(name: string, placeholder = "", showSavedValue = false, secret = false) {
  if (!showSavedValue || !placeholder) return "宸蹭繚瀛橈紝濡傞渶淇敼璇烽噸鏂板～鍐?;
  const shouldMask = secret
    || /^https?:\/\//i.test(placeholder)
    || /(token|cookie|secret|key|url|host|base_url)/i.test(name);
  if (shouldMask) return "宸蹭繚瀛橈紝濡傞渶淇敼璇烽噸鏂板～鍐?;
  return `${placeholder}锛屽闇€淇敼璇烽噸鏂板～鍐檂;
}

function Segmented({
  value,
  items,
  onChange,
}: {
  value: string;
  items: readonly (readonly [string, string])[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="segmented">
      {items.map(([key, label]) => (
        <button key={key} className={value === key ? "active" : ""} onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Poster({ item, compact = false }: { item: MediaItem; compact?: boolean }) {
  return (
    <div className={compact ? "poster compact" : "poster"}>
      {item.poster_url ? <img src={item.poster_url} alt={item.title} loading="lazy" /> : <span>{item.title.slice(0, 2)}</span>}
      {Boolean(item.vote_average) && <b className="rating-badge">{rating(item.vote_average)}</b>}
    </div>
  );
}

function PosterSkeleton() {
  return (
    <div className="poster-grid">
      {Array.from({ length: 12 }).map((_, index) => (
        <div className="poster-card skeleton-card" key={index}>
          <div className="poster shimmer" />
          <div className="line shimmer" />
          <div className="line short shimmer" />
        </div>
      ))}
    </div>
  );
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

function rating(value?: number) {
  if (!value) return "";
  return value.toFixed(1);
}

createRoot(document.getElementById("root")!).render(<App />);
