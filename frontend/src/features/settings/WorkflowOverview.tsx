import {
  ArrowRight,
  Binoculars,
  Broadcast,
  CheckCircle,
  CloudArrowDown,
  File,
  HardDrives,
  Heart,
  MagnifyingGlass,
  PaperPlaneTilt,
  Play,
  ShareNetwork,
  TelevisionSimple,
  WarningCircle,
  WebhooksLogo,
} from "@phosphor-icons/react";
import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import type { AppRoute } from "../../app/routes";
import { api, type ConfigStatus } from "../../lib/api";
import "./workflow-overview.css";

export type WorkflowOverviewSettingsTarget = "basic" | "records" | "webhook";

type WorkflowNode = {
  key: string;
  label: string;
  eyebrow: string;
  description: string;
  statusDetail: string;
  configured: boolean;
  icon: ReactNode;
  routeLabel: string;
  onOpen: () => void;
};

function hasPath(value: string) {
  return Boolean(String(value || "").trim());
}

function WorkflowNodeButton({ node }: { node: WorkflowNode }) {
  const stateLabel = node.configured ? "已配置" : "待配置";
  return (
    <button
      type="button"
      className={`workflow-node workflow-node-source ${node.configured ? "configured" : "pending"}`}
      onClick={node.onOpen}
      aria-label={`${node.label}，${stateLabel}，打开${node.routeLabel}`}
    >
      <span className="workflow-node-topline">
        <span className="workflow-node-icon" aria-hidden>{node.icon}</span>
        <span className="workflow-node-state">{node.configured ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}{stateLabel}</span>
      </span>
      <span className="workflow-node-copy">
        <small>{node.eyebrow}</small>
        <strong>{node.label}</strong>
        <span>{node.description}</span>
      </span>
      <span className="workflow-node-detail">{node.statusDetail}</span>
      <span className="workflow-node-link">打开{node.routeLabel}<ArrowRight aria-hidden /></span>
    </button>
  );
}

function FlowArrow() {
  return <span className="workflow-flow-arrow" aria-hidden><ArrowRight weight="bold" /></span>;
}

function WorkflowMergeConnector({ sourceCount }: { sourceCount: number }) {
  const inputPoints = sourceCount === 3 ? [12.67, 38, 63.33] : [19, 57];
  const paths = [
    ...inputPoints.map((y) => y === 38 ? "M 2 38 H 58" : `M 2 ${y} C 29 ${y}, 32 38, 58 38`),
    "M 58 38 H 98",
  ];
  return (
    <svg className="workflow-merge-connector" viewBox="0 0 100 76" preserveAspectRatio="none" aria-hidden>
      <g className="workflow-merge-connector-aura">
        {paths.map((path) => <path d={path} vectorEffect="non-scaling-stroke" key={`aura-${path}`} />)}
      </g>
      <g className="workflow-merge-connector-line">
        {paths.map((path) => <path d={path} vectorEffect="non-scaling-stroke" key={path} />)}
      </g>
    </svg>
  );
}

type WorkflowFlowItem =
  | { key: string; kind: "node"; node: WorkflowNode; label?: string; description?: string }
  | { key: string; kind: "milestone"; label: string; eyebrow: string; description: string; tone: "cloud" | "library" };

function WorkflowFlowStep({ item, sequence }: { item: WorkflowFlowItem; sequence: number }) {
  if (item.kind === "milestone") {
    return (
      <div className={`workflow-milestone ${item.tone}`} aria-label={`${sequence}. ${item.label}：${item.description}`}>
        <span className="workflow-step-number">{String(sequence).padStart(2, "0")}</span>
        <span className="workflow-milestone-icon" aria-hidden>{item.tone === "cloud" ? <CloudArrowDown weight="duotone" /> : <HardDrives weight="duotone" />}</span>
        <small>{item.eyebrow}</small>
        <strong>{item.label}</strong>
        <span>{item.description}</span>
      </div>
    );
  }
  const node = item.node;
  const stateLabel = node.configured ? "已配置" : "待配置";
  return (
    <button
      type="button"
      className={`workflow-flow-step ${node.configured ? "configured" : "pending"}`}
      onClick={node.onOpen}
      aria-label={`${sequence}. ${item.label || node.label}，${stateLabel}，打开${node.routeLabel}`}
    >
      <span className="workflow-step-number">{String(sequence).padStart(2, "0")}</span>
      <span className="workflow-step-icon" aria-hidden>{node.icon}</span>
      <span className="workflow-step-state">{node.configured ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}{stateLabel}</span>
      <strong>{item.label || node.label}</strong>
      <span>{item.description || node.description}</span>
      <small>打开{node.routeLabel}<ArrowRight aria-hidden /></small>
    </button>
  );
}

function WorkflowBranch({
  number,
  title,
  summary,
  target,
  tone,
  sources,
  items,
  footer,
}: {
  number: string;
  title: string;
  summary: string;
  target: string;
  tone: "direct" | "cloud";
  sources: WorkflowNode[];
  items: WorkflowFlowItem[];
  footer: string;
}) {
  return (
    <section className={`workflow-branch workflow-branch-${tone}`}>
      <header className="workflow-branch-heading">
        <span>{number}</span>
        <div><strong>{title}</strong><small>{summary}</small></div>
        <em>{target}</em>
      </header>
      <div className="workflow-branch-layout">
        <div className="workflow-branch-entries">
          <div className="workflow-branch-label"><strong>从这里进入</strong><small>{sources.length} 种入口共用本链路</small></div>
          <div className={`workflow-source-grid workflow-source-grid-${tone}`}>{sources.map((node) => <WorkflowNodeButton node={node} key={node.key} />)}</div>
        </div>
        <div className="workflow-branch-merge" aria-hidden>
          <WorkflowMergeConnector sourceCount={sources.length} />
          <span className="workflow-branch-merge-copy">入口在这里汇合，接着按顺序执行</span>
          <ArrowRight weight="bold" />
        </div>
        <div className="workflow-branch-process">
          <div className="workflow-branch-label"><strong>顺序处理</strong><small>箭头表示必须先完成前一步</small></div>
          <div className="workflow-branch-flow">
            {items.map((item, index) => <Fragment key={item.key}><WorkflowFlowStep item={item} sequence={index + 1} />{index < items.length - 1 && <FlowArrow />}</Fragment>)}
          </div>
          <p className="workflow-branch-footer">{footer}</p>
        </div>
      </div>
    </section>
  );
}

export function WorkflowOverview({
  onNavigate,
  onOpenSettings,
}: {
  onNavigate: (route: AppRoute) => void;
  onOpenSettings: (target: WorkflowOverviewSettingsTarget) => void;
}) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [error, setError] = useState("");

  const loadConfig = useCallback(async () => {
    setError("");
    try {
      setConfig(await api.config());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "链路配置读取失败");
    }
  }, []);

  useEffect(() => { void loadConfig(); }, [loadConfig]);

  const model = useMemo(() => {
    if (!config) return null;

    const nativeP115Ready = config.enabled_providers.includes("p115") && config.has_p115_cookie;
    const nativeQuarkReady = config.enabled_providers.includes("quark") && config.has_quark_cookie;
    const transferConfigured = nativeP115Ready || nativeQuarkReady;
    const resourceSourceConfigured = config.has_pansou || config.has_qas;
    const telegramConfigured = Boolean(config.telegram_enabled && config.has_telegram_token);
    const p115StrmConfigured = Boolean(
      nativeP115Ready
      && config.p115_strm_enabled
      && hasPath(config.p115_strm_source_root)
      && config.p115_strm_included_directories.length
      && hasPath(config.strm_output_root),
    );
    const quarkStrmConfigured = Boolean(
      nativeQuarkReady
      && config.quark_strm_enabled
      && hasPath(config.quark_strm_source_root)
      && config.quark_strm_included_directories.length
      && hasPath(config.strm_output_root),
    );
    const strmConfigured = p115StrmConfigured || quarkStrmConfigured;
    const selectedMdcStrmConfigured = config.mdc_webhook_provider === "p115" ? p115StrmConfigured : quarkStrmConfigured;
    const organizerProviderConfigured = (provider: "p115" | "quark") => {
      const enabled = provider === "p115" ? config.p115_cloud_download_organizer_enabled : config.quark_cloud_download_organizer_enabled;
      const connected = provider === "p115" ? nativeP115Ready : nativeQuarkReady;
      const libraryRoot = provider === "p115" ? config.p115_root_path : config.quark_root_path;
      const downloadRoot = provider === "p115" ? config.p115_cloud_download_path : config.quark_cloud_download_path;
      const scopeMode = provider === "p115" ? config.p115_cloud_download_organizer_scope_mode : config.quark_cloud_download_organizer_scope_mode;
      const directories = provider === "p115" ? config.p115_cloud_download_organizer_directories : config.quark_cloud_download_organizer_directories;
      return Boolean(enabled && connected && hasPath(libraryRoot) && hasPath(downloadRoot) && (scopeMode === "all" || directories.length));
    };
    const organizerProviders = (["p115", "quark"] as const).filter(organizerProviderConfigured);
    const organizerConfigured = Boolean(config.has_tmdb_key && config.cloud_download_organizer_triggers.length && organizerProviders.length);
    const interactiveCloudProviders = (["p115", "quark"] as const).filter((provider) => (
      provider === "p115"
        ? nativeP115Ready && hasPath(config.p115_cloud_download_path)
        : nativeQuarkReady && hasPath(config.quark_cloud_download_path)
    ));
    const interactiveCloudConfigured = interactiveCloudProviders.length > 0;
    const mdcConfigured = Boolean(
      config.mdc_webhook_enabled
      && config.has_mdc_webhook_token
      && selectedMdcStrmConfigured,
    );
    const discoveryConfigured = config.has_tmdb_key && resourceSourceConfigured;
    const trackingConfigured = config.tracking_scheduler_enabled && discoveryConfigured && transferConfigured;
    const wishlistConfigured = config.wishlist_scheduler_enabled && discoveryConfigured && transferConfigured;
    const namingConfigured = Boolean(
      config.has_tmdb_key
      && config.media_folder_naming_rule
      && config.movie_naming_rule
      && config.episode_naming_rule,
    );
    const embyConfigured = Boolean(config.emby_base_url && config.has_emby_api_key && config.emby_library_refresh_enabled);
    const strmTarget = p115StrmConfigured || config.mdc_webhook_provider === "p115" ? "p115" : "quark";

    const sources: WorkflowNode[] = [
      {
        key: "telegram", label: "TG 频道追踪", eyebrow: "频道资源入口", configured: telegramConfigured,
        description: "按频道规则筛选分享资源，先转存到云下载文件夹等待统一整理。",
        statusDetail: telegramConfigured ? "Telegram Bot 已配置；频道规则在资源获取页维护" : "请配置 Telegram Bot 与频道规则",
        icon: <Broadcast size={23} weight="duotone" />, routeLabel: "TG 频道追踪",
        onOpen: () => onNavigate({ page: "workspace", section: "sources" }),
      },
      {
        key: "discover", label: "发现", eyebrow: "TMDB + 资源来源", configured: discoveryConfigured,
        description: "从探索、搜索与排行内容发起资源获取。",
        statusDetail: discoveryConfigured ? "TMDB 与资源来源已保存" : "请补充 TMDB 和 PanSou / QAS 资源来源",
        icon: <Binoculars size={23} weight="duotone" />, routeLabel: "资源获取设置",
        onOpen: () => onNavigate({ page: "workspace", section: "sources" }),
      },
      {
        key: "cloud-download", label: "外部投递 / 目录监测", eyebrow: "已落盘文件入口", configured: organizerConfigured,
        description: "外部工具已把原始文件放入授权子目录，由 MediaIndex 监测并接管整理。",
        statusDetail: organizerConfigured ? `${organizerProviders.map((value) => value === "p115" ? "115" : "夸克").join("、")} 云下载整理已保存` : "请开启网盘、设置根目录与整理范围",
        icon: <CloudArrowDown size={23} weight="duotone" />, routeLabel: "云下载整理",
        onOpen: () => onNavigate({ page: "workspace", section: "cloud-download" }),
      },
      {
        key: "tracking", label: "智能追更", eyebrow: "持续追踪", configured: trackingConfigured,
        description: "按播出日期与设定时间检查新集并转存。",
        statusDetail: trackingConfigured ? "巡检、资源来源与转存网盘已配置" : "请检查追更巡检、资源来源与网盘",
        icon: <TelevisionSimple size={23} weight="duotone" />, routeLabel: "智能追更",
        onOpen: () => onNavigate({ page: "subscriptions", section: "tracking" }),
      },
      {
        key: "wishlist", label: "愿望单", eyebrow: "定时巡检", configured: wishlistConfigured,
        description: "暂无资源的媒体保持巡检，命中后进入转存。",
        statusDetail: wishlistConfigured ? "巡检、资源来源与转存网盘已配置" : "请检查愿望单巡检、资源来源与网盘",
        icon: <Heart size={23} weight="duotone" />, routeLabel: "愿望单",
        onOpen: () => onNavigate({ page: "subscriptions", section: "wishlist" }),
      },
      {
        key: "paste-link", label: "链接 / 浏览器插件", eyebrow: "互动与分享页入口", configured: interactiveCloudConfigured,
        description: "粘贴链接或从 115、夸克分享页选定云下载子目录。",
        statusDetail: interactiveCloudConfigured
          ? `${interactiveCloudProviders.map((value) => value === "p115" ? "115" : "夸克").join("、")} 云下载入口已配置`
          : "请至少配置一个原生网盘连接与云下载路径",
        icon: <PaperPlaneTilt size={23} weight="duotone" />, routeLabel: "云下载设置",
        onOpen: () => onNavigate({ page: "workspace", section: "cloud-download" }),
      },
      {
        key: "mdc", label: "Webhook 引入媒体", eyebrow: "外部完成通知", configured: mdcConfigured,
        description: "接收外部媒体整理完成通知，优先定点生成 STRM。",
        statusDetail: mdcConfigured ? "Webhook 凭据与 STRM 范围已配置" : "请补充 Webhook 凭据与 STRM 范围",
        icon: <WebhooksLogo size={23} weight="duotone" />, routeLabel: "Webhook 设置",
        onOpen: () => onNavigate({ page: "workspace", section: "webhook" }),
      },
    ];

    const core: WorkflowNode[] = [
      {
        key: "transfer", label: "资源转存", eyebrow: "转存执行", configured: transferConfigured,
        description: "按来源调用 115 或夸克；互动内容先落入云下载暂存。",
        statusDetail: transferConfigured ? `${nativeP115Ready ? "115" : ""}${nativeP115Ready && nativeQuarkReady ? " · " : ""}${nativeQuarkReady ? "夸克" : ""} 原生转存连接已配置` : "请至少完成一个原生网盘连接",
        icon: <ShareNetwork size={23} weight="duotone" />, routeLabel: "网盘连接",
        onOpen: () => onNavigate({ page: "workspace", section: "connections" }),
      },
      {
        key: "tmdb", label: "TMDB 核验", eyebrow: "身份核验", configured: config.has_tmdb_key,
        description: "核对媒体标题、年份、类型与季集身份。",
        statusDetail: config.has_tmdb_key ? "TMDB API Key 已配置" : "请配置 TMDB API Key",
        icon: <MagnifyingGlass size={23} weight="duotone" />, routeLabel: "全局设置",
        onOpen: () => onOpenSettings("basic"),
      },
      {
        key: "organize", label: "改名与整理", eyebrow: "命名整理", configured: namingConfigured,
        description: "结合 TMDB 与身份提示标准化命名，再从云下载转入媒体库。",
        statusDetail: namingConfigured ? "媒体、电影与剧集命名规则已配置" : "请补充 TMDB 与命名规则",
        icon: <File size={23} weight="duotone" />, routeLabel: "转存和整理规则",
        onOpen: () => onNavigate({ page: "workspace", section: "rules" }),
      },
      {
        key: "strm", label: "STRM 生成", eyebrow: "媒体库输出", configured: strmConfigured,
        description: "按已授权的网盘范围生成或定点更新 STRM。",
        statusDetail: strmConfigured ? `${p115StrmConfigured ? "115" : ""}${p115StrmConfigured && quarkStrmConfigured ? " · " : ""}${quarkStrmConfigured ? "夸克" : ""} STRM 范围已配置` : "请开启网盘 STRM，选择范围与输出目录",
        icon: <Play size={23} weight="duotone" />, routeLabel: `${strmTarget === "p115" ? "115" : "夸克"} STRM 设置`,
        onOpen: () => onNavigate({ page: "strm", section: strmTarget }),
      },
      {
        key: "emby", label: "Emby 入库", eyebrow: "媒体服务器", configured: embyConfigured,
        description: "STRM 完成后调用 Emby 媒体库刷新。",
        statusDetail: embyConfigured ? "Emby 地址、API Key 与自动刷新已配置" : "请配置 Emby 连接并开启入库刷新",
        icon: <HardDrives size={23} weight="duotone" />, routeLabel: "Emby 与入库设置",
        onOpen: () => onNavigate({ page: "strm", section: "emby" }),
      },
    ];

    return { sources, core, configuredCount: [...sources, ...core].filter((node) => node.configured).length };
  }, [config, onNavigate, onOpenSettings]);

  if (!config) {
    return <section className="workflow-overview-page">{error ? <div className="workflow-overview-load error" role="alert"><WarningCircle weight="fill" /><div><strong>链路配置读取失败</strong><span>{error}</span></div><button type="button" className="ghost compact-action" onClick={() => void loadConfig()}>重试</button></div> : <div className="workflow-overview-load"><span className="workflow-overview-loader" aria-hidden /><strong>正在读取链路配置</strong></div>}</section>;
  }

  if (!model) return null;
  const totalCount = model.sources.length + model.core.length;
  const source = (key: string) => model.sources.find((node) => node.key === key)!;
  const core = (key: string) => model.core.find((node) => node.key === key)!;
  const directSources = [source("discover"), source("tracking"), source("wishlist")];
  const cloudSources = [source("cloud-download"), source("paste-link"), source("telegram")];
  const directFlow: WorkflowFlowItem[] = [
    { key: "direct-tmdb", kind: "node", node: core("tmdb"), label: "资源核验", description: "核对标题、年份、类型与季集身份。" },
    { key: "direct-name", kind: "node", node: core("organize"), label: "生成标准命名", description: "在写入前生成正式媒体库路径与文件名。" },
    { key: "direct-transfer", kind: "node", node: core("transfer"), label: "原生转存", description: "按标准名直接写入 115 或夸克正式媒体库。" },
    { key: "direct-library", kind: "milestone", tone: "library", eyebrow: "物理落点", label: "正式媒体库", description: "/媒体库/<分类>/<片名>" },
    { key: "direct-strm", kind: "node", node: core("strm") },
    { key: "direct-emby", kind: "node", node: core("emby") },
  ];
  const cloudFlow: WorkflowFlowItem[] = [
    { key: "cloud-transfer", kind: "node", node: core("transfer"), label: "接收 / 发现原始文件", description: "链接由 MediaIndex 原样转存；外部投递则在授权目录中被发现。" },
    { key: "cloud-inbox", kind: "milestone", tone: "cloud", eyebrow: "临时落点", label: "云下载文件夹", description: "/云下载/<分类>；此时尚未入库" },
    { key: "cloud-tmdb", kind: "node", node: core("tmdb"), label: "TMDB 匹配", description: "事件或定时任务触发后，核对媒体身份。" },
    { key: "cloud-organize", kind: "node", node: core("organize"), label: "改名与整理", description: "规范目录与文件名，复制或移动到正式库。" },
    { key: "cloud-library", kind: "milestone", tone: "library", eyebrow: "整理后落点", label: "正式媒体库", description: "/媒体库/<分类>/<片名>" },
    { key: "cloud-strm", kind: "node", node: core("strm") },
    { key: "cloud-emby", kind: "node", node: core("emby") },
  ];

  return (
    <section className="workflow-overview-page">
      <div className="page-head workflow-overview-head">
        <div><p className="eyebrow">AUTOMATION OVERVIEW</p><h1>全流程自动化概览</h1><p>查看资源入口、转存、核验整理、STRM 生成和 Emby 入库，并检查每个环节的配置状态。</p></div>
        <div className="workflow-overview-summary" aria-label={`${model.configuredCount} 个环节已配置，${totalCount - model.configuredCount} 个环节待配置`}>
          <span><strong>{model.configuredCount}</strong><small>/ {totalCount}</small></span>
          <div><strong>必需配置完整度</strong><small>{totalCount - model.configuredCount ? `还有 ${totalCount - model.configuredCount} 个环节待配置` : "全部环节已配置"}</small></div>
        </div>
      </div>

      <div className="workflow-overview-legend">
        <div><span className="workflow-legend-item configured"><CheckCircle weight="fill" />已配置</span><span className="workflow-legend-item pending"><WarningCircle weight="fill" />待配置</span></div>
        <p>状态仅表示必需配置已保存，不代表外部服务的实时健康状态；可点击节点进入对应页面测试。</p>
      </div>

      <div className="workflow-map" aria-label="MediaIndex 资源处理链路图">
        <div className="workflow-branches">
          <WorkflowBranch
            number="01"
            title="直接入库媒体链"
            summary="已知道媒体身份，核验并命名后直接写入正式媒体库"
            target="目标：正式媒体库"
            tone="direct"
            sources={directSources}
            items={directFlow}
            footer="这条链不经过云下载文件夹；转存成功时，资源已在正式媒体库。"
          />
          <WorkflowBranch
            number="02"
            title="云下载暂存整理链"
            summary="链接先接收、外部投递直接发现；两者在云下载文件夹汇合后统一整理"
            target="第一落点：云下载文件夹"
            tone="cloud"
            sources={cloudSources}
            items={cloudFlow}
            footer="关闭“匹配改名并整理入库”时，流程停在云下载文件夹；开启后才会继续到正式媒体库、STRM 和 Emby。"
          />
        </div>

        <aside className="workflow-mdc-bypass">
          <WorkflowNodeButton node={source("mdc")} />
          <div className="workflow-mdc-bypass-content">
            <div className="workflow-mdc-bypass-heading"><WebhooksLogo size={24} weight="duotone" /><div><strong>03 · Webhook 增量旁路</strong><small>外部已完成整理的媒体文件</small></div></div>
            <div className="workflow-mdc-bypass-line" aria-label="外部 Webhook 引入的媒体不经过 MediaIndex 改名，增量生成 STRM 后通知 Emby 入库">
              <span>Webhook 引入媒体</span><ArrowRight weight="bold" aria-hidden /><strong>由外部工具整理，不经过 MediaIndex 改名</strong><ArrowRight weight="bold" aria-hidden /><span>STRM 增量生成</span><ArrowRight weight="bold" aria-hidden /><span>Emby 入库</span>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
