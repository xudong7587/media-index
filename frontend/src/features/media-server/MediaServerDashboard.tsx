import {
  ArrowClockwise,
  CheckCircle,
  Devices,
  FilmSlate,
  MonitorPlay,
  PaintBrushBroad,
  PlayCircle,
  Sparkle,
  Television,
  Users,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { ReactNode, useEffect, useState } from "react";

import { AppRoute } from "../../app/routes";
import { api, ApiError, ConfigStatus, EmbyDashboard } from "../../lib/api";

type CoverStyle = "collage" | "showcase" | "mosaic" | "minimal";
const coverStyles: Array<{ id: CoverStyle; label: string; description: string }> = [
  { id: "collage", label: "风格 1", description: "圆角海报堆叠" },
  { id: "showcase", label: "风格 2", description: "斜向多海报组合" },
  { id: "mosaic", label: "风格 3", description: "单海报斜置" },
  { id: "minimal", label: "风格 4", description: "纯文字封面" },
];

export function MediaServerDashboard({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  const [data, setData] = useState<EmbyDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [coverStudioOpen, setCoverStudioOpen] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await api.embyDashboard());
    } catch (reason) {
      setData(null);
      setError(reason instanceof ApiError ? reason.message : "媒体服务器状态读取失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  if (loading) {
    return <section className="media-server-dashboard"><DashboardHeader onRefresh={() => void load()} loading /><div className="dashboard-skeleton" aria-label="正在读取 Emby 数据" /></section>;
  }

  if (!data) {
    return <section className="media-server-dashboard">
      <DashboardHeader onRefresh={() => void load()} />
      <div className="dashboard-empty-state">
        <WarningCircle size={34} />
        <div><h2>暂时无法读取 Emby</h2><p>{error || "请先完成 Emby 地址和 API Key 配置。"}</p></div>
        <button type="button" className="primary" onClick={() => onNavigate({ page: "strm" })}>前往 Emby 连接</button>
      </div>
    </section>;
  }

  const activePlaying = data.sessions.filter((session) => session.is_playing);
  return <section className="media-server-dashboard">
    <DashboardHeader onRefresh={() => void load()} />

    <section className="server-overview" aria-label="Emby 服务器概览">
      <div className="server-mark"><MonitorPlay size={32} weight="duotone" /></div>
      <div className="server-identity"><span><CheckCircle weight="fill" />连接正常</span><h2>{data.server.name}</h2><p>{data.server.operating_system || "Emby Server"}<small>版本 {data.server.version}</small></p></div>
      <div className="server-now"><strong>{activePlaying.length}</strong><span>正在播放</span></div>
      <div className="server-now"><strong>{data.sessions.length}</strong><span>活跃会话</span></div>
    </section>

    <div className="media-count-strip" aria-label="媒体数量">
      <Metric icon={<FilmSlate />} label="电影" value={data.counts.MovieCount} />
      <Metric icon={<Television />} label="剧集" value={data.counts.SeriesCount} />
      <Metric icon={<PlayCircle />} label="单集" value={data.counts.EpisodeCount} />
      <Metric icon={<Users />} label="活跃用户" value={new Set(data.sessions.map((item) => item.user_name)).size} />
    </div>

    <section className="dashboard-section library-cover-tool">
      <div className="library-cover-tool-icon"><PaintBrushBroad size={30} weight="duotone" /></div>
      <div><h2>媒体库封面工坊</h2><p>使用 Emby 现有海报生成四种静态模板；预览确认后才会写入 Emby。</p></div>
      <button type="button" className="primary" onClick={() => setCoverStudioOpen(true)}><Sparkle weight="fill" />打开封面工坊</button>
    </section>

    <section className="dashboard-section">
      <header><div><h2>媒体库</h2><p>来自 Emby 的现有媒体库与最新封面。</p></div><span>{data.libraries.length} 个</span></header>
      {data.libraries.length === 0 ? <p className="dashboard-inline-empty">Emby 当前没有返回媒体库。</p> : <div className="library-cover-grid">
        {data.libraries.map((library) => <article key={library.id || library.name} className="library-cover-card">
          <div className="library-cover-art">
            {library.cover_item_id ? <DashboardImage src={`/api/integrations/emby/images/${encodeURIComponent(library.cover_item_id)}`} alt="" /> : <FilmSlate size={34} />}
            <div><span>{collectionLabel(library.collection_type)}</span><strong>{library.name}</strong></div>
          </div>
        </article>)}
      </div>}
    </section>

    <div className="dashboard-lower-grid">
      <section className="dashboard-section dashboard-sessions">
        <header><div><h2>播放与用户</h2><p>当前连接到 Emby 的用户和设备。</p></div><Devices size={22} /></header>
        {data.sessions.length === 0 ? <p className="dashboard-inline-empty">当前没有活跃会话。</p> : <div className="session-list">
          {data.sessions.map((session) => <article key={session.id || `${session.user_name}-${session.device_name}`}>
            <span className={session.is_playing ? "playing" : ""}>{session.user_name.slice(0, 1).toUpperCase()}</span>
            <div><strong>{session.user_name}</strong><small>{session.item_name ? `正在播放 ${session.item_name}` : session.device_name}</small></div>
            <em>{session.is_playing ? "播放中" : "在线"}</em>
          </article>)}
        </div>}
      </section>

      <section className="dashboard-section dashboard-latest">
        <header><div><h2>最近入库</h2><p>Emby 最近识别的电影和剧集。</p></div><span>{data.latest_items.length} 项</span></header>
        {data.latest_items.length === 0 ? <p className="dashboard-inline-empty">暂时没有最近入库数据。</p> : <div className="latest-media-grid">
          {data.latest_items.slice(0, 10).map((item) => <article key={item.id}>
            <div>{item.id && item.has_image ? <DashboardImage src={`/api/integrations/emby/images/${encodeURIComponent(item.id)}`} alt="" /> : <FilmSlate />}</div>
            <strong>{item.name}</strong>
            <small>{[item.year, item.rating ? `${item.rating.toFixed(1)} 分` : ""].filter(Boolean).join(" / ") || (item.type === "Series" ? "剧集" : "电影")}</small>
          </article>)}
        </div>}
      </section>
    </div>
    {coverStudioOpen ? <CoverGeneratorDialog libraries={data.libraries} onClose={() => setCoverStudioOpen(false)} onApplied={() => void load()} /> : null}
  </section>;
}

function CoverGeneratorDialog({ libraries, onClose, onApplied }: {
  libraries: EmbyDashboard["libraries"];
  onClose: () => void;
  onApplied: () => void;
}) {
  const [libraryId, setLibraryId] = useState(libraries[0]?.id || "");
  const library = libraries.find((item) => item.id === libraryId) || libraries[0];
  const [style, setStyle] = useState<CoverStyle>("collage");
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleHours, setScheduleHours] = useState(168);
  const [nonce, setNonce] = useState(0);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => { void api.config().then((config: ConfigStatus) => {
    setStyle(config.emby_cover_style || "collage");
    setScheduleEnabled(config.emby_cover_refresh_enabled);
    setScheduleHours(config.emby_cover_refresh_hours || 168);
  }); }, []);

  async function applyCover() {
    if (!library) return;
    setSaving(true);
    setMessage("");
    try {
      const result = await api.applyEmbyLibraryCover(library.id, { title: library.name, style });
      setMessage(result.message);
      onApplied();
    } catch (reason) {
      setMessage(reason instanceof ApiError ? reason.message : "媒体库封面写入失败");
    } finally {
      setSaving(false);
    }
  }

  async function applyAll() {
    setSaving(true); setMessage("");
    try { const result = await api.refreshEmbyLibraryCovers(style); setMessage(result.message); onApplied(); }
    catch (reason) { setMessage(reason instanceof ApiError ? reason.message : "批量封面生成失败"); }
    finally { setSaving(false); }
  }

  async function saveSchedule() {
    setSaving(true); setMessage("");
    try {
      await api.saveConfig({ emby_cover_refresh_enabled: scheduleEnabled, emby_cover_refresh_hours: Math.max(1, scheduleHours), emby_cover_style: style });
      setMessage(scheduleEnabled ? `已启用，每 ${Math.max(1, scheduleHours)} 小时刷新` : "已关闭定时封面刷新");
    } catch (reason) { setMessage(reason instanceof ApiError ? reason.message : "定时设置保存失败"); }
    finally { setSaving(false); }
  }

  return <div className="cover-generator-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <section className="cover-generator-dialog" role="dialog" aria-modal="true" aria-labelledby="cover-generator-title">
      <header><h2 id="cover-generator-title">Emby 媒体库封面生成</h2><button type="button" className="cover-generator-close" onClick={onClose} aria-label="关闭封面工坊" title="关闭"><X size={25} /></button></header>
      <section className="cover-workshop-hero">
        <span aria-hidden="true">▧</span><div><small>MEDIA COVER ATELIER</small><h3>封面生成工坊</h3><p>选择静态样式并预览，生成时读取媒体库现有海报；确认后再上传到 Emby。</p></div>
      </section>
      <div className="cover-workshop-toolbar">
        <label><span>目标媒体库</span><select value={library?.id || ""} onChange={(event) => setLibraryId(event.target.value)}>{libraries.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <div className="cover-generator-readonly"><span>输出规格</span><strong>1920 × 1080 JPG</strong></div>
        <button type="button" className="ghost" disabled={!library} onClick={() => setNonce((value) => value + 1)}>刷新封面预览</button>
      </div>
      {library ? <div className="cover-style-gallery" role="group" aria-label="静态封面样式">{coverStyles.map((item) => {
        const itemPreviewUrl = coverPreviewUrl(library.id, library.name, item.id, nonce);
        return <button type="button" className={`cover-style-card ${style === item.id ? "active" : ""}`} key={item.id} onClick={() => setStyle(item.id)} aria-pressed={style === item.id}>
          <span className="cover-style-art"><DashboardImage key={itemPreviewUrl} src={itemPreviewUrl} alt={`${library.name}${item.description}预览`} /></span>
          <strong>{item.label}</strong><small>{item.description}</small>
        </button>;
      })}</div> : <p className="dashboard-inline-empty">没有可生成封面的媒体库。</p>}
      <div className="cover-schedule"><label><input type="checkbox" checked={scheduleEnabled} onChange={(event) => setScheduleEnabled(event.target.checked)} />定时刷新全部媒体库</label><label>每 <input type="number" min={1} max={8760} value={scheduleHours} onChange={(event) => setScheduleHours(Number(event.target.value) || 1)} /> 小时</label><button type="button" className="ghost" disabled={saving} onClick={() => void saveSchedule()}>保存定时设置</button></div>
      {message ? <p className="cover-generator-message">{message}</p> : null}
      <footer><button type="button" className="ghost" disabled={saving || !library} onClick={() => void applyCover()}>应用当前媒体库</button><button type="button" className="primary" disabled={saving || !libraries.length} onClick={() => void applyAll()}>{saving ? "生成中…" : "按当前样式生成全部"}</button></footer>
    </section>
  </div>;
}

function coverPreviewUrl(libraryId: string, title: string, style: CoverStyle, nonce: number) {
  return `/api/integrations/emby/libraries/${encodeURIComponent(libraryId)}/cover-preview?title=${encodeURIComponent(title)}&style=${style}&v=${nonce}`;
}

function DashboardHeader({ onRefresh, loading = false }: { onRefresh: () => void; loading?: boolean }) {
  return <div className="page-head dashboard-page-head"><div><p className="eyebrow">MEDIA SERVER</p><h1>媒体服务器</h1><p>集中查看 Emby 媒体库、最近入库、播放会话和活跃用户。</p></div><button type="button" className="ghost" disabled={loading} onClick={onRefresh}><ArrowClockwise className={loading ? "spin" : ""} />刷新</button></div>;
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value?: number }) {
  return <div>{icon}<span>{label}</span><strong>{typeof value === "number" ? value.toLocaleString() : "-"}</strong></div>;
}

function DashboardImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  return failed ? <FilmSlate size={34} /> : <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />;
}

function collectionLabel(value: string) {
  const labels: Record<string, string> = { movies: "电影", tvshows: "剧集", music: "音乐", homevideos: "家庭影像", mixed: "混合媒体" };
  return labels[value.toLowerCase()] || "媒体库";
}
