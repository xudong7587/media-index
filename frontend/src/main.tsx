import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowClockwise,
  CheckCircle,
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
import { api, ConfigStatus, Genre, MediaItem, ResourceStatus, TrackingTask, WishlistItem } from "./lib/api";
import "./styles.css";

type Page = "discover" | "tracking" | "wishlist" | "review" | "settings";
type Theme = "light" | "dark";

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
        <div className="brand-mark">MI</div>
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
  const [page, setPage] = useState<Page>("discover");
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

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="wordmark" onClick={() => setPage("discover")}>
          <span>MI</span>
          Media Index
        </button>
        <nav>
          {nav.map(([key, label]) => (
            <button key={key} className={page === key ? "active" : ""} onClick={() => setPage(key)}>
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

  async function load() {
    setLoading(true);
    setError("");
    try {
      const res = query.trim() ? await api.search(query.trim()) : await api.discover(mediaType, region, sort, genre, 0);
      setItems(res.results || []);
      if ("error" in res && res.error) setError("TMDB 尚未配置");
    } catch {
      setError("加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
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
            void load();
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
        <button className="ghost" onClick={() => void load()}>
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
        </FilterRow>
      </div>

      {loading && <PosterSkeleton />}
      {!loading && error && <Empty title={error} body="请到设置页确认 TMDB 配置。" />}
      {!loading && !error && items.length === 0 && <Empty title="没有结果" body="换个关键词或分类试试。" />}
      {!loading && !error && (
        <div className="poster-grid">
          {items.map((item) => (
            <button className="poster-card" key={`${item.media_type}-${item.tmdb_id}`} onClick={() => setSelected(item)}>
              <Poster item={item} />
              <span className="poster-title">{item.title}</span>
              <span className="poster-meta">{item.year}</span>
            </button>
          ))}
        </div>
      )}
      {selected && <MediaDialog item={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}

function MediaDialog({ item, onClose }: { item: MediaItem; onClose: () => void }) {
  const [detail, setDetail] = useState<MediaItem | null>(null);
  const [season, setSeason] = useState(1);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"" | "cloud" | "local">("");
  const [completed, setCompleted] = useState<"" | "cloud" | "local">("");
  const [resource, setResource] = useState<ResourceStatus | null>(null);
  const [resourceLoading, setResourceLoading] = useState(true);

  useEffect(() => {
    api.details(item.media_type, item.tmdb_id).then((data) => {
      setDetail(data);
      const latest = data.seasons?.at(-1)?.season_number ?? 1;
      setSeason(latest);
    });
  }, [item]);

  const media = detail || item;
  const canTrack = media.media_type === "tv" || media.media_type === "variety";
  const isOngoing = canTrack && media.status !== "Ended";
  const canSave = Boolean(resource?.found) && !resourceLoading && !busy && !completed;

  useEffect(() => {
    let cancelled = false;
    setResource(null);
    setResourceLoading(true);
    api
      .resources(media, canTrack ? season : undefined)
      .then((res) => {
        if (!cancelled) setResource(res);
      })
      .catch(() => {
        if (!cancelled) setResource({ ok: false, found: false, message: "资源搜索失败" });
      })
      .finally(() => {
        if (!cancelled) setResourceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [media.media_type, media.tmdb_id, season, canTrack]);

  async function transfer(target: "cloud" | "local") {
    setBusy(target);
    setMessage("");
    try {
      const res = await api.createTransfer(media, target, canTrack ? season : undefined);
      if (isOngoing) {
        await api.createTracking(media, season, target);
        setMessage(
          res.ok
            ? `已触发 QAS 转存，并加入智能追更：${res.save_path}`
            : `已加入智能追更，但本次转存未完成：${res.message || "等待下次重试"}`,
        );
      } else if (res.ok) {
        setMessage(`已触发 QAS 一次性转存：${res.save_path}`);
      } else {
        setMessage(`转存未完成：${res.message || "请稍后重试"}`);
      }
      if (res.ok || target === "local") {
        setCompleted(target);
      }
    } catch {
      setMessage("创建任务失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <article className="media-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">
          ❌
        </button>
        <div className="modal-hero">
          {media.backdrop_url && <img src={media.backdrop_url} alt="" />}
        </div>
        <div className="modal-body">
          <Poster item={media} compact />
          <div className="modal-main">
            <h2>{media.title}</h2>
            <p className="muted">{[media.year, media.genres?.join(" / "), media.status].filter(Boolean).join(" / ")}</p>
            <p>{media.overview || "暂无简介。"}</p>
            {canTrack && Boolean(media.seasons?.length) && (
              <div className="season-row">
                {media.seasons?.map((s, index) => {
                  const latest = index === (media.seasons?.length ?? 1) - 1;
                  const state = latest && isOngoing ? "连载中" : "已完结";
                  return (
                    <button key={s.season_number} className={season === s.season_number ? "active" : ""} onClick={() => setSeason(s.season_number)}>
                      <span>S{s.season_number}</span>
                      <em>{state}</em>
                    </button>
                  );
                })}
              </div>
            )}
            <div className="action-row">
              <button className="primary action-button" onClick={() => transfer("cloud")} disabled={!canSave}>
                {completed === "cloud" ? <CheckCircle size={18} /> : busy === "cloud" ? <Spinner /> : <CloudArrowDown size={18} />}
                {completed === "cloud" ? "已完成" : busy === "cloud" ? "执行中" : "存网盘"}
              </button>
              <button className="secondary action-button" onClick={() => transfer("local")} disabled={!canSave}>
                {completed === "local" ? <CheckCircle size={18} /> : busy === "local" ? <Spinner /> : <HardDrives size={18} />}
                {completed === "local" ? "已完成" : busy === "local" ? "执行中" : "存本地"}
              </button>
              <button
                className={`ghost action-button resource-button ${resource?.found ? "found" : ""}`}
                disabled={resourceLoading || Boolean(busy)}
                title={resource?.title || resource?.message || ""}
                onClick={() => {
                  if (!resource?.found) {
                    void api.addWishlist(media).then(() => setMessage("已加入愿望单，后续会按设置自动巡检资源。"));
                  }
                }}
              >
                {resourceLoading ? <Spinner /> : resource?.found ? <CheckCircle size={18} /> : <Heart size={18} />}
                {resourceLoading ? "PanSou 搜索中" : resource?.found ? "已找到资源" : "暂无资源 加入愿望单"}
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

function WishlistPage() {
  const [items, setItems] = useState<WishlistItem[]>([]);
  const [loading, setLoading] = useState(true);

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
                <span className="status">{item.status === "pending" ? "待巡检" : item.status}</span>
              </div>
              <p className="task-overview">{item.overview || "暂无简介。"}</p>
              <p>{[item.year, mediaTypeLabel(item.media_type), `加入时间 ${item.created_at?.slice(0, 10)}`].filter(Boolean).join(" / ")}</p>
            </div>
            <div className="row-actions">
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

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>智能追更</h1>
          <p>按 TMDB 播出信息保守搜索，模糊匹配会进入待确认。</p>
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
              <p>更新周期：{task.next_check_at ? `下次检查 ${task.next_check_at.slice(0, 16)}` : "每日检查"}</p>
              {task.last_error && <p className="danger">{task.last_error}</p>}
            </div>
            <div className="row-actions">
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

function ReviewPage() {
  return <Empty title="暂无待确认" body="模糊匹配、年份冲突或多候选结果会进入这里。" />;
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

  useEffect(() => {
    api.config().then(setConfig);
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
            <SettingsInput label="PanSou 地址" name="pansou_url" saved={Boolean(config.pansou_url)} value={form.pansou_url || ""} onChange={update} placeholder={config.pansou_url || "http://your-pansou-host:your-pansou-port"} showSavedValue />
          </SettingsSection>
          <SettingsSection title="保存路径" body="根路径决定任务写到网盘还是本地，分类路径会拼在根路径后面。">
            <SettingsInput label="网盘根路径" name="cloud_save_path" saved value={form.cloud_save_path || ""} onChange={update} placeholder={config.cloud_root} showSavedValue />
            <SettingsInput label="本地根路径" name="local_save_path" saved value={form.local_save_path || ""} onChange={update} placeholder={config.local_root} showSavedValue />
          </SettingsSection>
          <SettingsSection title="分类路径" body="默认电影进 /movie，剧集和综艺进 /tv；后面可以继续扩展动漫、番剧。">
            <CategoryPathSettings config={config} form={form} onChange={setForm} />
          </SettingsSection>
          <SettingsSection title="愿望单巡检" body="用于定时检查愿望单里的资源是否已经出现。">
            <SettingsInput label="启用巡检" name="wishlist_cron_enabled" saved value={form.wishlist_cron_enabled || ""} onChange={update} placeholder={config.wishlist_cron_enabled ? "true" : "false"} showSavedValue />
            <SettingsInput label="Cron 表达式" name="wishlist_cron_schedule" saved value={form.wishlist_cron_schedule || ""} onChange={update} placeholder={config.wishlist_cron_schedule} showSavedValue />
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
  const payload: Record<string, string | Record<string, string>> = {};
  const categoryPaths: Record<string, string> = {};
  Object.entries(form).forEach(([key, value]) => {
    if (!value.trim()) return;
    if (key.startsWith("category_paths.")) {
      categoryPaths[key.replace("category_paths.", "")] = value.trim();
      return;
    }
    payload[key] = value.trim();
  });
  if (Object.keys(categoryPaths).length) {
    payload.category_paths = categoryPaths;
  }
  return payload;
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

  return (
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
}: {
  label: string;
  name: string;
  value: string;
  saved: boolean;
  secret?: boolean;
  placeholder?: string;
  showSavedValue?: boolean;
  onChange: (key: string, value: string) => void;
}) {
  const savedPlaceholder = showSavedValue && placeholder ? `${placeholder}，如需修改请重新填写` : "已保存，如需修改请重新填写";
  return (
    <label className="settings-field">
      <span>{label}</span>
      <input
        type={secret ? "password" : "text"}
        value={value}
        placeholder={saved ? savedPlaceholder : placeholder || "未配置"}
        onChange={(event) => onChange(name, event.target.value)}
      />
    </label>
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
