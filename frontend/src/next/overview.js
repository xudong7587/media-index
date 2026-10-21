const MERGE_CURVES = '<path d="M2 12.67C29 12.67 32 38 58 38M2 38H58M2 63.33C29 63.33 32 38 58 38M58 38H96" vector-effect="non-scaling-stroke"/>';
const MOBILE_MERGE = `<svg class="chain-merge-mobile" viewBox="0 0 76 100" preserveAspectRatio="none"><g transform="translate(76 0) rotate(90)"><g class="chain-merge-aura">${MERGE_CURVES}</g><g class="chain-merge-line">${MERGE_CURVES}</g></g></svg>`;

export const OVERVIEW_HTML = `
          <section class="panel panel-pad chain-overview">
            <div class="chain-top">
              <div>
                <h2>全流程自动化概览</h2>
                <p>查看资源入口、转存、核验整理、STRM 生成和 Emby 入库，并检查每个环节的配置状态。</p>
              </div>
              <div class="chain-score">
                <strong>11<small>/12</small></strong>
                <div><b>必需配置完整度</b><span>还有 1 个环节待配置</span></div>
              </div>
            </div>
            <div class="chain-legend">
              <span class="dot ok"></span>已配置
              <span class="dot warn"></span>待配置
              <em>状态仅表示必需配置已保存，不代表外部服务的实时健康状态；可点击节点进入对应页面测试。</em>
            </div>
          </section>

          <section class="panel chain-block">
            <header class="chain-head">
              <span class="chain-num">01</span>
              <div><h3>直接入库媒体链</h3><p>知道媒体身份，核验并命名后直接写入正式媒体库</p></div>
              <span class="chain-tag">目标：正式媒体库</span>
            </header>
            <div class="chain-body">
              <div class="chain-entries">
                <div class="chain-label">从这里进入<small>3 种入口共用本链路</small></div>
                <article class="entry-card">
                  <div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-spark"/></svg></span><span class="pill ok"><i></i>已配置</span></div>
                  <small>TMDB + 资源来源</small>
                  <b>发现</b>
                  <p>从探索、搜索与排行内容发起资源获取。</p>
                  <em>TMDB 与资源来源已保存。</em>
                  <button class="link" type="button" data-route="discover">打开资源获取设置<svg class="ic"><use href="#i-arrow"/></svg></button>
                </article>
                <article class="entry-card">
                  <div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-bell"/></svg></span><span class="pill ok"><i></i>已配置</span></div>
                  <small>持续追踪</small>
                  <b>智能追更</b>
                  <p>按播出日期与设定时间检查新集并转存。</p>
                  <em>巡检、资源来源与转存网盘已配置</em>
                  <button class="link" type="button" data-route="subscriptions">打开智能追更<svg class="ic"><use href="#i-arrow"/></svg></button>
                </article>
                <article class="entry-card">
                  <div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-star"/></svg></span><span class="pill ok"><i></i>已配置</span></div>
                  <small>定时巡检</small>
                  <b>愿望单</b>
                  <p>暂无资源的媒体保持巡检，命中后进入转存。</p>
                  <em>巡检、资源来源与转存网盘已配置</em>
                  <button class="link" type="button" data-route="subscriptions">打开愿望单<svg class="ic"><use href="#i-arrow"/></svg></button>
                </article>
              </div>
                            <div class="chain-merge" aria-hidden="true">${MOBILE_MERGE}
                <svg class="chain-merge-svg" viewBox="0 0 100 76" preserveAspectRatio="none">
                  <g class="chain-merge-aura">
                    <path d="M 2 12.67 C 29 12.67, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 2 38 H 58" vector-effect="non-scaling-stroke" />
                    <path d="M 2 63.33 C 29 63.33, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 58 38 H 96" vector-effect="non-scaling-stroke" />
                  </g>
                  <g class="chain-merge-line">
                    <path d="M 2 12.67 C 29 12.67, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 2 38 H 58" vector-effect="non-scaling-stroke" />
                    <path d="M 2 63.33 C 29 63.33, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 58 38 H 96" vector-effect="non-scaling-stroke" />
                  </g>
                </svg>
                <span class="chain-merge-copy">入口在这里汇合，接着按顺序执行</span>
                <svg class="chain-merge-arrow" viewBox="0 0 24 24"><path d="M4 12h15M13 6l6 6-6 6" /></svg>
              </div>
              <div class="chain-steps-wrap">
                <div class="chain-label">顺序处理<small>箭头表示必须先完成前一步</small></div>
                <div class="chain-steps">
                  <article class="step-card">
                    <div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-search"/></svg></span><span class="step-n">01</span></div>
                    <span class="pill ok"><i></i>已配置</span>
                    <b>资源核验</b>
                    <p>核对标题、年份、类型与季集身份。</p>
                    <button class="link" type="button" data-route="system">打开全局设置<svg class="ic"><use href="#i-arrow"/></svg></button>
                  </article>
                  <article class="step-card">
                    <div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-doc"/></svg></span><span class="step-n">02</span></div>
                    <span class="pill ok"><i></i>已配置</span>
                    <b>生成标准命名</b>
                    <p>在写入前生成正式媒体库路径与文件名。</p>
                    <button class="link" type="button" data-route="workspace">打开转存和整理规则<svg class="ic"><use href="#i-arrow"/></svg></button>
                  </article>
                  <article class="step-card">
                    <div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-link"/></svg></span><span class="step-n">03</span></div>
                    <span class="pill ok"><i></i>已配置</span>
                    <b>原生转存</b>
                    <p>按标准名直接写入 115 或夸克正式媒体库。</p>
                    <button class="link" type="button" data-route="workspace">打开网盘连接<svg class="ic"><use href="#i-arrow"/></svg></button>
                  </article>
                  <article class="step-card">
                    <div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-folder"/></svg></span><span class="step-n">04</span></div>
                    <span class="pill warn"><i></i>待配置</span>
                    <b>物理落点</b>
                    <p>/媒体库/&lt;分类&gt;/&lt;片名&gt;</p>
                    <button class="link" type="button" data-route="workspace">打开路径设置<svg class="ic"><use href="#i-arrow"/></svg></button>
                  </article>
                  <article class="step-card">
                    <div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-play"/></svg></span><span class="step-n">05</span></div>
                    <span class="pill ok"><i></i>已配置</span>
                    <b>STRM 生成</b>
                    <p>按已授权的网盘范围生成或定点更新 STRM。</p>
                    <button class="link" type="button" data-route="strm">打开 115 STRM 设置<svg class="ic"><use href="#i-arrow"/></svg></button>
                  </article>
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-video"/></svg></span><span class="step-n">06</span></div><span class="pill ok"><i></i>已配置</span><b>Emby 入库</b><p>STRM 完成后调用 Emby 媒体库刷新。</p><button class="link" type="button" data-route="media-server">打开媒体服务器<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                </div>
              </div>
            </div>
            <p class="chain-note">这条链不经过云下载文件夹；转存成功时，资源已在正式媒体库。</p>
          </section>

          <section class="panel chain-block" data-flow="cloud">
            <header class="chain-head">
              <span class="chain-num alt">02</span>
              <div><h3>云下载暂存整理链</h3><p>链接先接收、外部投递直接发现；两者在云下载文件夹汇合后统一整理</p></div>
              <span class="chain-tag">第一落点：云下载文件夹</span>
            </header>
            <div class="chain-body">
              <div class="chain-entries">
                <div class="chain-label">从这里进入<small>3 种入口共用本链路</small></div>
                <article class="entry-card"><div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-link"/></svg></span><span class="pill ok"><i></i>已配置</span></div><small>显式链接</small><b>网页与互动链接</b><p>夸克、115 分享或磁力、电驴、HTTP 链接，先选择云下载子目录。</p><button class="link" type="button" data-route="workspace" data-ws-section="cloud-download">打开相关设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                <article class="entry-card"><div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-download"/></svg></span><span class="pill ok"><i></i>已配置</span></div><small>外部投递</small><b>授权目录中的原始文件</b><p>外部下载器直接写入云下载目录，由事件或轮询发现，不重复提交下载。</p><button class="link" type="button" data-route="workspace" data-ws-section="cloud-download">打开相关设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                <article class="entry-card"><div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-bell"/></svg></span><span class="pill ok"><i></i>已配置</span></div><small>Telegram 频道</small><b>频道资源自动转存</b><p>按频道规则筛选资源，先原样转存到云下载文件夹等待统一整理。</p><button class="link" type="button" data-route="workspace" data-ws-section="sources">打开相关设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
              </div>
                            <div class="chain-merge" aria-hidden="true">${MOBILE_MERGE}
                <svg class="chain-merge-svg" viewBox="0 0 100 76" preserveAspectRatio="none">
                  <g class="chain-merge-aura">
                    <path d="M 2 12.67 C 29 12.67, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 2 38 H 58" vector-effect="non-scaling-stroke" />
                    <path d="M 2 63.33 C 29 63.33, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 58 38 H 96" vector-effect="non-scaling-stroke" />
                  </g>
                  <g class="chain-merge-line">
                    <path d="M 2 12.67 C 29 12.67, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 2 38 H 58" vector-effect="non-scaling-stroke" />
                    <path d="M 2 63.33 C 29 63.33, 32 38, 58 38" vector-effect="non-scaling-stroke" />
                    <path d="M 58 38 H 96" vector-effect="non-scaling-stroke" />
                  </g>
                </svg>
                <span class="chain-merge-copy">入口在这里汇合，接着按顺序执行</span>
                <svg class="chain-merge-arrow" viewBox="0 0 24 24"><path d="M4 12h15M13 6l6 6-6 6" /></svg>
              </div>
              <div class="chain-steps-wrap">
                <div class="chain-label">顺序处理<small>箭头表示必须先完成前一步</small></div>
                <div class="chain-steps">
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-cloud"/></svg></span><span class="step-n">01</span></div><span class="pill ok"><i></i>已配置</span><b>接收 / 发现原始文件</b><p>链接原样转存；外部投递在授权目录中被发现。</p><button class="link" type="button" data-route="workspace" data-ws-section="cloud-download">打开设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-download"/></svg></span><span class="step-n">02</span></div><span class="pill ok"><i></i>已配置</span><b>云下载文件夹</b><p>/云下载/&lt;分类&gt;；此时尚未入库。</p><button class="link" type="button" data-route="workspace" data-ws-section="cloud-download">打开设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-discover"/></svg></span><span class="step-n">03</span></div><span class="pill ok"><i></i>已配置</span><b>TMDB 匹配</b><p>事件或定时任务触发后，核对标题、年份、类型与季集身份。</p><button class="link" type="button" data-route="system">打开设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-doc"/></svg></span><span class="step-n">04</span></div><span class="pill ok"><i></i>已配置</span><b>改名与整理</b><p>规范目录与文件名，复制或移动到正式媒体库。</p><button class="link" type="button" data-route="workspace" data-ws-section="rules">打开设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-folder"/></svg></span><span class="step-n">05</span></div><span class="pill ok"><i></i>已配置</span><b>正式媒体库</b><p>/媒体库/&lt;分类&gt;/&lt;片名&gt;</p><button class="link" type="button" data-route="workspace" data-ws-section="rules">打开设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-play"/></svg></span><span class="step-n">06</span></div><span class="pill ok"><i></i>已配置</span><b>STRM 生成</b><p>按授权网盘范围生成或定点更新 STRM。</p><button class="link" type="button" data-route="strm">打开设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                  <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-video"/></svg></span><span class="step-n">07</span></div><span class="pill ok"><i></i>已配置</span><b>Emby 入库</b><p>STRM 完成后调用 Emby 媒体库刷新。</p><button class="link" type="button" data-route="media-server">打开设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
                </div>
              </div>
            </div>
            <p class="chain-note">关闭匹配改名与整理时，流程停在云下载文件夹；开启后才继续到正式媒体库、STRM 和 Emby。</p>
          </section>
        `;

export const WEBHOOK_CHAIN_HTML = `
<section class="panel chain-block" data-flow="webhook">
  <header class="chain-head"><div class="chain-num alt">03</div><div><h3>Webhook 增量旁路</h3><p>外部已完成整理的媒体文件，直接触发增量入库</p></div><span class="chain-tag">外部完成通知</span></header>
  <div class="chain-body"><div class="chain-entries"><article class="entry-card"><div class="entry-top"><span class="entry-ic"><svg class="ic"><use href="#i-cloud"/></svg></span><span class="pill ok">可配置</span></div><small>Webhook</small><b>外部工具完成整理</b><p>接收 MDC 等外部工具的完成通知，媒体已在正式目录中。</p><button class="link" data-route="workspace" data-ws-section="webhook">打开 Webhook<svg class="ic"><use href="#i-arrow"/></svg></button></article></div>
  <div class="chain-merge" aria-hidden="true">${MOBILE_MERGE}<svg class="chain-merge-arrow" viewBox="0 0 24 24"><path d="M4 12h15M13 6l6 6-6 6"/></svg></div>
  <div class="chain-steps-wrap"><div class="chain-label">增量处理<small>不经过 MediaIndex 匹配改名</small></div><div class="chain-steps">
    <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-folder"/></svg></span><span class="step-n">01</span></div><b>授权范围核对</b><p>按来源网盘核对外部通知中的媒体目录。</p></article>
    <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-play"/></svg></span><span class="step-n">02</span></div><b>STRM 增量生成</b><p>优先对指定目录生成或更新 STRM。</p><button class="link" data-route="strm">打开 STRM 设置<svg class="ic"><use href="#i-arrow"/></svg></button></article>
    <article class="step-card"><div class="step-top"><span class="step-ic"><svg class="ic"><use href="#i-video"/></svg></span><span class="step-n">03</span></div><b>Emby 入库</b><p>STRM 完成后通知 Emby 刷新媒体库。</p><button class="link" data-route="media-server">打开媒体服务器<svg class="ic"><use href="#i-arrow"/></svg></button></article>
  </div></div></div><p class="chain-note">媒体已由外部工具整理，不进入 MediaIndex 云下载暂存与改名流程。</p>
</section>`;
