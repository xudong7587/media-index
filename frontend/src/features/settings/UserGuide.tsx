import {
  ArrowRight, Binoculars, Broadcast, CloudArrowDown, GearSix, HardDrives, Heart,
  ListChecks, Play, ShieldCheck, SlidersHorizontal, TelevisionSimple, Wrench,
} from "@phosphor-icons/react";
import type { ComponentType } from "react";

import type { AppRoute } from "../../app/routes";
import "./user-guide.css";

type Chapter = {
  id: string; number: string; title: string; summary: string; icon: ComponentType<{ weight?: "duotone" }>;
  route?: AppRoute; routeLabel?: string; steps: { title: string; body: string; done: string }[];
  notes?: string[];
};

const chapters: Chapter[] = [
  { id: "start", number: "01", title: "第一次配置", summary: "先连通身份、网盘和目录，再逐项开启自动化。", icon: GearSix, route: { page: "system", section: "basic" }, routeLabel: "全局设置", steps: [
    { title: "登录与基础服务", body: "首次部署后修改管理密码，在全局设置填写 TMDB API Key 与时区；需要代理时先测试代理，再测试 TMDB。", done: "TMDB 测试成功，页面可显示海报和标准媒体信息。" },
    { title: "连接至少一个网盘", body: "在网盘工作台连接 115 或夸克，保存 Cookie 或完成扫码，并使用同页测试读取根目录。两家网盘可并存，但凭据和任务彼此独立。", done: "连接状态为可用，能够浏览目标网盘目录。" },
    { title: "划定两个根目录", body: "分别设置正式媒体库根与云下载根，再勾选允许整理的直属分类目录。两个根不能重叠，正式库不能放在云下载根内部。", done: "页面能列出电影、电视剧等直属分类，且危险重叠校验通过。" },
    { title: "先做一次小范围验收", body: "用熟悉的一部电影做单次转存，确认网盘目标、标准命名、STRM 和 Emby 后，再开启追更、频道和定时任务。", done: "文件进入预期正式目录，播放链路可用。" },
  ], notes: ["所有 Cookie、Token 和 API Key 只保存在自己的服务端；页面不会回显完整凭据。", "不用的外部服务保持关闭，不需要为了完成首次配置而全部接入。"] },
  { id: "sources", number: "02", title: "资源从哪里进入", summary: "先分清“检索候选”和“自动接收”，避免规则互相污染。", icon: Binoculars, route: { page: "workspace", section: "sources" }, routeLabel: "资源获取", steps: [
    { title: "发现与 PanSou", body: "发现页先用 TMDB 建立标准身份，再由 PanSou 检索候选分享。PanSou 的反向关键词只过滤搜索结果，不控制 TG。", done: "测试搜索成功，结果中不再出现已排除词。" },
    { title: "TG 频道追踪", body: "每个频道单独设置正向词、反向词、启用状态、自动转存和目标目录。正向词为空表示全部允许；反向词命中任意一个即拒绝。", done: "频道目录显示为有效规则，而不是“待配置”。" },
    { title: "网页或互动链接", body: "网页、浏览器扩展、企业微信和 Telegram 可提交夸克、115、磁力、ED2K 或 HTTP 链接。名称不统一的内容默认进入云下载暂存。", done: "任务中心出现可追踪任务，消息渠道收到安全摘要。" },
    { title: "外部下载 Webhook", body: "MDC-NG 等工具完成整理后，可通过 Webhook 通知 MediaIndex 对已授权目标路径执行只增不删的 STRM 处理。", done: "事件关联到唯一任务并结束等待，不再持续转圈。" },
  ], notes: ["TG 自动分类只有在媒体类别和云下载直属目录都唯一时才执行；无法判断时安全失败。", "PanSou 搜索其已配置的公开频道；MediaIndex Bot 只接收已加入频道后的新帖，私有频道填写 -100… 数字 ID。"] },
  { id: "storage", number: "03", title: "云下载与正式媒体库", summary: "不规范资源先暂存，核验和改名完成后才进入正式库。", icon: HardDrives, route: { page: "workspace", section: "cloud-download" }, routeLabel: "云下载", steps: [
    { title: "暂存原始资源", body: "TG、互动链接、磁力和外部投递进入 /云下载/<分类>。此处保留来源命名，不直接作为正式媒体资产生成最终 STRM。", done: "任务目标位于所选云下载直属子目录。" },
    { title: "等待内容稳定", body: "整理器先等待下载或转存稳定，再尝试 TMDB 唯一匹配、季集识别和标准命名；信息不足时进入待确认。", done: "任务显示明确识别结果或明确的待确认原因。" },
    { title: "复制或移动到正式库", body: "复制模式保留来源；移动模式仅在全部目标逐文件核验后按精确文件 ID 清理来源，绝不按模糊目录名删除。", done: "正式库出现标准目录，任务保存目标证据。" },
    { title: "继续后处理", body: "正式目标核验后复用现有流程：定点更新 STRM，按配置刷新 Emby，并发送完成通知。", done: "STRM 有实际增量，Emby 能扫描并播放。" },
  ], notes: ["“全部分类”仍会排除与正式媒体库重叠的危险路径。", "判断不唯一时选择待确认比猜测目录、片名或任务完成更安全。"] },
  { id: "direct", number: "04", title: "身份明确时直接入库", summary: "发现、愿望单和追更持有 TMDB 身份时，可跳过暂存整理。", icon: CloudArrowDown, route: { page: "discover" }, routeLabel: "发现", steps: [
    { title: "选择标准媒体", body: "在发现或详情页确认电影/剧集、年份、季数和目标网盘，避免只凭来源标题判断身份。", done: "任务拥有 TMDB ID、媒体类型和明确季数。" },
    { title: "核验候选资源", body: "候选需要通过分享有效性、类型、标题与季集证据检查；多季内容按季处理，证据不足进入待确认。", done: "目标与命名计划唯一。" },
    { title: "直接写入正式库", body: "按分类和标准命名转存到正式媒体库，并在目标真实存在后触发 STRM 与 Emby。", done: "无需经过云下载，正式库形成规范结构。" },
  ] },
  { id: "automation", number: "05", title: "追更、愿望单与频道", summary: "三种自动化解决不同问题，过滤规则互不共用。", icon: Heart, route: { page: "subscriptions" }, routeLabel: "订阅与追更", steps: [
    { title: "智能追更", body: "用于已有的连载媒体，结合播出日期与云端已存集数巡检到期新集。默认不把历史缺集当成当天更新。", done: "追更卡片显示作品状态、已存进度和下次检查。" },
    { title: "愿望单", body: "用于尚未找到可靠资源的标准媒体，按间隔重新检索；只有高置信候选才自动建任务，其余进入待确认。", done: "愿望单保留标准身份和检索策略。" },
    { title: "TG 频道", body: "用于持续接收频道发布。每个频道的正反关键词、分类模式和目录都独立保存，适合不同质量偏好的来源。", done: "频道消息能说明匹配、拒绝或转存结果。" },
  ] },
  { id: "playback", number: "06", title: "STRM、302 与 Emby", summary: "正式媒体是源，STRM 是播放映射，Emby 负责展示。", icon: Play, route: { page: "strm" }, routeLabel: "STRM 与 302", steps: [
    { title: "配置 STRM 范围", body: "分别选择 115/夸克来源根和允许处理的直属分类，设置本地 STRM 输出目录。已有网盘库也可从这里直接开始。", done: "预览范围准确，不包含云下载暂存或无关目录。" },
    { title: "生成与维护", body: "首次运行全量扫描，后续使用增量或定时任务。普通增量只新增/更新；删除需完整扫描、连续缺失确认和熔断保护。", done: "本地 STRM 与已核验云端文件一一对应。" },
    { title: "接入 Emby", body: "让 Emby 扫描 STRM 输出目录。只有 STRM 实际新增或替换时才请求对应媒体库刷新；图文入库通知等待 Emby 回执。", done: "Emby 识别媒体，客户端经独立播放端口正常播放。" },
  ], notes: ["302 播放 URL 是长期访问凭证，不要公开、截图分享或写入日志。", "STRM 文件存在不等于网盘转存成功；任务完成必须以目标核验为证据。"] },
  { id: "integrations", number: "07", title: "媒体服务器与外部联动", summary: "按需接入 Emby、OpenList、Webhook 和消息渠道。", icon: TelevisionSimple, route: { page: "media-server" }, routeLabel: "媒体服务器", steps: [
    { title: "媒体服务器", body: "连接 Emby 后可查看媒体库、用户、播放会话和最近入库，并为媒体库制作封面。删除联动必须依赖精确映射。", done: "连接测试成功，目标媒体库可选择。" },
    { title: "OpenList 跨盘补齐", body: "当夸克已有而 115 缺失时，可在独立页面手动复制或开启受控自动补偿；单个提供方失败不覆盖另一方结果。", done: "来源、目标与授权范围明确。" },
    { title: "通知与交互", body: "站内、企业微信或 Telegram 可接收成功、失败和待确认，也可提交资源名和链接。先测试通知，再逐项启用事件。", done: "测试消息到达，回执不包含敏感链接或凭据。" },
  ] },
  { id: "operations", number: "08", title: "任务、日志与排障", summary: "先看任务状态与证据，再看日志定位原因。", icon: SlidersHorizontal, route: { page: "workspace", section: "tasks" }, routeLabel: "任务中心", steps: [
    { title: "理解任务状态", body: "任务中心是执行状态源；待确认保留需要人工选择的候选。运行日志只用于观察，不应单独决定任务是否完成。", done: "能定位当前步骤、目标、失败原因和下一动作。" },
    { title: "正确清理日志", body: "“清除历史”只隐藏终态记录，不停止正在执行的任务；“停止运行”只终止可停止的活动任务。每条任务可独立清除或停止。", done: "活动任务与历史记录的操作互不混淆。" },
    { title: "按顺序排障", body: "依次检查网盘连接、目录授权、关键词、TMDB 唯一性、文件稳定时间、任务目标证据和 STRM/Emby 配置；必要时导出后台诊断包。", done: "问题被归因到具体步骤，而不是重复提交同一任务。" },
  ] },
  { id: "safety", number: "09", title: "备份、升级与安全", summary: "先保住数据和回滚能力，再更新镜像。", icon: Wrench, steps: [
    { title: "升级前备份", body: "备份 data、strm、downloads 与 docker-compose.yaml；其中 data 包含数据库和网页设置，不能只备份镜像。", done: "备份可读、路径清晰，并保留当前镜像版本。" },
    { title: "拉取并重启", body: "执行 docker compose pull 与 docker compose up -d，保留原挂载；从 0.6.0 前版本升级时使用当前单容器双端口结构。", done: "管理面板与播放端口均可访问，链路概览状态正常。" },
    { title: "保护凭据与数据", body: "不要公开 Cookie、Token、API Key、播放 URL、配置导出或诊断包。删除、移动、跨盘复制都应保持最小授权范围。", done: "日志与截图不含敏感值，自动化只覆盖明确选择的目录。" },
  ], notes: ["遇到回滚需要同时考虑数据库版本；先阅读对应 Release 说明。", "MediaIndex 不提供资源，也不替用户判断版权；只处理用户自行配置和有权访问的内容。"] },
];

const chapterStepRoutes: Record<string, AppRoute[]> = {
  start: [
    { page: "system", section: "basic" }, { page: "workspace", section: "connections" },
    { page: "workspace", section: "cloud-download" }, { page: "discover" },
  ],
  sources: [
    { page: "workspace", section: "sources" }, { page: "workspace", section: "sources-tg" },
    { page: "system", section: "interaction" }, { page: "workspace", section: "webhook" },
  ],
  storage: [
    { page: "workspace", section: "cloud-download" }, { page: "workspace", section: "cloud-download" },
    { page: "workspace", section: "cloud-download" }, { page: "strm" },
  ],
  direct: [{ page: "discover" }, { page: "discover" }, { page: "workspace", section: "tasks" }],
  automation: [
    { page: "subscriptions", section: "tracking" }, { page: "subscriptions", section: "wishlist" },
    { page: "workspace", section: "sources-tg" },
  ],
  playback: [{ page: "strm" }, { page: "strm" }, { page: "media-server" }],
  integrations: [
    { page: "media-server" }, { page: "cross-cloud" }, { page: "system", section: "notifications" },
  ],
  operations: [
    { page: "workspace", section: "tasks" }, { page: "workspace", section: "tasks" },
    { page: "system", section: "basic" },
  ],
  safety: [
    { page: "system", section: "basic" }, { page: "system", section: "basic" },
    { page: "system", section: "basic" },
  ],
};

function FlowMap() {
  return <div className="guide-flow-map" aria-label="MediaIndex 两条主要流程"><div><small>入口</small><span>发现 · 愿望单 · 追更</span><span>TG · 链接 · 外部下载</span></div><ArrowRight /><div><small>按身份分流</small><span>身份明确 → 直接规范入库</span><span>名称不一 → 云下载暂存</span></div><ArrowRight /><div><small>统一后处理</small><span>正式媒体库</span><span>STRM → Emby → 通知</span></div></div>;
}

export function UserGuide({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  function scrollToChapter(id: string) {
    document.getElementById(`guide-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return <section className="user-guide-page">
    <header className="page-head user-guide-head"><div><p className="eyebrow">MEDIAINDEX HANDBOOK</p><h1>使用手册</h1><p>从“我要完成什么”出发，按整条媒体流程说明入口、目录、自动化、播放和维护。第一次使用按 01 → 09 阅读。</p></div><span className="guide-head-mark"><ShieldCheck weight="duotone" /><small>执行原则</small><strong>证据不足时停止并待确认</strong></span></header>
    <section className="guide-goals"><header><small>CHOOSE A PATH</small><h2>你现在要完成什么？</h2></header><div>
      <article><GearSix weight="duotone" /><span><strong>第一次配置</strong><small>从账号、网盘和目录开始</small></span></article>
      <article><Binoculars weight="duotone" /><span><strong>找资源或追踪频道</strong><small>PanSou 与 TG 独立设置</small></span></article>
      <article><CloudArrowDown weight="duotone" /><span><strong>整理云下载</strong><small>暂存、识别、改名和入库</small></span></article>
      <article><Play weight="duotone" /><span><strong>生成 STRM 并播放</strong><small>已有网盘媒体也可从这里开始</small></span></article>
    </div></section>
    <FlowMap />
    <div className="guide-layout"><nav className="guide-chapter-nav" aria-label="使用手册章节">{chapters.map(({ id, number, title, icon: Icon }) => <button type="button" onClick={() => scrollToChapter(id)} key={id}><span>{number}</span><Icon weight="duotone" /><strong>{title}</strong></button>)}</nav><div className="guide-chapters">{chapters.map((chapter) => {
      const Icon = chapter.icon;
      return <article id={`guide-${chapter.id}`} className="guide-chapter" key={chapter.id}><header><span><Icon weight="duotone" /></span><div><small>{chapter.number} · WORKFLOW</small><h2>{chapter.title}</h2><p>{chapter.summary}</p><p className="guide-card-hint">点击下方卡片跳转到对应设置页面。</p></div></header><ol className="guide-step-list">{chapter.steps.map((step, index) => { const route = chapterStepRoutes[chapter.id]?.[index]; return <li key={step.title}><button type="button" onClick={() => route && onNavigate(route)} disabled={!route}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{step.title}</strong><p>{step.body}</p><small><ListChecks weight="duotone" />完成标志：{step.done}</small></div><ArrowRight className="guide-step-arrow" /></button></li>; })}</ol>{chapter.notes?.length ? <aside className="guide-notes"><strong><ShieldCheck weight="duotone" />边界与注意事项</strong>{chapter.notes.map((note) => <p key={note}>{note}</p>)}</aside> : null}</article>;
    })}</div></div>
  </section>;
}
