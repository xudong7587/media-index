import { ArrowClockwise, Eye, GlobeHemisphereWest, PlayCircle, Star } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { api, MediaItem } from "../../lib/api";

const platforms = [
  { key: "netflix", label: "Netflix", mark: "N", provider: "8" },
  { key: "max", label: "HBO Max", mark: "H", provider: "1899" },
  { key: "apple", label: "Apple TV+", mark: "A", provider: "350" },
  { key: "disney", label: "Disney+", mark: "D+", provider: "337" },
  { key: "crunchyroll", label: "Crunchyroll", mark: "C", provider: "283" },
  { key: "prime", label: "Prime Video", mark: "P", provider: "119" },
  { key: "amazon", label: "Amazon", mark: "a", provider: "10" },
  { key: "hulu", label: "Hulu", mark: "h", provider: "15" },
] as const;

const regions = [
  ["US", "美国"], ["CN", "中国大陆"], ["HK", "中国香港"], ["TW", "中国台湾"], ["JP", "日本"], ["KR", "韩国"], ["GB", "英国"],
] as const;

type RankingKind = "all" | "movie" | "tv";

export function DiscoveryRankings({
  onSelect,
  onTrack,
  busyKey,
  canTrack,
}: {
  onSelect: (item: MediaItem) => void;
  onTrack: (item: MediaItem) => void;
  busyKey: string;
  canTrack: (item: MediaItem) => boolean;
}) {
  const [platformKey, setPlatformKey] = useState<(typeof platforms)[number]["key"]>("netflix");
  const [kind, setKind] = useState<RankingKind>("all");
  const [region, setRegion] = useState("US");
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const platform = useMemo(() => platforms.find((item) => item.key === platformKey) || platforms[0], [platformKey]);
  const regionLabel = regions.find(([value]) => value === region)?.[1] || region;

  async function load(refresh = false) {
    setLoading(true);
    setError("");
    try {
      const types = kind === "all" ? ["movie", "tv"] : [kind];
      const responses = await Promise.all(types.map((type) => api.discover(type, "", "hot", "", 0, 1, kind === "all" ? 10 : 20, refresh, platform.provider, region)));
      const merged = kind === "all" ? interleave(responses.map((response) => response.results || [])) : responses[0].results || [];
      setItems(Array.from(new Map(merged.map((item) => [`${item.media_type}-${item.tmdb_id}`, item])).values()).slice(0, 20));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "榜单加载失败");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [platformKey, kind, region]);

  return <section className="streaming-rankings" data-platform={platform.key}>
    <header className="ranking-hero">
      <div className="ranking-hero-copy">
        <span className="ranking-brand-line"><i>{platform.mark}</i>{platform.label} · STREAMING CHART</span>
        <h2>{platform.label} 热映榜</h2>
        <p>按 {regionLabel} 地区的 TMDB 可观看来源与当前热度浏览电影和剧集。</p>
      </div>
      <div className="ranking-source-count"><span>榜单数据源</span><strong>{items.length}</strong><small>部作品</small></div>
    </header>

    <section className="ranking-control-panel">
      <header><div><span>选择平台</span><h3>流媒体榜单</h3></div><button type="button" className="ghost" disabled={loading} onClick={() => void load(true)}><ArrowClockwise className={loading ? "spin" : ""} />刷新数据</button></header>
      <div className="platform-picker" role="tablist" aria-label="流媒体平台">
        {platforms.map((item) => <button key={item.key} type="button" role="tab" aria-selected={platformKey === item.key} className={platformKey === item.key ? "active" : ""} onClick={() => setPlatformKey(item.key)}><i data-brand={item.key}>{item.mark}</i><span>{item.label}</span></button>)}
      </div>
      <div className="ranking-filter-line">
        <div className="ranking-kind-switch" role="tablist" aria-label="榜单类型">
          <button type="button" role="tab" aria-selected={kind === "all"} className={kind === "all" ? "active" : ""} onClick={() => setKind("all")}>全部榜单</button>
          <button type="button" role="tab" aria-selected={kind === "movie"} className={kind === "movie" ? "active" : ""} onClick={() => setKind("movie")}>电影榜</button>
          <button type="button" role="tab" aria-selected={kind === "tv"} className={kind === "tv" ? "active" : ""} onClick={() => setKind("tv")}>剧集榜</button>
        </div>
        <label><GlobeHemisphereWest /><span>国家/地区</span><select value={region} onChange={(event) => setRegion(event.target.value)}>{regions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      </div>
    </section>

    <section className="ranking-results">
      <header><div><span>{platform.label.toUpperCase()} · {region}</span><h3>{platform.label} 热映榜</h3></div><small>{kind === "all" ? "电影与剧集" : kind === "movie" ? "电影" : "剧集"}</small></header>
      {loading && <div className="ranking-loading" aria-label="榜单加载中" />}
      {!loading && error && <div className="ranking-empty"><strong>榜单暂时无法加载</strong><span>{error}</span></div>}
      {!loading && !error && items.length === 0 && <div className="ranking-empty"><strong>这个地区暂时没有榜单</strong><span>换个平台或地区再试试。</span></div>}
      {!loading && !error && items.length > 0 && <div className="ranked-media-list">
        {items.map((item, index) => <article key={`${item.media_type}-${item.tmdb_id}`}>
          <button type="button" className="ranked-media-main" onClick={() => onSelect(item)} aria-label={`查看${item.title}详情`}>
            <span className="ranked-number">{String(index + 1).padStart(2, "0")}</span>
            <span className="ranked-poster">{item.poster_url ? <img src={item.poster_url} alt="" loading="lazy" /> : <PlayCircle />}</span>
            <span className="ranked-copy"><strong>{item.title}</strong><small>{[item.media_type === "movie" ? "电影" : "剧集", item.year || item.release_date].filter(Boolean).join(" · ")}</small></span>
            <span className="ranked-score">{typeof item.vote_average === "number" && <><Star weight="fill" />{item.vote_average.toFixed(1)}</>}</span>
          </button>
          {canTrack(item) && <button type="button" className="ranked-track" disabled={busyKey === `${item.media_type}-${item.tmdb_id}`} onClick={() => onTrack(item)}><Eye />{busyKey === `${item.media_type}-${item.tmdb_id}` ? "加入中" : "追更"}</button>}
        </article>)}
      </div>}
    </section>
  </section>;
}

function interleave(groups: MediaItem[][]): MediaItem[] {
  const result: MediaItem[] = [];
  const length = Math.max(0, ...groups.map((group) => group.length));
  for (let index = 0; index < length; index += 1) {
    groups.forEach((group) => { if (group[index]) result.push(group[index]); });
  }
  return result;
}
