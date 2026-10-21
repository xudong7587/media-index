import { listen } from "../components/native-ui.js";

export function bindNativeGuide(root = document) {
  const articles = [...root.querySelectorAll("article.chapter[data-chapter]")];
  const controls = [...root.querySelectorAll("#guideToc button[data-chapter], [data-guide-chapter]")];
  function selectChapter(chapter, scroll = true) {
    const article = articles.find((node) => node.dataset.chapter === chapter);
    if (!article) return;
    articles.forEach((node) => { node.classList.toggle("active", node === article); node.hidden = node !== article; });
    controls.forEach((node) => { const active = (node.dataset.chapter || node.dataset.guideChapter) === chapter; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); });
    if (scroll) { const heading = article.querySelector("h2"); heading?.setAttribute("tabindex", "-1"); heading?.focus({ preventScroll: true }); article.scrollIntoView?.({ block: "start", behavior: "instant" }); }
  }
  controls.forEach((node) => listen(node, "click", () => selectChapter(node.dataset.chapter || node.dataset.guideChapter)));
  selectChapter("1", false);
}

export const GUIDE_HTML = `
        <div class="page-head">
          <div>
            <p class="eyebrow">GUIDE · 帮助中心</p>
            <h1>使用手册</h1>
            <p class="sub">按“你现在要完成什么”来查，而不是按功能列表翻。</p>
          </div>
        </div>

        <div class="card-grid">
          <button class="panel conn-card" data-guide-chapter="1" style="text-align:left;cursor:pointer">
            <div class="conn-top"><span class="conn-logo" style="--brand:var(--accent)">1</span><div><b>第一次配置</b><small>从登录到跑通第一条链路</small></div></div>
            <div class="row-actions" style="justify-content:flex-end"><svg class="ic" style="width:16px;height:16px;color:var(--muted)"><use href="#i-arrow"/></svg></div>
          </button>
          <button class="panel conn-card" data-guide-chapter="2" style="text-align:left;cursor:pointer">
            <div class="conn-top"><span class="conn-logo" style="--brand:var(--accent-2)">2</span><div><b>找到资源</b><small>发现、PanSou、TG 与外部推送</small></div></div>
            <div class="row-actions" style="justify-content:flex-end"><svg class="ic" style="width:16px;height:16px;color:var(--muted)"><use href="#i-arrow"/></svg></div>
          </button>
          <button class="panel conn-card" data-guide-chapter="3" style="text-align:left;cursor:pointer">
            <div class="conn-top"><span class="conn-logo" style="--brand:var(--accent-3)">3</span><div><b>整理入库</b><small>暂存、等待稳定、进正式库</small></div></div>
            <div class="row-actions" style="justify-content:flex-end"><svg class="ic" style="width:16px;height:16px;color:var(--muted)"><use href="#i-arrow"/></svg></div>
          </button>
          <button class="panel conn-card" data-guide-chapter="8" style="text-align:left;cursor:pointer">
            <div class="conn-top"><span class="conn-logo" style="--brand:var(--muted)">4</span><div><b>排障与备份</b><small>任务状态、日志、升级回滚</small></div></div>
            <div class="row-actions" style="justify-content:flex-end"><svg class="ic" style="width:16px;height:16px;color:var(--muted)"><use href="#i-arrow"/></svg></div>
          </button>
        </div>

        <div class="split guide-split">
          <aside class="panel panel-pad" style="position:sticky;top:84px">
            <div class="panel-head"><div><h2>目录</h2><small>01 — 09</small></div></div>
            <div class="toc" id="guideToc">
              <button class="active" data-chapter="1">01 第一次配置</button>
              <button data-chapter="2">02 资源从哪里进入</button>
              <button data-chapter="3">03 云下载与正式媒体库</button>
              <button data-chapter="4">04 身份明确时直接入库</button>
              <button data-chapter="5">05 追更、愿望单与频道</button>
              <button data-chapter="6">06 STRM、302 与 Emby</button>
              <button data-chapter="7">07 媒体服务器与外部联动</button>
              <button data-chapter="8">08 任务、日志与排障</button>
              <button data-chapter="9">09 备份、升级与安全</button>
            </div>
          </aside>

          <section class="panel panel-pad">
            <article class="doc chapter active" data-chapter="1">
            <div class="panel-head"><div><h2>01 第一次配置</h2><small>目标：小范围跑通一次完整链路</small></div><span class="pill ok"><i></i>约 10 分钟</span></div>
            <ol>
              <li>登录后先改默认密码，密码不要复用其它站点。</li>
              <li>在「全局设置 → 影视资料服务」填入 TMDB API Key，点测试连接。</li>
              <li>在「网盘工作台 → 网盘链接」接入 115 或夸克，至少保留一个执行网盘。</li>
              <li>划定正式媒体库根目录，以及云下载的暂存目录。</li>
              <li>回到「发现」挑一部作品，走一次转存，到任务中心看它跑完。</li>
            </ol>
            <div class="callout"><svg class="ic"><use href="#i-warn"/></svg><span>先小范围验收：拿一部电影跑通，再批量导入。目录写错会让后面的整理全部落空。</span></div>

            <h3>两条链路先分清</h3>
            <div class="flow" style="margin:6px 0 14px">
              <div class="flow-node"><small>直接入库</small><b>发现 → 任务</b><span>身份明确、候选可信</span></div>
              <div class="flow-arrow"><svg class="ic"><use href="#i-arrow"/></svg></div>
              <div class="flow-node"><small></small><b>正式媒体库</b><span>跳过暂存</span></div>
              <div class="flow-arrow"><svg class="ic"><use href="#i-arrow"/></svg></div>
              <div class="flow-node"><small></small><b>STRM / Emby</b><span>立即可播</span></div>
            </div>
            <div class="flow" style="margin:0 0 6px">
              <div class="flow-node"><small>云下载链</small><b>链接 → 云下载</b><span>文件名不规范</span></div>
              <div class="flow-arrow"><svg class="ic"><use href="#i-arrow"/></svg></div>
              <div class="flow-node"><small></small><b>暂存目录</b><span>等待稳定</span></div>
              <div class="flow-arrow"><svg class="ic"><use href="#i-arrow"/></svg></div>
              <div class="flow-node"><small></small><b>整理进正式库</b><span>再生成 STRM</span></div>
            </div>

            <h3>下一步</h3>
            <p>配置完成后，建议直接看「02 资源从哪里进入」，确认你常用的入口是否已经接上。</p>
            </article>

            <article class="doc chapter" data-chapter="2">
              <div class="panel-head"><div><h2>02 资源从哪里进入</h2><small>四条入口，各自落点不同</small></div><span class="pill info"><i></i>入口</span></div>
              <ul>
                <li><b>发现 / PanSou 搜索</b>：先确认 TMDB 身份，再检索资源，产出任务。</li>
                <li><b>TG 频道追踪</b>：按关键词与目录过滤，批量进任务或只建索引。</li>
                <li><b>网页与交互链接</b>：直接进入云下载，适合文件名不规范的内容。</li>
                <li><b>MDC-NG Webhook</b>：外部系统推过来的消息，走旁路。</li>
              </ul>
              <div class="callout"><svg class="ic"><use href="#i-warn"/></svg><span>频道模式选「仅建索引」时不会自动转存，只记录，需要手动处理。</span></div>
              <h3>建议顺序</h3>
              <ol>
                <li>先接 PanSou 作兜底检索，确认能搜到东西。</li>
                <li>再接 1–2 个高质量频道，观察一两天的识别结果。</li>
                <li>最后再开自动转存，避免一上来就写进正式库。</li>
              </ol>
            </article>

            <article class="doc chapter" data-chapter="3">
              <div class="panel-head"><div><h2>03 云下载与正式媒体库</h2><small>给不规范的文件一条整理路径</small></div><span class="pill warn"><i></i>需要耐心</span></div>
              <p>云下载是暂存区：文件先落在下载目录，等稳定后再整理进正式库，最后才生成 STRM。</p>
              <ol>
                <li>在「网盘工作台 → 云下载」设定下载根目录与正式库根目录。</li>
                <li>设置触发时机（下载完成 / 定时扫描）与稳定等待时间。</li>
                <li>选择复制或移动：移动省空间但不可回滚，复制更安全。</li>
                <li>整理失败的文件会留在暂存区，在任务中心能看到卡住的阶段。</li>
              </ol>
              <div class="callout"><svg class="ic"><use href="#i-warn"/></svg><span>稳定等待别设太小。下载器刚写完文件名时，文件大小还在变。</span></div>
            </article>

            <article class="doc chapter" data-chapter="4">
              <div class="panel-head"><div><h2>04 身份明确时直接入库</h2><small>跳过暂存，直接写正式库</small></div><span class="pill ok"><i></i>快</span></div>
              <p>当发现页已经确认了 TMDB 身份、候选资源也干净时，可以直接写正式库，不用走云下载。</p>
              <ol>
                <li>在作品详情里核对标题、年份与季集。</li>
                <li>看候选的来源与匹配分，确认文件清单。</li>
                <li>确认后直接入库，任务中心会显示 6 步流水线。</li>
              </ol>
              <div class="callout"><svg class="ic"><use href="#i-warn"/></svg><span>候选与原任务网盘不一致、或匹配分偏低时，用「待确认」而不是硬转。</span></div>
            </article>

            <article class="doc chapter" data-chapter="5">
              <div class="panel-head"><div><h2>05 追更、愿望单与频道</h2><small>三种自动化，互不影响</small></div><span class="pill info"><i></i>自动化</span></div>
              <ul>
                <li><b>智能追更</b>：季集明确，按发布时间 + 巡检周期补缺集。</li>
                <li><b>愿望单</b>：还没有资源，等上线后再检查。</li>
                <li><b>频道</b>：批量来源，按关键词与目录规则过滤。</li>
              </ul>
              <p>三者各有独立开关；追更页里的「保存路径」按网盘分别设置，别只改一个。</p>
              <h3>失败重试</h3>
              <p>重试间隔与最大次数在追更页右侧设置，对所有追更任务生效；单条任务的「执行」不受周期限制。</p>
            </article>

            <article class="doc chapter" data-chapter="6">
              <div class="panel-head"><div><h2>06 STRM、302 与 Emby</h2><small>让网盘里的东西在 Emby 里可播</small></div><span class="pill info"><i></i>播放</span></div>
              <ol>
                <li>先配 302 播放地址：填外部可访问的地址，端口映射要对得上。</li>
                <li>再配 Emby 内网地址与 API Key，点测试连接。</li>
                <li>来源目录只勾授权范围，自动读取子目录后再选。</li>
                <li>首次用全量扫描，之后按 Cron 增量；大改目录后再全量一次。</li>
                <li>删除同步需要生成 Webhook，填进 Emby 的通知设置。</li>
              </ol>
              <div class="callout"><svg class="ic"><use href="#i-warn"/></svg><span>写入 STRM 的是外部地址。内网能播、出门不能播，通常就是这里写成了内网 IP。</span></div>
            </article>

            <article class="doc chapter" data-chapter="7">
              <div class="panel-head"><div><h2>07 媒体服务器与外部联动</h2><small>看板、封面、跨盘与通知</small></div><span class="pill info"><i></i>联动</span></div>
              <ul>
                <li><b>Emby 看板</b>：当前会话、四个库的数量与容量、最近入库。</li>
                <li><b>封面工坊</b>：按库批量替换封面，支持定时任务。</li>
                <li><b>OpenList / CD2</b>：跨盘补齐的搬运通道。</li>
                <li><b>通知与交互</b>：企业微信、机器人、Telegram，以及群聊指令。</li>
              </ul>
              <p>外部联动都不是必须的：先跑通主链路，再逐个接。</p>
            </article>

            <article class="doc chapter" data-chapter="8">
              <div class="panel-head"><div><h2>08 任务、日志与排障</h2><small>先看卡在哪一步</small></div><span class="pill warn"><i></i>排障</span></div>
              <ol>
                <li>打开任务详情，看 6 步流水线停在哪一步。</li>
                <li>媒体核对失败：多半是 TMDB 连不上或名字太离谱。</li>
                <li>提交网盘失败：查目录是否可写、网盘是否限流。</li>
                <li>待决定：候选不匹配，需要人确认或换关键词。</li>
              </ol>
              <div class="callout"><svg class="ic"><use href="#i-warn"/></svg><span>排障用的只读诊断令牌在「全局设置 → 开发者选项」，默认关闭，有效期 5–120 分钟。</span></div>
            </article>

            <article class="doc chapter" data-chapter="9">
              <div class="panel-head"><div><h2>09 备份、升级与安全</h2><small>先能回滚，再谈升级</small></div><span class="pill err"><i></i>别省这一步</span></div>
              <ol>
                <li>升级前导出配置，并备份数据库与 \`.env\`。</li>
                <li>拉取新镜像后重启，跑一次冒烟：登录、发现、转存、播放。</li>
                <li>配置导出包含凭据，别放进公开仓库。</li>
                <li>回调 URL 与 API Key 当作口令对待，泄露就重置。</li>
              </ol>
              <h3>版本回退</h3>
              <p>镜像与数据库迁移要一起回退；只回镜像会在启动时报迁移版本不匹配。</p>
            </article>
          </section>
        </div>
      `;
