import {
  Binoculars, Broadcast, CloudArrowDown, GearSix, HardDrives, Heart,
  ListChecks, Play, ShieldCheck, SlidersHorizontal, TelevisionSimple, Wrench,
} from "@phosphor-icons/react";

import "./user-guide.css";

const chapters = [
  ["start", GearSix, "首次配置", "部署、登录与基础服务"],
  ["sources", Binoculars, "资源从哪里进入", "发现、PanSou、TG 与链接"],
  ["storage", HardDrives, "网盘与目录", "正式媒体库和云下载边界"],
  ["flows", CloudArrowDown, "两条入库流程", "直接入库与暂存整理"],
  ["automation", Heart, "持续自动化", "追更、愿望单和频道"],
  ["playback", Play, "STRM 与 Emby", "生成、播放和媒体库刷新"],
  ["operations", Wrench, "日常维护", "日志、排障、备份与升级"],
] as const;

function Checklist({ items }: { items: string[] }) {
  return <ol className="guide-checklist">{items.map((item) => <li key={item}><span><ListChecks weight="duotone" /></span><p>{item}</p></li>)}</ol>;
}

export function UserGuide() {
  return <section className="user-guide-page">
    <header className="page-head user-guide-head"><div><p className="eyebrow">MEDIAINDEX HANDBOOK</p><h1>使用手册</h1><p>按真实媒体流程说明每个入口、目录边界、自动整理和后续入库；第一次使用从上往下完成即可。</p></div><span className="guide-head-mark"><ShieldCheck weight="duotone" /><small>安全默认</small><strong>证据不足时停止</strong></span></header>

    <nav className="guide-chapter-nav" aria-label="使用手册章节">{chapters.map(([id, Icon, title]) => <a href={`#guide-${id}`} key={id}><Icon weight="duotone" /><span>{title}</span></a>)}</nav>

    <div className="guide-overview-strip" aria-label="MediaIndex 基本处理顺序"><span>发现或接收资源</span><i>→</i><span>核验身份与目标</span><i>→</i><span>网盘转存 / 云下载暂存</span><i>→</i><span>分类改名到正式库</span><i>→</i><span>STRM · Emby · 通知</span></div>

    <div className="guide-chapters">
      <article id="guide-start" className="guide-chapter">
        <header><span><GearSix weight="duotone" /></span><div><small>01 · START</small><h2>首次配置：先把基础能力连通</h2><p>每保存一组设置就使用同页测试按钮，不要一次填完后才判断哪里失败。</p></div></header>
        <Checklist items={["使用 Docker Compose 部署，固定保留 /app/data、/app/strm 等持久化挂载；首次登录后立即修改管理密码。", "在“全局设置”填写 TMDB API Key 和时区；需要代理时先测试代理，再测试 TMDB。", "至少连接一个原生网盘：115 使用 Cookie/扫码，夸克使用 Cookie/扫码；连接测试必须能读取根目录。", "可选配置 PanSou、OpenList、Telegram、企业微信与 Emby；不用的外部服务保持关闭。"]} />
      </article>

      <article id="guide-sources" className="guide-chapter">
        <header><span><Binoculars weight="duotone" /></span><div><small>02 · SOURCES</small><h2>资源入口：先决定资源怎样被发现</h2><p>入口只提供候选或原始链接，最终路径、媒体身份和写入权限仍由后端确认。</p></div></header>
        <div className="guide-feature-grid">
          <section><Binoculars /><strong>发现与 PanSou</strong><p>发现页以 TMDB 建立标准身份，再由 PanSou 返回候选。资源获取页的反向关键词只过滤 PanSou，与 TG 规则独立。</p></section>
          <section><Broadcast /><strong>TG 频道追踪</strong><p>公开频道定时读取，私有频道由 Bot 接收。反向关键词优先拒绝；正向词为空代表全部允许。匹配的每条支持链接分别去重和转存。</p></section>
          <section><CloudArrowDown /><strong>链接与互动渠道</strong><p>网页、浏览器插件、企业微信或 Telegram 可提交 115、夸克分享，以及交给 115 的磁力/电驴链接；默认先进入云下载暂存。</p></section>
          <section><TelevisionSimple /><strong>外部下载与 Webhook</strong><p>MDC-NG 等外部工具已完成整理时，可通知 MediaIndex 对已授权路径做只增不删的 STRM 增量处理。</p></section>
        </div>
      </article>

      <article id="guide-storage" className="guide-chapter">
        <header><span><HardDrives weight="duotone" /></span><div><small>03 · STORAGE</small><h2>网盘目录：分清暂存区与正式媒体库</h2><p>这是整个自动化最重要的边界。两个根目录不能重叠，也不要把正式库放到云下载根内部。</p></div></header>
        <div className="guide-path-compare"><section className="cloud"><small>临时落点</small><strong>/云下载/&lt;分类&gt;</strong><p>接收名称不统一的 TG、互动链接、磁力和外部下载。这里的原始文件不直接生成正式 STRM。</p></section><span>整理器核验后 →</span><section className="library"><small>正式落点</small><strong>/媒体库/&lt;分类&gt;/&lt;标准片名&gt;</strong><p>只有 TMDB 唯一匹配、命名计划和目标核验通过后才写入，并继续 STRM 与 Emby。</p></section></div>
        <Checklist items={["为 115 和夸克分别设置正式媒体库根与云下载根；两个网盘的目录和开关互不替代。", "云下载整理的授权范围只允许根目录的直属分类子目录；选择“全部”仍会排除与正式库重叠的危险路径。", "复制模式保留原文件；移动模式只在全部目标逐文件核验后按精确文件 ID 清理来源，不删除整个目录。", "TG 自动分类只在消息类别和对应子目录都唯一时执行；不确定时留在可见失败状态，不猜路径。"]} />
      </article>

      <article id="guide-flows" className="guide-chapter">
        <header><span><CloudArrowDown weight="duotone" /></span><div><small>04 · FLOWS</small><h2>两条入库流程：根据身份确定程度选择</h2><p>“全流程自动化概览”显示相同链路的实时配置状态，这里解释什么时候走哪一条。</p></div></header>
        <div className="guide-flow-lanes"><section><span>流程 A</span><h3>已知媒体身份 → 直接入正式库</h3><p>发现卡片、愿望单或追更已持有 TMDB 身份时，先验真、逐文件匹配和生成标准命名，再直接转存到正式媒体库。</p><code>TMDB → 候选验真 → 标准命名 → 正式库 → STRM → Emby</code></section><section><span>流程 B</span><h3>名称不统一 → 云下载暂存整理</h3><p>TG、互动链接、磁力和外部投递先原样进入分类暂存；整理器等待稳定、唯一识别、改名后再进入正式库。</p><code>资源链接 → 云下载 → TMDB 整理 → 正式库 → STRM → Emby</code></section></div>
      </article>

      <article id="guide-automation" className="guide-chapter">
        <header><span><Heart weight="duotone" /></span><div><small>05 · AUTOMATION</small><h2>持续自动化：追更、愿望单与频道各司其职</h2><p>三者规则独立，避免一个入口的过滤词或状态意外影响另一个入口。</p></div></header>
        <div className="guide-feature-grid three"><section><TelevisionSimple /><strong>智能追更</strong><p>已有媒体按播出日期和已保存集数巡检，只处理到期且缺失的新集；不自动回补历史缺集。</p></section><section><Heart /><strong>愿望单</strong><p>暂时无资源的媒体按设定间隔重新检索，命中高置信度候选后才进入转存。</p></section><section><Broadcast /><strong>TG 频道</strong><p>频道规则面向消息和链接；正/反关键词、分类方式和指定目录只属于该频道，不与 PanSou 或其他频道共享。</p></section></div>
      </article>

      <article id="guide-playback" className="guide-chapter">
        <header><span><Play weight="duotone" /></span><div><small>06 · PLAYBACK</small><h2>STRM 与 Emby：只对正式且已核验的资产工作</h2><p>STRM 是播放映射，不是转存成功的替代证据；必须先确认网盘目标真实存在。</p></div></header>
        <Checklist items={["分别为 115/夸克选择 STRM 来源根和直属分类范围，并配置本地 STRM 输出目录。", "增量任务只新增或更新映射，不做删除；全量清理需要完整扫描、连续两次缺失确认并受熔断保护。", "启用 Emby 自动刷新后，STRM 实际新增或替换才请求对应媒体库扫描；图文入库通知仍等待 Emby Webhook 回执。", "外网 302 播放使用 MediaIndex 反代端口；播放 URL 是长期凭证，不应公开或写入日志。"]} />
      </article>

      <article id="guide-operations" className="guide-chapter">
        <header><span><SlidersHorizontal weight="duotone" /></span><div><small>07 · OPERATIONS</small><h2>日常维护：看状态、处理异常、再升级</h2><p>运行日志用于观察，不应成为任务的唯一状态源；待确认和具体模块页面保留各自操作入口。</p></div></header>
        <div className="guide-operations-grid"><section><strong>日志与任务</strong><p>“清除历史”隐藏所有非活动记录，不停止任务；“停止运行”只终止可停止的活动任务，不删除历史。遇到问题先导出后台诊断包。</p></section><section><strong>常见卡点</strong><p>先检查任务当前步骤、网盘连接、目录范围、关键词、TMDB 唯一性和文件稳定时间。MDC-NG 路径明确时会按目录关联互动等待任务，多候选时仍不猜测。</p></section><section><strong>备份与升级</strong><p>升级前备份运行配置、数据库与 STRM 目录；拉取新镜像后保留原挂载启动，再检查 Release 说明和全流程概览。</p></section><section><strong>信息安全</strong><p>Cookie、Token、API Key 只存服务端；页面不回显完整密钥，频道记录不展示分享链接。不要把配置导出或诊断包公开上传。</p></section></div>
      </article>
    </div>
  </section>;
}
