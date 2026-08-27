import { ArrowRight, CaretLeft, CaretRight, Eye, FilmSlate, Pause, Play, PlayCircle, Star } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { MediaItem } from "../../lib/api";
import { Poster } from "./MediaPrimitives";
import "./discover-surfaces.css";

export type DiscoveryGroup = { key: string; title: string; description: string; items: MediaItem[] };

export function DiscoverExploreView({ groups, busyKey, canTrack, onSelect, onTrack }: {
  groups: DiscoveryGroup[];
  busyKey: string;
  canTrack: (item: MediaItem) => boolean;
  onSelect: (item: MediaItem) => void;
  onTrack: (item: MediaItem) => void;
}) {
  const orderedGroups = useMemo(() => [...groups].sort((left, right) => Number(right.key === "hot") - Number(left.key === "hot")), [groups]);
  const features = useMemo(() => {
    const unique = new Map<string, MediaItem>();
    for (const group of orderedGroups) {
      for (const item of group.items) {
        const key = `${item.media_type}-${item.tmdb_id}`;
        if (!unique.has(key) && item.backdrop_url) unique.set(key, item);
        if (unique.size >= 7) return [...unique.values()];
      }
    }
    if (!unique.size) {
      for (const group of orderedGroups) {
        for (const item of group.items) unique.set(`${item.media_type}-${item.tmdb_id}`, item);
      }
    }
    return [...unique.values()].slice(0, 7);
  }, [orderedGroups]);
  const [featureIndex, setFeatureIndex] = useState(0);
  const [carouselPaused, setCarouselPaused] = useState(false);
  const featured = features[featureIndex] || features[0];

  useEffect(() => setFeatureIndex(0), [features]);
  useEffect(() => {
    if (carouselPaused || features.length < 2 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setFeatureIndex((current) => (current + 1) % features.length), 6500);
    return () => window.clearInterval(timer);
  }, [carouselPaused, features.length]);

  if (!featured) return null;
  const featureKey = `${featured.media_type}-${featured.tmdb_id}`;
  const moveFeature = (offset: number) => setFeatureIndex((current) => (current + offset + features.length) % features.length);
  return <div className="discover-explore-view">
    <section
      className="discover-feature discover-carousel"
      aria-roledescription="轮播图"
      aria-label="精选影视推荐"
      onMouseEnter={() => setCarouselPaused(true)}
      onMouseLeave={() => setCarouselPaused(false)}
      onFocus={() => setCarouselPaused(true)}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setCarouselPaused(false); }}
    >
      <div
        className="discover-feature-backdrop"
        key={featureKey}
        style={featured.backdrop_url ? { backgroundImage: `url(${featured.backdrop_url})` } : undefined}
        aria-hidden
      />
      <div className="discover-feature-copy" aria-live="polite" aria-atomic="true">
        <span className="eyebrow">MEDIA DISCOVERY</span>
        <h2>{featured.title}</h2>
        <div className="discover-feature-meta"><span><Star weight="fill" />{featured.vote_average?.toFixed(1) || "待评分"}</span><span>{featured.year || featured.release_date || "日期待定"}</span><span>{mediaTypeLabel(featured)}</span></div>
        <p>{featured.overview || "从推荐内容中选择作品，进入详情核对 TMDB 信息并发起资源任务。"}</p>
        <div className="discover-feature-actions"><button type="button" className="primary" onClick={() => onSelect(featured)}>查看作品 <ArrowRight /></button>{canTrack(featured) && <button type="button" className="ghost light-action" disabled={busyKey === featureKey} onClick={() => onTrack(featured)}><Eye />加入智能追更</button>}</div>
      </div>
      {features.length > 1 && <div className="discover-carousel-controls" aria-label="轮播控制">
        <button type="button" className="discover-carousel-arrow" onClick={() => moveFeature(-1)} aria-label="上一张"><CaretLeft weight="bold" /></button>
        <div className="discover-carousel-dots" role="tablist" aria-label="选择推荐作品">
          {features.map((item, index) => <button
            type="button"
            role="tab"
            aria-selected={index === featureIndex}
            aria-label={`第 ${index + 1} 张：${item.title}`}
            className={index === featureIndex ? "active" : ""}
            onClick={() => setFeatureIndex(index)}
            key={`${item.media_type}-${item.tmdb_id}`}
          />)}
        </div>
        <button type="button" className="discover-carousel-arrow" onClick={() => moveFeature(1)} aria-label="下一张"><CaretRight weight="bold" /></button>
        <button type="button" className="discover-carousel-toggle" onClick={() => setCarouselPaused((value) => !value)} aria-label={carouselPaused ? "继续自动轮播" : "暂停自动轮播"}>
          {carouselPaused ? <Play weight="fill" /> : <Pause weight="fill" />}
        </button>
      </div>}
    </section>
    {orderedGroups.map((group) => <section className="discover-rail" key={group.key}>
      <header><div><h2>{group.title}</h2><p>{group.description}</p></div></header>
      <div className="discover-rail-track">
        {group.items.map((item) => <button type="button" className="discover-rail-card" key={`${group.key}-${item.media_type}-${item.tmdb_id}`} onClick={() => onSelect(item)}>
          <Poster item={item} />
          <strong>{item.title}</strong>
          <span>{item.year || item.release_date || "日期待定"}{item.vote_average ? ` · ${item.vote_average.toFixed(1)}` : ""}</span>
        </button>)}
      </div>
    </section>)}
  </div>;
}

export function MediaDetailScaffold({ media, onBack, strmStatus, children }: { media: MediaItem; onBack: () => void; strmStatus?: string; children: ReactNode }) {
  const release = media.release_date || media.year || "待定";
  return <div className="media-detail-page tg-media-detail">
    <button className="media-detail-back" onClick={onBack} title="返回发现">← 返回发现</button>
    <section className="media-detail-hero" style={media.backdrop_url ? { backgroundImage: `linear-gradient(90deg, rgba(5,12,29,.98) 0%, rgba(5,12,29,.88) 48%, rgba(5,12,29,.48) 100%), url(${media.backdrop_url})` } : undefined}>
      <Poster item={media} compact />
      <div className="media-detail-hero-copy">
        <span className="eyebrow">TMDB COLLECTION · {mediaTypeLabel(media)}</span>
        <h1>{media.title} {media.year && <small>({media.year})</small>}</h1>
        <div className="media-detail-pills">
          <span className="rating"><Star weight="fill" />{media.vote_average?.toFixed(1) || "待评分"}</span>
          <span>{mediaTypeLabel(media)}</span><span>{media.year || "年份待定"}</span><span>{release}</span>
          {Boolean(media.runtime) && <span>{media.runtime} 分钟</span>}
          {strmStatus && <span className="strm-state-pill">{strmStatus}</span>}
        </div>
        <p>{media.overview || "暂无剧情简介。"}</p>
      </div>
    </section>
    <div className="media-detail-lower">
      <aside className="media-work-profile">
        <span className="eyebrow">WORK PROFILE</span><h2>作品资料</h2>
        <dl>
          <div><dt>类型</dt><dd>{mediaTypeLabel(media)}</dd></div>
          <div><dt>首映</dt><dd>{release}</dd></div>
          {Boolean(media.runtime) && <div><dt>时长</dt><dd>{media.runtime} 分钟</dd></div>}
          <div><dt>状态</dt><dd>{media.status || "未提供"}</dd></div>
        </dl>
        <div className="media-genre-list"><small>题材标签</small><div>{media.genres?.length ? media.genres.map((genre) => <span key={genre}>{genre}</span>) : <span>暂无标签</span>}</div></div>
      </aside>
      <section className="media-action-workbench">
        <header><div><span className="eyebrow">MEDIAINDEX WORKFLOW</span><h2>核对与转存</h2></div><div className="workflow-symbol"><FilmSlate /><PlayCircle /></div></header>
        {children}
      </section>
    </div>
  </div>;
}

function mediaTypeLabel(media: MediaItem) {
  if (media.category === "variety" || media.media_type === "variety") return "综艺";
  if (media.category === "concert") return "演唱会";
  if (media.category === "documentary") return "纪录片";
  if (media.category === "anime") return "动漫";
  return media.media_type === "movie" ? "电影" : "电视剧";
}
