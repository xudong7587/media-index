import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowClockwise,
  ArrowSquareOut,
  CaretDown,
  CaretLeft,
  CaretRight,
  Check,
  CheckCircle,
  CheckSquare,
  CloudArrowDown,
  HardDrives,
  Heart,
  MagnifyingGlass,
  Moon,
  Pause,
  Play,
  SignOut,
  Sun,
  Trash,
} from "@phosphor-icons/react";
import { api, ConfigStatus, Genre, MediaItem, ResourceStatus, ReviewCandidate, TrackingTask, TransferJob, WishlistItem } from "./lib/api";
import "./styles.css";

type Page = "discover" | "tracking" | "wishlist" | "review" | "settings";
type Theme = "light" | "dark";

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
  const [page, setPage] = useState<Page>(() => (window.location.hash === "#review" ? "review" : "discover"));
  const nav = [
    ["discover", "发现"],
    ["tracking", "智能追更"],
    ["wishlist", "愿望单"],
    ["review", "待确认"],
    ["settings", "设置"],
  ] as const;

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
          <button className="icon" onClick={() => setTheme(theme === "light" ? "dark" : "light")} title="切换主题">
            {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <button className="icon" onClick={logout} title="退出">
            <SignOut size={18} />
          </button>
        </div>
      </header>
      <main className="content">
        {page === "discover" && <DiscoverPage />}
        {page === "tracking" && <TrackingPage />}
        {page === "wishlist" && <WishlistPage />}
        {page === "review" && <ReviewPage />}
        {page === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}

function DiscoverPage() {
  const [mediaType, setMediaType] = useState<"movie" | "tv" | "variety">("movie");
  const [region, setRegion] = useState("");
  const [sort, setSort] = useState("hot");
  const [genre, setGenre] = useState("");
  const [genres, setGenres] = useState<Genre[]>([]);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<MediaItem | null>(null);
  const [discoverPage, setDiscoverPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [genreExpanded, setGenreExpanded] = useState(false);

  async function load(page = discoverPage) {
    setLoading(true);
    setError("");
    try {
      const res = query.trim() ? await api.search(query.trim()) : await api.discover(mediaType, region, sort, genre, 0, page);
      setItems(res.results || []);
      setTotalPages("total_pages" in res && typeof res.total_pages === "number" ? res.total_pages || 1 : 1);
      if ("page" in res && typeof res.page === "number") setDiscoverPage(res.page);
      if ("error" in res && res.error) setError("TMDB 尚未配置");
    } catch {
      setError("加载失败");
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

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>发现</h1>
          <p>从 TMDB 发现内容，确认后交给 QAS 执行转存。</p>
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
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索电影、剧集、综艺" />
        </form>
      </div>

      <div className="toolbar">
        <Segmented
          value={mediaType}
          items={[
            ["movie", "电影"],
            ["tv", "剧集"],
            ["variety", "综艺"],
          ]}
          onChange={(value) => setMediaType(value as "movie" | "tv" | "variety")}
        />
        <Segmented
          value={region}
          items={[
            ["", "全部"],
            ["cn", "华语"],
          ]}
          onChange={setRegion}
        />
        <button className="ghost" onClick={() => void load(discoverPage)}>
          <ArrowClockwise size={16} />
          刷新
        </button>
      </div>
      <div className="filter-panel">
        <FilterRow label="排序">
          <Segmented
            value={sort}
            items={[
              ["latest", "最新"],
              ["hot", "热门"],
              ["rating", "评分"],
            ]}
            onChange={setSort}
          />
        </FilterRow>
        <FilterRow label="风格">
          <div className="genre-filter">
            <button className="genre-toggle" onClick={() => setGenreExpanded((value) => !value)} aria-expanded={genreExpanded}>
              <CaretDown size={15} className={genreExpanded ? "expanded" : ""} />
              {genreExpanded ? "收起风格" : "展开风格"}
              {!genreExpanded && genre && <span>{genres.find((item) => String(item.id) === genre)?.name}</span>}
            </button>
            {genreExpanded && (
              <div className="chip-row">
                <button className={genre === "" ? "chip active" : "chip"} onClick={() => setGenre("")}>
                  全部
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
      {!loading && error && <Empty title={error} body="请到设置页确认 TMDB 配置。" />}
      {!loading && !error && items.length === 0 && <Empty title="没有结果" body="换个关键词或分类试试。" />}
      {!loading && !error && (
        <>
          <div className="poster-grid">
            {items.map((item) => (
              <button className="poster-card" key={`${item.media_type}-${item.tmdb_id}`} onClick={() => setSelected(item)}>
                <Poster item={item} />
                <span className="poster-title">{item.title}</span>
                <span className="poster-meta">{item.release_date ? `发行 ${item.release_date}` : item.year ? `发行 ${item.year}` : "发行日期待定"}</span>
              </button>
            ))}
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
      {selected && <MediaDialog item={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}

function MediaDialog({ item, onClose }: { item: MediaItem; onClose: () => void }) {
  const [detail, setDetail] = useState<MediaItem | null>(null);
  const [selectedSeasons, setSelectedSeasons] = useState<number[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"" | "cloud" | "local">("");
  const [completed, setCompleted] = useState<"" | "cloud" | "local">("");
  const [seasonResources, setSeasonResources] = useState<Record<number, ResourceStatus>>({});
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceSeason, setResourceSeason] = useState(0);
  const [resourceStage, setResourceStage] = useState(0);
  const [trackingTasks, setTrackingTasks] = useState<TrackingTask[]>([]);
  const [progressStage, setProgressStage] = useState("");
  const [progressSeason, setProgressSeason] = useState(0);
  const [progressIndex, setProgressIndex] = useState(0);

  useEffect(() => {
    api.details(item.media_type, item.tmdb_id).then((data) => {
      setDetail(data);
      const latest = data.seasons?.at(-1)?.season_number ?? 1;
      setSelectedSeasons([latest]);
      const seasonNumbers = (data.seasons || []).map((season) => season.season_number).filter((number) => number > 0);
      void Promise.all(
        (seasonNumbers.length ? seasonNumbers : [0]).map(async (number) => [number, await api.cachedResource(data, number || undefined)] as const),
      ).then((entries) => {
        setSeasonResources((current) => {
          const next = { ...current };
          for (const [number, status] of entries) if (status) next[number] = status;
          return next;
        });
      });
    });
  }, [item]);

  const media = detail || item;
  const canTrack = media.media_type === "tv" || media.media_type === "variety";
  const isOngoing = canTrack && media.status !== "Ended";
  const seasons = (media.seasons || []).filter((value) => value.season_number > 0);
  const latestSeason = seasons.at(-1)?.season_number ?? 1;
  const orderedSelection = [...selectedSeasons].sort((a, b) => a - b);
  const allSeasonsSelected = seasons.length > 0 && orderedSelection.length === seasons.length;
  const resourceSelection = canTrack ? (allSeasonsSelected ? orderedSelection : [orderedSelection.at(-1) ?? latestSeason]) : [0];
  const selectedResourceStatuses = resourceSelection.map((number) => seasonResources[number]).filter(Boolean);
  const foundSeasonCount = selectedResourceStatuses.filter((value) => value.found).length;
  const allResourcesFound = resourceSelection.length > 0 && foundSeasonCount === resourceSelection.length;
  const anyRequiresReview = selectedResourceStatuses.some((value) => value.requires_review);
  const isTracked = canTrack && orderedSelection.some((number) => trackingTasks.some((task) => task.tmdb_id === media.tmdb_id && task.season_number === number));
  const canSave = allResourcesFound && !resourceLoading && !busy && !completed && !isTracked;

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
    if (!detail) return;
    let cancelled = false;
    setResourceLoading(true);
    const lastSelected = orderedSelection.at(-1) ?? latestSeason;
    const targets = canTrack
      ? allSeasonsSelected
        ? [lastSelected, ...orderedSelection.filter((number) => number !== lastSelected)]
        : [lastSelected]
      : [0];
    async function inspectTargets() {
      for (const number of targets) {
        if (cancelled) return;
        setResourceSeason(number);
        let result: ResourceStatus;
        try {
          result = await api.resources(media, canTrack ? number : undefined);
        } catch {
          result = { ok: false, found: false, message: "资源搜索失败" };
        }
        if (!cancelled) setSeasonResources((current) => ({ ...current, [number]: result }));
      }
    }
    void inspectTargets()
      .finally(() => {
        if (!cancelled) {
          setResourceSeason(0);
          setResourceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [detail, media.media_type, media.tmdb_id, selectedSeasons.join(","), canTrack, allSeasonsSelected, latestSeason]);

  function toggleSeason(number: number) {
    setCompleted("");
    setSelectedSeasons((current) => {
      if (!current.includes(number)) return [...current, number].sort((a, b) => a - b);
      if (current.length === 1) return current;
      return current.filter((value) => value !== number);
    });
  }

  function selectAllSeasons() {
    setCompleted("");
    setSelectedSeasons(seasons.map((value) => value.season_number));
  }

  async function transfer(target: "cloud" | "local") {
    setBusy(target);
    setProgressStage("tmdb_resolving");
    setMessage("");
    setProgressIndex(0);
    try {
      const results: TransferJob[] = [];
      for (const [index, seasonNumber] of orderedSelection.entries()) {
        setProgressSeason(seasonNumber);
        setProgressIndex(index + 1);
        const started = await api.createTransfer(media, target, canTrack ? seasonNumber : undefined);
        const result = await waitForTransfer(started.id, (job) => setProgressStage(job.stage));
        results.push(result);
        const transferOk = result.status === "done" || result.status === "triggered";
        if (transferOk && isOngoing && seasonNumber === latestSeason) {
          await api.createTracking(media, seasonNumber, target);
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
      setProgressIndex(0);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="media-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">
          ×
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
                <button className={`season-select-all ${allSeasonsSelected ? "active" : ""}`} onClick={selectAllSeasons} aria-label="全选季度" title="全选季度">
                  <CheckSquare size={16} weight={allSeasonsSelected ? "fill" : "regular"} />
                  <span>全选</span>
                </button>
                {seasons.map((s) => {
                  const selected = selectedSeasons.includes(s.season_number);
                  const isTransferring = Boolean(busy) && progressSeason === s.season_number;
                  const isInspecting = resourceLoading && resourceSeason === s.season_number;
                  const resource = seasonResources[s.season_number];
                  const resourceState = isInspecting ? "验证中" : resource?.found ? "已找到" : resource ? "未找到" : "待验证";
                  return (
                    <button
                      key={s.season_number}
                      className={`${selected ? "selected" : ""} ${resource?.found ? "verified" : ""}`}
                      onClick={() => toggleSeason(s.season_number)}
                      aria-pressed={selected}
                    >
                      {isTransferring || isInspecting ? <Spinner /> : selected && <Check size={13} weight="bold" />}
                      <span>S{s.season_number}</span>
                      <em>{resourceState}</em>
                    </button>
                  );
                })}
              </div>
            )}
            <p>{media.overview || "暂无简介。"}</p>
            {isTracked && <div className="tracking-lock"><CheckCircle size={17} /> 选中的季度中有已加入智能追更的项目</div>}
            <div className="action-row">
              <button className="primary action-button" onClick={() => transfer("cloud")} disabled={!canSave}>
                {completed === "cloud" ? <CheckCircle size={18} /> : busy === "cloud" ? <Spinner /> : <CloudArrowDown size={18} />}
                <span>{completed === "cloud" ? "已完成" : busy === "cloud" ? `${progressSeason ? `S${progressSeason} ` : ""}${transferStageLabel(progressStage)}${orderedSelection.length > 1 ? ` ${progressIndex}/${orderedSelection.length}` : ""}` : "存网盘"}</span>
              </button>
              <button className="secondary action-button" onClick={() => transfer("local")} disabled={!canSave}>
                {completed === "local" ? <CheckCircle size={18} /> : busy === "local" ? <Spinner /> : <HardDrives size={18} />}
                <span>{completed === "local" ? "已完成" : busy === "local" ? `${progressSeason ? `S${progressSeason} ` : ""}${transferStageLabel(progressStage)}${orderedSelection.length > 1 ? ` ${progressIndex}/${orderedSelection.length}` : ""}` : "存本地"}</span>
              </button>
              <button
                className={`ghost action-button resource-button ${allResourcesFound ? "found" : ""} ${resourceLoading ? "loading" : ""}`}
                disabled={resourceLoading || Boolean(busy)}
                title={canTrack ? resourceSelection.map((number) => `S${number}: ${seasonResources[number]?.message || "等待检查"}`).join("\n") : seasonResources[0]?.message || ""}
                onClick={() => {
                  if (!allResourcesFound) {
                    const missing = resourceSelection.filter((number) => !seasonResources[number]?.found);
                    void Promise.all(missing.map((number) => api.addWishlist(media, canTrack ? number : undefined))).then(() =>
                      setMessage(`已将 ${missing.length} 个暂无资源的季度加入愿望单。`),
                    );
                  }
                }}
              >
                {resourceLoading ? <Spinner /> : allResourcesFound ? <CheckCircle size={18} /> : <Heart size={18} />}
                <span>{resourceLoading ? resourceSearchLabel(resourceStage) : canTrack ? anyRequiresReview ? `找到 ${foundSeasonCount}/${resourceSelection.length} 季，部分需确认` : allResourcesFound ? `已找到 ${foundSeasonCount}/${resourceSelection.length} 季资源` : `找到 ${foundSeasonCount}/${resourceSelection.length} 季，加入缺失愿望单` : allResourcesFound ? "已找到资源" : "暂无资源，加入愿望单"}</span>
              </button>
            </div>
            {message && <div className="notice">{message}</div>}
          </div>
        </div>
      </article>
    </div>
  );
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

function resourceSearchLabel(stage: number) {
  return ["正在获取媒体信息，请勿关闭卡片", "正在获取 PanSou 资源，请勿关闭卡片", "正在验证链接有效性，请勿关闭卡片", "正在与 TMDB 核对，请勿关闭卡片"][stage] || "正在搜索资源，请勿关闭卡片";
}

function WishlistPage() {
  const [items, setItems] = useState<WishlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [scheduleOpen, setScheduleOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

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
    await api.deleteWishlist(item.id);
    await load();
  }

  async function setCheckHour(item: WishlistItem, hour: number) {
    setBusy(item.id);
    try {
      await api.updateWishlistSchedule(item.id, hour);
      setScheduleOpen(null);
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function runNow(item: WishlistItem) {
    setBusy(item.id);
    try {
      await api.runWishlist(item.id);
      await load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>愿望单</h1>
          <p>暂时没有资源的影片会先放在这里，后续按设置自动巡检。</p>
        </div>
        <button className="ghost" onClick={() => void load()}>
          <ArrowClockwise size={16} />
          刷新
        </button>
      </div>
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
              <p>{[item.year, mediaTypeLabel(item.media_type), `加入时间 ${item.created_at?.slice(0, 10)}`].filter(Boolean).join(" / ")}</p>
              <p>
                {item.tmdb_date ? `TMDB 日期 ${item.tmdb_date}` : "等待 TMDB 更新日期"}
                {item.next_check_at ? ` / 下次检查 ${formatTrackingTime(item.next_check_at)}` : ""}
              </p>
              {item.last_error && <p className="danger">{item.last_error}</p>}
            </div>
            <div className="row-actions">
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
              <button className="icon" title="立即检查" onClick={() => void runNow(item)} disabled={busy === item.id}>
                <ArrowClockwise size={16} />
              </button>
              <button className="icon danger-icon" title="删除" onClick={() => void remove(item)}>
                <Trash size={16} />
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function TrackingPage() {
  const [items, setItems] = useState<TrackingTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [taskAction, setTaskAction] = useState("");

  async function load() {
    setLoading(true);
    try {
      setItems(await api.tracking());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function toggleTask(task: TrackingTask) {
    if (task.status === "paused") {
      await api.resumeTracking(task.id);
    } else {
      await api.pauseTracking(task.id);
    }
    await load();
  }

  async function deleteTask(task: TrackingTask) {
    if (!window.confirm(`删除「${task.title}」的追更任务？`)) return;
    await api.deleteTracking(task.id);
    await load();
  }

  async function runTask(task: TrackingTask) {
    setTaskAction(`run:${task.id}`);
    try {
      await api.runTracking(task.id);
      await load();
    } finally {
      setTaskAction("");
    }
  }

  async function refreshTaskStorage(task: TrackingTask) {
    setTaskAction(`refresh:${task.id}`);
    try {
      await api.refreshTrackingStorage(task.id);
      await load();
    } finally {
      setTaskAction("");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>智能追更</h1>
          <p>系统根据 TMDB 播出日复验旧链接；缺集或失效时才通过 PanSou 换源。</p>
        </div>
        <button className="ghost" onClick={() => void load()}>
          <ArrowClockwise size={16} />
          刷新
        </button>
      </div>
      {loading && <div className="list-skeleton" />}
      {!loading && items.length === 0 && <Empty title="还没有追更任务" body="连载剧集点存网盘或存本地后，会自动出现在这里。" />}
      <div className="task-list">
        {items.map((task) => (
          <article className="task-row" key={task.id}>
            <Poster item={taskToMedia(task)} compact />
            <div className="task-main">
              <div className="task-title-line">
                <h3>{task.title}</h3>
                <span className={`status ${task.status}`}>{task.status === "paused" ? "已暂停" : "运行中"}</span>
              </div>
              <p className="task-overview">{task.overview || "暂无简介。"}</p>
              <p>{[task.year, mediaTypeLabel(task.media_type), `S${task.season_number}`, task.save_path].filter(Boolean).join(" / ")}</p>
              <p>
                进度：已确认 {task.saved_count || 0} 集 / 已触发 {task.triggered_count || 0} 集 / 共 {task.episode_count || 0} 集
              </p>
              <p>
                {task.next_check_at ? `下次巡检：${formatTrackingTime(task.next_check_at)}` : trackingStateLabel(task.decision_state)}
              </p>
              <p>
                夸克已存：{task.last_saved_episode ? `S${String(task.season_number).padStart(2, "0")}E${String(task.last_saved_episode).padStart(2, "0")}` : "尚未识别"}
                {task.last_storage_check_at ? ` / ${formatTrackingTime(task.last_storage_check_at)} 刷新` : ""}
              </p>
              {task.storage_check_message && <p className="muted task-storage-message">{task.storage_check_message}</p>}
              {task.last_error && <p className="danger">{task.last_error}</p>}
            </div>
            <div className="row-actions">
              <button className="icon" title="刷新夸克已存的最后一集" onClick={() => void refreshTaskStorage(task)} disabled={Boolean(taskAction)}>
                {taskAction === `refresh:${task.id}` ? <Spinner /> : <ArrowClockwise size={16} />}
              </button>
              <button className="icon" title="立即执行一次追更" onClick={() => void runTask(task)} disabled={task.status === "paused" || Boolean(taskAction)}>
                {taskAction === `run:${task.id}` ? <Spinner /> : <Play size={16} />}
              </button>
              <button className="icon" title={task.status === "paused" ? "恢复" : "暂停"} onClick={() => void toggleTask(task)}>
                {task.status === "paused" ? <Play size={16} /> : <Pause size={16} />}
              </button>
              <button className="icon danger-icon" title="删除" onClick={() => void deleteTask(task)}>
                <Trash size={16} />
              </button>
            </div>
          </article>
        ))}
      </div>
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

function transferStageLabel(stage: string) {
  const labels: Record<string, string> = {
    tmdb_resolving: "正在匹配 TMDB",
    validating_link: "正在检查旧链接",
    searching_sources: "正在搜索资源",
    matching_files: "正在匹配文件",
    preparing_names: "正在生成文件名",
    qas_transferring: "正在执行转存",
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
    triggered: "QAS 已触发",
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
    awaiting_confirmation: "QAS 已触发，等待结果确认",
    paused: "任务已暂停",
  };
  return labels[state || ""] || "暂无下一次巡检时间";
}

function ReviewPage() {
  const [items, setItems] = useState<ReviewCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<"confirm" | "research" | "delete" | null>(null);
  const [progressStage, setProgressStage] = useState("");
  const [message, setMessage] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<Record<number, string[]>>({});

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
    setProgressStage("matching_files");
    setMessage("");
    try {
      const result = await api.confirmReview(item.id, selectedFiles[item.id] || []);
      const job = await waitForTransfer(result.id, (current) => setProgressStage(current.stage));
      setMessage(
        ["done", "triggered"].includes(job.status)
          ? "所选资源已完成匹配、改名并提交转存。"
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
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
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
          <p>打开夸克链接核对内容，或直接选择正确文件。后台仍会按 TMDB 集数重新匹配、改名并转存。</p>
        </div>
      </div>
      {message && <div className="notice">{message}</div>}
      <div className="review-list">
        {items.map((item) => (
          <article className="review-card" key={item.id}>
            <header className="review-card-head">
              <div>
                <span className="review-kicker">候选资源</span>
                <h2>{item.source_title || "未命名候选"}</h2>
                <p>{[item.search_query, item.source, item.season_number ? `S${item.season_number}` : ""].filter(Boolean).join(" / ")}</p>
              </div>
              <span className="review-score">匹配分 {Math.round(item.score)}</span>
            </header>

            <div className="review-link-row">
              <div>
                <strong>夸克分享</strong>
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

            {item.review_state === "notification_failed" && <p className="danger">QAS 通知未发送成功，请检查 QAS 通知配置。</p>}
            <footer className="review-actions">
              <button className="primary review-confirm" onClick={() => void confirm(item)} disabled={busy !== null}>
                {busy === item.id && busyAction === "confirm" ? <Spinner /> : <CheckCircle size={17} />}
                <span>
                  {busy === item.id && busyAction === "confirm"
                    ? transferStageLabel(progressStage)
                    : (selectedFiles[item.id]?.length || 0) > 0
                      ? `转存所选文件 (${selectedFiles[item.id].length})`
                      : "使用此资源"}
                </span>
              </button>
              <button className="ghost" onClick={() => void research(item)} disabled={busy !== null}>
                {busy === item.id && busyAction === "research" ? <Spinner /> : <ArrowClockwise size={17} />}
                重新搜索
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
  };
  return labels[reason] || reason.replaceAll("_", " ");
}

function taskToMedia(task: TrackingTask): MediaItem {
  return {
    id: task.tmdb_id,
    tmdb_id: task.tmdb_id,
    media_type: task.media_type as MediaItem["media_type"],
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
    title: item.title,
    year: item.year,
    poster_url: item.poster_url,
    overview: item.overview,
  };
}

function mediaTypeLabel(mediaType: string) {
  if (mediaType === "movie") return "电影";
  if (mediaType === "variety") return "综艺";
  return "剧集";
}

function SettingsPage() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [testingPansou, setTestingPansou] = useState(false);
  const [pansouTestResult, setPansouTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [qasPansouEnabled, setQasPansouEnabled] = useState<boolean | null>(null);
  const [settingQasPansou, setSettingQasPansou] = useState(false);

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
      setMessage("已保存配置");
    } catch {
      setMessage("保存失败");
    } finally {
      setSaving(false);
    }
  }

  function update(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function testPansou() {
    setTestingPansou(true);
    setPansouTestResult(null);
    try {
      const result = await api.testPansou();
      setPansouTestResult({ ok: result.ok, message: result.message });
    } catch {
      setPansouTestResult({ ok: false, message: "连接失败，请先保存地址后重试" });
    } finally {
      setTestingPansou(false);
    }
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
          <h1>设置</h1>
          <p>敏感配置只保存在服务端，前端只显示配置状态。</p>
        </div>
      </div>
      {!config && <div className="list-skeleton" />}
      {config && (
        <form className="settings-form" onSubmit={save}>
          <SettingsSection title="服务连接" body="这些信息只写入 NAS 上的配置文件。">
            <SettingsInput label="TMDB API Key" name="tmdb_api_key" saved={config.has_tmdb_key} value={form.tmdb_api_key || ""} onChange={update} secret />
            <SettingsInput label="QAS 地址" name="qas_base_url" saved={Boolean(config.qas_base_url)} value={form.qas_base_url || ""} onChange={update} placeholder={config.qas_base_url || "http://your-qas-host:your-qas-port"} showSavedValue />
            <SettingsInput label="QAS Token" name="qas_token" saved={config.has_qas} value={form.qas_token || ""} onChange={update} secret />
            <SettingsInput
              label="PanSou 地址"
              name="pansou_url"
              saved={Boolean(config.pansou_url)}
              value={form.pansou_url || ""}
              onChange={update}
              placeholder={config.pansou_url || "http://your-pansou-host:your-pansou-port"}
              showSavedValue
              action={(
                <button type="button" className="primary compact-action" onClick={() => void testPansou()} disabled={testingPansou || saving}>
                  {testingPansou && <Spinner />}
                  {testingPansou ? "测试中" : "测试连接"}
                </button>
              )}
              result={pansouTestResult}
            />
            <SettingsToggle
              label="QAS 自带搜索"
              value={qasPansouEnabled ?? false}
              onChange={(enabled) => void setQasPansou(enabled)}
              trueLabel="启用 QAS 自带搜索"
              falseLabel="禁用 QAS 自带搜索"
              disabled={qasPansouEnabled === null || settingQasPansou}
              busy={settingQasPansou}
            />
          </SettingsSection>
          <SettingsSection title="网络代理" body="可选。用于通过旁路由等 HTTP 代理访问 TMDB 和 PanSou；留空时直接连接。">
            <SettingsInput
              label="代理地址"
              name="proxy_url"
              saved={Boolean(config.proxy_url)}
              value={form.proxy_url ?? config.proxy_url}
              onChange={update}
              placeholder="http://192.168.1.2:7890"
            />
            <p className="settings-help">支持 http:// 或 https:// 地址；如代理需要认证，可填写 http://用户名:密码@地址:端口。</p>
          </SettingsSection>
          <SettingsSection title="保存路径" body="这里填写夸克网盘中的保存根目录：网盘默认 /strm；本地默认 /下载_未整理，作为 MoviePilot 等工具监控、转存和同步到本地媒体库的中转目录。最终路径会自动拼接分类目录和媒体名称。">
            <SettingsInput label="网盘根路径" name="cloud_save_path" saved value={form.cloud_save_path || ""} onChange={update} placeholder={config.cloud_root} showSavedValue />
            <SettingsInput label="本地根路径" name="local_save_path" saved value={form.local_save_path || ""} onChange={update} placeholder={config.local_root} showSavedValue />
          </SettingsSection>
          <SettingsSection title="分类路径" body="分类路径只是根目录下的相对子目录，不是最终保存路径。剧集和综艺填写 /tv 后，系统会自动保存到 /strm/tv 或 /下载_未整理/tv。">
            <CategoryPathSettings config={config} form={form} onChange={setForm} />
          </SettingsSection>
          <SettingsSection
            title="愿望单巡检"
            body={`每条愿望按 TMDB 日期执行，默认 ${String(config.wishlist_default_check_hour).padStart(2, "0")}:00；可直接在愿望单卡片修改。`}
          >
            <SettingsToggle
              label="启用自动巡检"
              value={form.wishlist_scheduler_enabled === undefined ? config.wishlist_scheduler_enabled : form.wishlist_scheduler_enabled === "true"}
              onChange={(value) => update("wishlist_scheduler_enabled", String(value))}
            />
            <SettingsNumberInput
              label="巡检周期（分钟）"
              name="wishlist_poll_minutes"
              value={form.wishlist_poll_minutes || ""}
              placeholder={String(config.wishlist_poll_minutes)}
              min={1}
              max={1440}
              onChange={update}
            />
            <SettingsNumberInput
              label="默认检查小时"
              name="wishlist_default_check_hour"
              value={form.wishlist_default_check_hour || ""}
              placeholder={String(config.wishlist_default_check_hour)}
              min={0}
              max={23}
              onChange={update}
            />
            <p className="settings-help">巡检周期决定系统多久检查一次到期项目；具体执行日期仍以 TMDB 为准，每张愿望单卡片可以单独修改检查小时。</p>
          </SettingsSection>
          <div className="settings-footer">
            <span>版本 {config.version}</span>
            <button className="primary settings-save" disabled={saving}>
              {saving ? "保存中" : "保存设置"}
            </button>
          </div>
          {message && <div className="notice">{message}</div>}
        </form>
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

function buildConfigPayload(form: Record<string, string>) {
  const payload: Record<string, string | number | boolean | Record<string, string>> = {};
  const categoryPaths: Record<string, string> = {};
  Object.entries(form).forEach(([key, value]) => {
    if (!value.trim() && key !== "proxy_url") return;
    if (key.startsWith("category_paths.")) {
      categoryPaths[key.replace("category_paths.", "")] = value.trim();
      return;
    }
    if (key === "wishlist_scheduler_enabled") {
      payload[key] = value === "true";
      return;
    }
    if (key === "wishlist_poll_minutes" || key === "wishlist_default_check_hour") {
      payload[key] = Number(value);
      return;
    }
    payload[key] = value.trim();
  });
  if (Object.keys(categoryPaths).length) {
    payload.category_paths = categoryPaths;
  }
  return payload;
}

function SettingsToggle({
  label,
  value,
  onChange,
  trueLabel = "开",
  falseLabel = "关",
  disabled = false,
  busy = false,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
  trueLabel?: string;
  falseLabel?: string;
  disabled?: boolean;
  busy?: boolean;
}) {
  return (
    <div className="settings-field">
      <span>{label}</span>
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
  ["movie", "电影"],
  ["tv", "剧集"],
  ["variety", "综艺"],
  ["anime", "动漫"],
  ["bangumi", "番剧"],
] as const;

function CategoryPathSettings({
  config,
  form,
  onChange,
}: {
  config: ConfigStatus;
  form: Record<string, string>;
  onChange: React.Dispatch<React.SetStateAction<Record<string, string>>>;
}) {
  function updatePath(key: string, value: string) {
    onChange((current) => ({ ...current, [`category_paths.${key}`]: value }));
  }

  const cloudRoot = (form.cloud_save_path || config.cloud_root || "/strm").replace(/\/$/, "");
  const localRoot = (form.local_save_path || config.local_root || "/下载_未整理").replace(/\/$/, "");
  const tvCategory = (form["category_paths.variety"] || config.category_paths?.variety || "/tv").replace(/^\/?/, "/");

  return (
    <>
      <p className="muted">
        综艺路径示例：网盘 <code>{cloudRoot}{tvCategory}</code>；本地 <code>{localRoot}{tvCategory}</code>。媒体名称会继续追加在后面。
      </p>
      <div className="category-path-grid">
        {defaultCategoryRows.map(([key, label]) => {
          const current = config.category_paths?.[key] || (key === "movie" ? "/movie" : "/tv");
          return (
            <label className="category-path-field" key={key}>
              <span>{label}</span>
              <input
                value={form[`category_paths.${key}`] || ""}
                placeholder={`${current}，如需修改请重新填写`}
                onChange={(event) => updatePath(key, event.target.value)}
              />
            </label>
          );
        })}
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
        placeholder={`${placeholder}，范围 ${min}-${max}`}
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

function SettingsInput({
  label,
  name,
  value,
  saved,
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
  secret?: boolean;
  placeholder?: string;
  showSavedValue?: boolean;
  onChange: (key: string, value: string) => void;
  action?: React.ReactNode;
  result?: { ok: boolean; message: string } | null;
}) {
  const savedPlaceholder = showSavedValue && placeholder ? `${placeholder}，如需修改请重新填写` : "已保存，如需修改请重新填写";
  return (
    <div className="settings-field">
      <span>{label}</span>
      <div className="settings-input-content">
        <div className="settings-input-action">
          <input
            aria-label={label}
            type={secret ? "password" : "text"}
            value={value}
            placeholder={saved ? savedPlaceholder : placeholder || "未配置"}
            onChange={(event) => onChange(name, event.target.value)}
          />
          {action}
        </div>
        {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
      </div>
    </div>
  );
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
