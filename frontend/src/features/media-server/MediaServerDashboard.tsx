import {
  ArrowClockwise,
  CheckCircle,
  Devices,
  FilmSlate,
  MonitorPlay,
  PlayCircle,
  Television,
  Users,
  WarningCircle,
} from "@phosphor-icons/react";
import { ReactNode, useEffect, useState } from "react";

import { AppRoute } from "../../app/routes";
import { api, ApiError, EmbyDashboard } from "../../lib/api";

export function MediaServerDashboard({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  const [data, setData] = useState<EmbyDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
  </section>;
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
