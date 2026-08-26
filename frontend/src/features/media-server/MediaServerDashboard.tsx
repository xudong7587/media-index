import {
  ArrowClockwise,
  CheckCircle,
  Devices,
  FilmSlate,
  MonitorPlay,
  PaintBrushBroad,
  Palette,
  PlayCircle,
  Question,
  SlidersHorizontal,
  Sparkle,
  TextT,
  Television,
  UploadSimple,
  Users,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { ReactNode, useEffect, useRef, useState } from "react";

import { AppRoute } from "../../app/routes";
import { api, ApiError, ConfigStatus, CoverFont, CoverRenderOptions, EmbyDashboard } from "../../lib/api";

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
  const [coverRevision, setCoverRevision] = useState(0);

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
            {library.cover_item_id ? <DashboardImage src={`/api/integrations/emby/images/${encodeURIComponent(library.cover_item_id)}?v=${coverRevision}`} alt="" /> : <FilmSlate size={34} />}
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
    {coverStudioOpen ? <CoverGeneratorDialog libraries={data.libraries} onClose={() => setCoverStudioOpen(false)} onApplied={() => {
      setCoverRevision(Date.now());
      void load();
    }} /> : null}
  </section>;
}

function CoverGeneratorDialog({ libraries, onClose, onApplied }: {
  libraries: EmbyDashboard["libraries"];
  onClose: () => void;
  onApplied: () => void;
}) {
  const defaultOptions: CoverRenderOptions = {
    resolution: "1080p", source_sort: "Random", image_source: "Primary", zh_title: "", en_title: "",
    zh_font_id: "default", en_font_id: "default", zh_font_size: 170, en_font_size: 75, title_scale: 1,
    title_x_offset: 0, zh_font_offset: 0, title_spacing: 40, en_line_spacing: 40,
    blur_size: 50, showcase_blur: true, color_ratio: 0.8, bg_color_mode: "auto", custom_bg_color: "#2f6f57",
  };
  const [libraryId, setLibraryId] = useState(libraries[0]?.id || "");
  const library = libraries.find((item) => item.id === libraryId) || libraries[0];
  const [style, setStyle] = useState<CoverStyle>("collage");
  const [panel, setPanel] = useState<"basic" | "style" | "title" | "advanced">("basic");
  const [baseOptions, setBaseOptions] = useState<CoverRenderOptions>(defaultOptions);
  const [libraryOptions, setLibraryOptions] = useState<Record<string, CoverRenderOptions>>({});
  const [includedLibraryIds, setIncludedLibraryIds] = useState<string[]>([]);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleCron, setScheduleCron] = useState("0 3 * * 1");
  const [nonce, setNonce] = useState(0);
  const [previewUrl, setPreviewUrl] = useState("");
  const [fonts, setFonts] = useState<CoverFont[]>([{ id: "default", label: "MediaIndex 默认", source: "system" }]);
  const [uploadingFont, setUploadingFont] = useState<"zh" | "en" | "">("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const zhFontInput = useRef<HTMLInputElement>(null);
  const enFontInput = useRef<HTMLInputElement>(null);
  const libraryTitleOptions = library?.id ? libraryOptions[library.id] : undefined;
  const options: CoverRenderOptions = {
    ...baseOptions,
    zh_title: libraryTitleOptions?.zh_title || "",
    en_title: libraryTitleOptions?.en_title || "",
  };

  function setOptions(next: CoverRenderOptions) {
    setBaseOptions({ ...next, zh_title: "", en_title: "" });
    if (library?.id) setLibraryOptions((current) => ({ ...current, [library.id]: next }));
  }

  useEffect(() => { void api.config().then((config: ConfigStatus) => {
    setStyle(config.emby_cover_style || "collage");
    setBaseOptions({ ...defaultOptions, ...(config.emby_cover_options || {}) });
    setLibraryOptions(config.emby_cover_library_options || {});
    setIncludedLibraryIds(config.emby_cover_library_ids || []);
    setScheduleEnabled(config.emby_cover_refresh_enabled);
    setScheduleCron(config.emby_cover_refresh_cron || "0 3 * * 1");
  }); }, []);

  useEffect(() => { void api.embyCoverFonts().then((result) => setFonts(result.fonts)).catch(() => undefined); }, []);

  useEffect(() => {
    if (!library) {
      setPreviewUrl("");
      return;
    }
    const timer = window.setTimeout(() => {
      setPreviewUrl(coverPreviewUrl(library.id, library.name, style, options, nonce));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [library, nonce, options, style]);

  async function uploadFont(file: File | undefined, language: "zh" | "en") {
    if (!file) return;
    setUploadingFont(language);
    setMessage("");
    try {
      const result = await api.uploadEmbyCoverFont(file);
      setFonts((current) => current.some((font) => font.id === result.font.id) ? current : [...current, result.font]);
      setOptions({
        ...options,
        ...(language === "zh" ? { zh_font_id: result.font.id } : { en_font_id: result.font.id }),
      });
      setMessage(`${language === "zh" ? "中文" : "英文"}${result.message}，已应用到全部媒体库的文字样式`);
    } catch (reason) {
      setMessage(reason instanceof ApiError ? reason.message : "字体上传失败");
    } finally {
      setUploadingFont("");
      if (language === "zh" && zhFontInput.current) zhFontInput.current.value = "";
      if (language === "en" && enFontInput.current) enFontInput.current.value = "";
    }
  }

  async function applyCover() {
    if (!library) return;
    setSaving(true);
    setMessage("");
    try {
      const result = await api.applyEmbyLibraryCover(library.id, { title: library.name, style, options });
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
    try {
      const result = await api.refreshEmbyLibraryCovers(
        style,
        { ...baseOptions, zh_title: "", en_title: "" },
        includedLibraryIds,
        libraryOptions,
      );
      setMessage(result.message); onApplied();
    }
    catch (reason) { setMessage(reason instanceof ApiError ? reason.message : "批量封面生成失败"); }
    finally { setSaving(false); }
  }

  async function saveSettings() {
    setSaving(true); setMessage("");
    try {
      await api.saveConfig({
        emby_cover_refresh_enabled: scheduleEnabled,
        emby_cover_refresh_cron: scheduleCron.trim(),
        emby_cover_style: style,
        emby_cover_options: { ...baseOptions, zh_title: "", en_title: "" },
        emby_cover_library_ids: includedLibraryIds,
        emby_cover_library_options: libraryOptions,
      });
      setMessage(scheduleEnabled ? `封面设置已保存，下次将按“${describeCoverCron(scheduleCron)}”替换勾选的媒体库` : "封面设置已保存，定时刷新关闭");
    } catch (reason) { setMessage(reason instanceof ApiError ? reason.message : "封面设置保存失败"); }
    finally { setSaving(false); }
  }

  const stylePreviewOptions: CoverRenderOptions = {
    ...baseOptions,
    resolution: "480p",
    zh_title: "",
    en_title: "",
    zh_font_size: 118,
    en_font_size: 48,
  };

  return <div className="cover-generator-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <section className="cover-generator-dialog" role="dialog" aria-modal="true" aria-labelledby="cover-generator-title">
      <header><h2 id="cover-generator-title">Emby 媒体库封面生成</h2><button type="button" className="cover-generator-close" onClick={onClose} aria-label="关闭封面工坊" title="关闭"><X size={25} /></button></header>
      <section className="cover-workshop-hero">
        <span aria-hidden="true"><Palette size={29} weight="duotone" /></span><div><small>MEDIA COVER ATELIER</small><h3>封面控制台</h3><p>集中设置静态封面、标题与生成参数；不包含动态封面，确认后才写入 Emby。</p></div>
      </section>
      <div className="cover-workshop-toolbar">
        <label><span>预览媒体库</span><select value={library?.id || ""} onChange={(event) => setLibraryId(event.target.value)}>{libraries.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span>输出规格</span><select value={options.resolution} onChange={(event) => setOptions({ ...options, resolution: event.target.value as CoverRenderOptions["resolution"] })}><option value="1080p">1080p · 1920 × 1080 JPG</option><option value="720p">720p · 1280 × 720 JPG</option><option value="480p">480p · 854 × 480 JPG</option></select></label>
        <button type="button" className="ghost" disabled={!library} onClick={() => setNonce((value) => value + 1)}><ArrowClockwise />重新取样</button>
      </div>
      <div className="cover-workshop-editor">
        <aside className="cover-preview-console" aria-label="实时封面预览">
          <header><div><strong>实时预览</strong><span>{library?.name || "未选择媒体库"} · {resolutionLabel(options.resolution)}</span></div><em>参数停止调整 0.3 秒后更新</em></header>
          <CoverLivePreview src={previewUrl} alt={`${library?.name || "媒体库"}封面实时预览`} />
          <div className="cover-style-choices" role="group" aria-label="静态封面风格">
            {library ? coverStyles.map((item) => {
              const itemPreviewUrl = coverPreviewUrl(library.id, library.name, item.id, stylePreviewOptions, nonce);
              return <button type="button" className={`cover-style-choice ${style === item.id ? "active" : ""}`} key={item.id} onClick={() => setStyle(item.id)} aria-pressed={style === item.id} title={item.description}>
                <span><DashboardImage key={itemPreviewUrl} src={itemPreviewUrl} alt="" /></span><strong>{item.label}</strong>
              </button>;
            }) : null}
          </div>
        </aside>
        <div className="cover-control-console">
          <nav className="cover-config-tabs" aria-label="封面设置">
            <button type="button" className={panel === "basic" ? "active" : ""} onClick={() => setPanel("basic")}><SlidersHorizontal />基础设置</button>
            <button type="button" className={panel === "style" ? "active" : ""} onClick={() => setPanel("style")}><PaintBrushBroad />封面风格</button>
            <button type="button" className={panel === "title" ? "active" : ""} onClick={() => setPanel("title")}><TextT />标题设置</button>
            <button type="button" className={panel === "advanced" ? "active" : ""} onClick={() => setPanel("advanced")}><Palette />更多参数</button>
          </nav>
          <section className="cover-config-panel">
            {panel === "basic" ? <div className="cover-basic-settings">
              <div className="cover-basic-row">
                <label className="cover-toggle"><input type="checkbox" checked={scheduleEnabled} onChange={(event) => setScheduleEnabled(event.target.checked)} /><span><strong>定时更新封面</strong><small>按统一文字样式和各媒体库标题自动生成。</small></span></label>
                <label className="cover-cron-field">
                  <span>更新计划 <i title="5 位 Cron 顺序：分钟 小时 日期 月份 星期。例如 0 3 * * 1 表示每周一 03:00。"><Question size={17} /></i></span>
                  <input value={scheduleCron} spellCheck={false} placeholder="0 3 * * 1" onChange={(event) => setScheduleCron(event.target.value)} />
                  <small className={describeCoverCron(scheduleCron).startsWith("请输入") ? "invalid" : ""}>{describeCoverCron(scheduleCron)}</small>
                </label>
              </div>
              <fieldset className="cover-library-selection">
                <legend>更新媒体库</legend>
                <p>不勾选时更新全部；勾选后，批量生成和定时任务只处理所选媒体库。</p>
                <div>{libraries.map((item) => <label key={item.id}><input type="checkbox" checked={includedLibraryIds.includes(item.id)} onChange={(event) => setIncludedLibraryIds((current) => event.target.checked ? [...new Set([...current, item.id])] : current.filter((id) => id !== item.id))} /><span>{item.name}</span></label>)}</div>
              </fieldset>
              <div className="cover-basic-actions"><button type="button" className="primary" disabled={saving} onClick={() => void saveSettings()}>{saving ? "保存中…" : "保存封面设置"}</button></div>
            </div> : null}
            {panel === "style" ? <div className="cover-generator-fields">
              <CoverField label="封面来源"><select value={options.image_source} onChange={(event) => setOptions({ ...options, image_source: event.target.value as CoverRenderOptions["image_source"] })}><option value="Primary">海报图</option><option value="Backdrop">背景图</option></select></CoverField>
              <CoverField label="来源排序"><select value={options.source_sort} onChange={(event) => setOptions({ ...options, source_sort: event.target.value as CoverRenderOptions["source_sort"] })}><option value="Random">随机</option><option value="DateCreated">入库时间</option><option value="PremiereDate">首播日期</option></select></CoverField>
              <CoverField label="多海报风格背景"><select value={options.showcase_blur ? "blur" : "gradient"} onChange={(event) => setOptions({ ...options, showcase_blur: event.target.value === "blur" })}><option value="blur">模糊背景</option><option value="gradient">纯色渐变</option></select></CoverField>
              <CoverField label="背景颜色"><select value={options.bg_color_mode} onChange={(event) => setOptions({ ...options, bg_color_mode: event.target.value as CoverRenderOptions["bg_color_mode"] })}><option value="auto">从封面自动提取</option><option value="custom">使用自定义颜色</option></select></CoverField>
              {options.bg_color_mode === "custom" ? <CoverField label="自定义背景色"><input type="color" value={options.custom_bg_color} onChange={(event) => setOptions({ ...options, custom_bg_color: event.target.value })} /></CoverField> : null}
            </div> : null}
            {panel === "title" ? <div className="cover-title-settings">
              <section className="cover-title-copy">
                <p className="cover-title-note">中英文标题内容按媒体库分别保存；字体、字号、位置和间距对全部媒体库统一生效。</p>
                <CoverField label="中文标题"><input value={options.zh_title} placeholder={library?.name || "媒体库名称"} maxLength={28} onChange={(event) => setOptions({ ...options, zh_title: event.target.value })} /></CoverField>
                <CoverField label="英文标题"><input value={options.en_title} placeholder="例如 DOCUMENTARIES，可留空" maxLength={48} onChange={(event) => setOptions({ ...options, en_title: event.target.value })} /></CoverField>
                <div className="cover-font-setting">
                  <CoverField label="中文字体"><select value={options.zh_font_id} onChange={(event) => setOptions({ ...options, zh_font_id: event.target.value })}>{fonts.map((font) => <option key={`zh-${font.id}`} value={font.id}>{font.label}{font.source === "uploaded" ? " · 已上传" : ""}</option>)}</select></CoverField>
                  <button type="button" className="ghost" disabled={uploadingFont === "zh"} onClick={() => zhFontInput.current?.click()}><UploadSimple />{uploadingFont === "zh" ? "上传中" : "上传中文字体"}</button>
                  <input ref={zhFontInput} className="cover-font-file" type="file" accept=".ttf,.otf,.ttc,font/ttf,font/otf" onChange={(event) => void uploadFont(event.target.files?.[0], "zh")} />
                </div>
                <div className="cover-font-setting">
                  <CoverField label="英文字体"><select value={options.en_font_id} onChange={(event) => setOptions({ ...options, en_font_id: event.target.value })}>{fonts.map((font) => <option key={`en-${font.id}`} value={font.id}>{font.label}{font.source === "uploaded" ? " · 已上传" : ""}</option>)}</select></CoverField>
                  <button type="button" className="ghost" disabled={uploadingFont === "en"} onClick={() => enFontInput.current?.click()}><UploadSimple />{uploadingFont === "en" ? "上传中" : "上传英文字体"}</button>
                  <input ref={enFontInput} className="cover-font-file" type="file" accept=".ttf,.otf,.ttc,font/ttf,font/otf" onChange={(event) => void uploadFont(event.target.files?.[0], "en")} />
                </div>
              </section>
              <section className="cover-fine-tune">
                <header><strong>文字微调</strong><span>拖动时实时反馈到左侧预览</span></header>
                <CoverRange label="中文大小" value={options.zh_font_size} min={48} max={320} onChange={(value) => setOptions({ ...options, zh_font_size: value })} />
                <CoverRange label="英文大小" value={options.en_font_size} min={24} max={180} onChange={(value) => setOptions({ ...options, en_font_size: value })} />
                <CoverRange label="水平位置" value={options.title_x_offset} min={-500} max={500} onChange={(value) => setOptions({ ...options, title_x_offset: value })} />
                <CoverRange label="垂直位置" value={options.zh_font_offset} min={-300} max={300} onChange={(value) => setOptions({ ...options, zh_font_offset: value })} />
                <CoverRange label="中英文间距" value={options.title_spacing} min={-100} max={300} onChange={(value) => setOptions({ ...options, title_spacing: value })} />
                <CoverRange label="英文行距" value={options.en_line_spacing} min={-100} max={300} onChange={(value) => setOptions({ ...options, en_line_spacing: value })} />
              </section>
            </div> : null}
            {panel === "advanced" ? <div className="cover-generator-fields">
              <CoverNumber label="标题整体缩放 (%)" value={Math.round(options.title_scale * 100)} min={50} max={200} onChange={(value) => setOptions({ ...options, title_scale: value / 100 })} />
              <CoverNumber label="背景模糊强度" value={options.blur_size} min={0} max={150} onChange={(value) => setOptions({ ...options, blur_size: value })} />
              <CoverNumber label="主题色混合比例 (%)" value={Math.round(options.color_ratio * 100)} min={0} max={100} onChange={(value) => setOptions({ ...options, color_ratio: value / 100 })} />
            </div> : null}
            {!library ? <p className="dashboard-inline-empty">没有可生成封面的媒体库。</p> : null}
          </section>
        </div>
      </div>
      {message ? <p className="cover-generator-message">{message}</p> : null}
      <footer><button type="button" className="ghost" disabled={saving || !library} onClick={() => void applyCover()}>立即替换预览媒体库</button><button type="button" className="primary" disabled={saving || !libraries.length} onClick={() => void applyAll()}>{saving ? "生成中…" : includedLibraryIds.length ? `立即替换全部勾选媒体库（${includedLibraryIds.length}）` : "立即替换全部媒体库"}</button></footer>
    </section>
  </div>;
}

function CoverField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="cover-config-field"><span>{label}</span>{children}</label>;
}

function CoverNumber({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <CoverField label={label}><input type="number" value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value) || 0)} /></CoverField>;
}

function CoverRange({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <label className="cover-range-field"><span>{label}</span><input type="range" value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value))} /><input type="number" value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value) || 0)} /></label>;
}

function CoverLivePreview({ src, alt }: { src: string; alt: string }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => { setState("loading"); }, [src]);
  return <div className={`cover-live-preview ${state}`}>
    {src ? <img key={src} src={src} alt={alt} onLoad={() => setState("ready")} onError={() => setState("error")} /> : null}
    {state === "loading" ? <span>正在生成预览</span> : null}
    {state === "error" ? <span><WarningCircle />预览生成失败，请检查媒体库海报或字体文件</span> : null}
  </div>;
}

function coverPreviewUrl(libraryId: string, title: string, style: CoverStyle, options: CoverRenderOptions, nonce: number) {
  return `/api/integrations/emby/libraries/${encodeURIComponent(libraryId)}/cover-preview?title=${encodeURIComponent(title)}&style=${style}&options=${encodeURIComponent(JSON.stringify(options))}&sample=${nonce}`;
}

function describeCoverCron(value: string) {
  const parts = value.trim().split(/\s+/);
  if (parts.length !== 5) return "请输入 5 位 Cron：分钟 小时 日期 月份 星期";
  const [minute, hour, day, month, weekday] = parts;
  if (/^\d+$/.test(minute) && /^\d+$/.test(hour)) {
    const time = `${String(Number(hour)).padStart(2, "0")}:${String(Number(minute)).padStart(2, "0")}`;
    const weekdayLabels: Record<string, string> = { "0": "周日", "1": "周一", "2": "周二", "3": "周三", "4": "周四", "5": "周五", "6": "周六", "7": "周日" };
    if (day === "*" && month === "*" && weekdayLabels[weekday]) return `每${weekdayLabels[weekday]} ${time}`;
    if (day === "*" && /^\d+$/.test(month) && weekday === "*") return `每年 ${Number(month)} 月每天 ${time}`;
    if (/^\d+$/.test(day) && month === "*" && weekday === "*") return `每月 ${Number(day)} 日 ${time}`;
    if (day === "*" && month === "*" && weekday === "*") return `每天 ${time}`;
  }
  if (minute === "0" && /^\*\/\d+$/.test(hour) && day === "*" && month === "*" && weekday === "*") return `每 ${hour.slice(2)} 小时的整点`;
  return `已设置：${parts.join(" ")}`;
}

function resolutionLabel(value: CoverRenderOptions["resolution"]) {
  return value === "720p" ? "1280 × 720" : value === "480p" ? "854 × 480" : "1920 × 1080";
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
