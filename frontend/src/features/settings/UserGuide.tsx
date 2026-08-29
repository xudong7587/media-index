import { Binoculars, CloudArrowDown, HardDrives, ListChecks, Play, SlidersHorizontal } from "@phosphor-icons/react";

import "./user-guide.css";

const steps = [
  [Binoculars, "01 · 准备资源来源", "配置 TMDB 与 PanSou；如需频道自动化，再配置 Telegram Bot 和频道规则。"],
  [HardDrives, "02 · 连接网盘", "连接 115 或夸克并设置正式媒体库根、云下载根及各分类一级目录。"],
  [CloudArrowDown, "03 · 选择入库路径", "已知媒体身份可直接规范入库；互动链接、TG 与外部下载先进入云下载暂存。"],
  [ListChecks, "04 · 自动核验整理", "整理器在授权范围内等待文件稳定，唯一匹配 TMDB 后改名并复制或移动到正式库。"],
  [Play, "05 · STRM 与 Emby", "正式库目标核验完成后，既有后处理会定点生成 STRM，并按设置刷新 Emby。"],
  [SlidersHorizontal, "06 · 日常维护", "在链路概览检查缺失配置；运行日志中的“清除历史”和“停止运行”互不影响。"],
] as const;

export function UserGuide() {
  return <section className="user-guide-page">
    <header className="page-head user-guide-head"><div><p className="eyebrow">MEDIAINDEX HANDBOOK</p><h1>使用手册</h1><p>从资源进入到正式媒体库、STRM 与 Emby 的完整操作顺序。</p></div></header>
    <div className="user-guide-flow">{steps.map(([Icon, title, body]) => <article key={title}><span><Icon size={24} weight="duotone" /></span><div><h2>{title}</h2><p>{body}</p></div></article>)}</div>
    <aside className="user-guide-safety"><strong>自动化安全边界</strong><p>MediaIndex 不猜测媒体身份或目标路径。目录越界、TMDB 歧义、文件不稳定或 Provider 核验失败都会停止自动写入并保留可见状态。</p></aside>
  </section>;
}
