# MediaIndex 新前端交接文档（给 Codex）

> 2026-10-20 对接更新：本次补齐内容、兼容性与验证边界见 [FRONTEND-INTEGRATION.md](FRONTEND-INTEGRATION.md)。下文“未完成”和环境状态保留为原始交接记录。

> 分支：`codex/pages-089`（worktree：`D:\Documents\MediaIndex前端\.worktrees\appearance-088`）
> 版本：1.0.0（0.8.9 开发稿完成验收后正式发布）
> 交接范围：`frontend/src/next/*` 这一套无框架前端；React 旧入口保留但不再打包。
> 本文只记录实际存在、实际验证过的内容；未接后端的部分在“外观桩 / 未完成”一节单独标注。

---

## 1. 现在是什么状态

- 旧 React 前端（`frontend/src/main.tsx` 及 `src/app`、`src/pages` 等）仍留在仓库里，但 `frontend/index.html` 的入口已改成 `/src/next/main.js`，Vite 只打包新前端。
- 新前端是**纯原生 JS + 模板字符串 DOM**，没有 React、没有路由库、没有组件库；样式直接复用预览站 `index.html` 的 CSS（原样 109 KB）。
- 8 个一级页面、工作台 6 个分区、STRM 3 个分区、设置 5 个分区、订阅 4 个分支、发现页探索/链接下载分支、详情弹层、任务详情、目录选择、二维码登录、封面工坊等都在 `main.js` 里。
- 外观已经按用户逐条验收过 15 项；**功能行为有部分只是“外观桩”**，见第 10 节，这是 Codex 接手后最主要的活。

---

## 2. 运行方式

### 2.1 生产式本地版（推荐验收用）

后端直接托管 `frontend/dist`：

```
构建：pnpm --dir frontend build          # tsc -b && vite build
访问：http://127.0.0.1:8000/
账号：local / local-only-pass
```

后端启动参数（本机实测可用，PowerShell 环境变量）：

```
APP_ENV=local-test
AUTH_SECRET=local-sandbox-only-secret-please-change
MEDIA_USER=local
MEDIA_PASS=local-only-pass
DB_PATH=<worktree>\.tmp\local\media_index.db
CACHE_DIR=<worktree>\.tmp\local\cache
STATIC_DIR=<worktree>\frontend\dist
PYTHONPATH=<worktree>\backend
MEDIA_CONFIG_PATH=<worktree>\.tmp\local\media.env
PUBLIC_BASE_URL=http://127.0.0.1:5173
COOKIE_SECURE=false
TRACKING_SCHEDULER_ENABLED=false
WISHLIST_SCHEDULER_ENABLED=false

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000   # cwd=<worktree>\backend
```

注意：

- 后端**没有** `--reload`，改后端代码必须手动重启。
- 真实配置（含 TMDB Key、夸克/115 Cookie、Telegram Token、Emby Key、OpenList Token）在 `\.tmp\local\media.env`，**已被 git 忽略，不要提交、不要打印**。
- `PUBLIC_BASE_URL` 必须是 http，否则登录 Cookie 带 `Secure`，本地 `http://127.0.0.1` 会丢登录态。

### 2.2 Vite 开发服务器

```
pnpm --dir frontend dev --port 5173 --strictPort
```

- `/api` 代理到 `127.0.0.1:8000`。
- 本机实测这个 dev server 偶尔会自己挂掉；改完代码优先 `build` + 用 8000 验收。
- 5173 被占用时先杀掉端口进程再起。

### 2.3 测试

```
PYTHONPATH=<worktree>\backend python -m unittest tests.test_cloud_download_organizer_manual tests.test_frontend_resource_acquisition_contract
```

9 项通过（3 项手动整理 + 6 项前端契约）。

---

## 3. 文件结构

```
frontend/
  index.html                 入口，内联预览站的 35 个 <symbol> 图标 sprite
  src/next/
    main.js                  ≈2900 行，全部页面/状态/绑定/弹层
    preview.css              预览站 CSS 原样拷贝（不要改，改样式只加 next.css）
    next.css                 ≈280 行增量样式（列表内边距、榜单行、媒体卡、gap 等）
    theme-data.js            THEME_DATA：16 材质 + 10 单色 + 16 多色主题
    overview.js              OVERVIEW_HTML：链路概览静态结构
    guide.js                 GUIDE_HTML：使用手册静态页
    （临时文件 _*.js 已清理，不要重新引入）
  src/main.tsx 等           旧 React，未打包，暂时保留
```

---

## 4. 架构约定

### 4.1 入口与路由

- `frontend/index.html` → `<script type="module" src="/src/next/main.js">`
- Hash 路由：`#discover`、`#subscriptions`、`#workspace`、`#cross-cloud`、`#strm`、`#media-server`、`#system`、`#guide`
- `boot()` 先拉 `/api/auth/me`：失败渲染登录页；成功拉 `/api/config/status`、`/api/transfers`、`/api/notifications`，然后 `render()`。
- 路由切换走 `render()` → `shell()` 重绘侧栏 + 主区；每个页面是 `xxxView()` 返回 HTML 字符串，再由 `bindXxx()` 绑事件。

### 4.2 页面函数清单

| 路由 | 主函数 | 绑定函数 | 数据来源 |
|---|---|---|---|
| discover | `discoverView` → `loadDiscover` → `renderExplore` / `renderDownload` / `loadRankingsInline` | `bindDiscover`、`bindDiscoverFilters`、`bindRankInline`、`bindDiscoverDownload` | `/api/discover`、`/api/ranking`、`/api/media/{type}/{id}`、`/api/tracking`、`/api/wishlist`、`/api/transfers` |
| subscriptions | `subsView` → `loadSubs` → `renderSubsBody` | `bindSubs` | `/api/tracking`、`/api/wishlist`、`/api/review` |
| workspace | `wsPageView` → `loadWs` | `bindWs` | `/api/config/status`、`/api/transfers`、`/api/cloud/channels`、`/api/webhooks/*` |
| cross-cloud | `crossPageView` → `loadCross` → `crossConfigView` / `crossManualView` / `crossTasksView` | `bindCross` | `/api/cross-copy/config`、`/api/openlist/*` |
| strm | `strmPageView` → `loadStrm` → `strmCommonView` / `strmProviderView` | `bindStrm` | `/api/config/status`、`/api/cloud/strm/jobs`、`/api/strm/directory-rescan` |
| media-server | `mediaPageView` → `loadMedia` → `mediaBodyView` | `bindMedia` | `/api/integrations/emby/*` |
| system | `settingsPageView` → `loadSettings` → `renderSettingsBody` | `bindSettings` + `bindSettingsControls` | `/api/config/status`、`/api/config`、`/api/config/export|import`、`/api/notifications/test/*` |
| guide | `guidePageView` | `bindGuide` | 静态 `GUIDE_HTML` |

### 4.3 状态对象

`state`（全局）、`discoverState`、`subsState`、`wsState`、`crossState`、`strmState`、`settingsState`、`mediaState`。
页面渲染前先赋 `xxxState.config = config`，避免异步返回时读到旧值。

### 4.4 绑定约定（重要）

**每个 `render/load` 之后必须显式调用对应 `bindXxx()`。** 本会话踩过两次大坑：

1. `renderDiscoverFilters()` 被删掉后，筛选/刷新/链接下载的监听不再绑定，按钮全部像静态页面；
2. `loadSettings()` 只调 `renderSettingsBody()`，从不调 `bindSettings()`，设置页 5 个 tab 完全点不动。

现在的做法：

- 发现页：`renderExplore` 末尾 `bindDiscoverFilters()`；
- 设置页：`loadSettings` 末尾 `bindSettings()`，且 `renderSettingsBody` 末尾 `bindSettingsControls()`（只绑 `#settingsBody` 内部，避免 tab 重复绑定）；
- 其他页面：`load*` 内渲染后立即 `bind*()`。

新增页面/分区时按这个模式走，不要依赖事件委托。

### 4.5 样式约定

- `preview.css` 是预览站原样，**不要改**。
- 所有覆盖/补充写进 `next.css`，并尽量用预览已有类名。
- 主题属性：`html[data-theme]`、`data-material`、`data-color`、`data-corner`。
  强调色必须写 `root.dataset.color = state.accent`（只写 `data-accent` 不会生效）。
- 预览组件类名优先复用：`.panel/.panel-pad/.panel-head/.list/.list-row`、`.subnav`、`.switch-row/.switch`、`.form-grid/.field`、`.card-grid/.conn-card`、`.task-card/.ep-row/.ep`、`.hero*`、`.side-stack/.track-card/.stat-card`、`.copy-grid/.copy-*`、`.chain-*`、`.detail*`、`.poster-grid`。

---

## 5. 已接通的真实接口

静态字符串路径（`api("...")`）：

```
/api/auth/login /api/auth/me
/api/discover /api/ranking /api/media/{type}/{id} /api/media/search
/api/tracking (+ /api/tracking/{id}/pause|resume|delete|episodes|fill|sync-selected|fill-from-share)
/api/wishlist /api/review
/api/config /api/config/status /api/config/export /api/config/import
/api/config/test-quark /api/config/test-p115 /api/config/test-tmdb /api/config/test-pansou
/api/config/quark/qr/start /api/config/quark/qr/poll
/api/cloud/p115/cookie/qrcode
/api/cloud/channels (+ import-pansou / pansou / sync / {id})
/api/cloud/strm/jobs /api/strm/directory-rescan
/api/transfers (+ /api/transfers/{id}、/pause、/resume、/execute、/requeue、/delete、/refresh-saved、/direct-link、/direct-link/options)
/api/transfers/cloud-download-organizer/organize
/api/cross-copy/config
/api/openlist/test|browse|entries|sync-selected|sync-library|tasks(+/{id})
/api/integrations/emby/test|dashboard|cover-refresh|images/{item_id}|libraries/covers/refresh
/api/webhooks/connections (+ /{id}/test、/deliveries/recent)
/api/notifications /api/notifications/read /api/notifications/test/{kind}
```

新增后端接口后，前端只需要 `api(path, {method, body})`，`api()` 在 `main.js` 顶部，统一处理 JSON 和错误消息。

---

## 6. 外观改造的 15 项（已完成，供二期回归）

1. 榜单行：背景图小横条 + 渐变遮罩，右侧紧凑评分，电影显示「资源」、其他显示「追更」。
2. 电影不出现「加入智能追更」，改为「搜索资源」（当前只是把标题填进搜索框）。
3. 订阅页新增「已归档」（`status === "archived"`）。
4. 网盘链接卡片有「扫码登录」（走 `/api/config/quark/qr/*`、`/api/cloud/p115/cookie/qrcode`）。
5. 资源获取：频道列表 + 每频道规则弹窗（`openChannelEditor`）。
6. 工作台转存和整理规则：通用命名/分类路径 + 115 规则 + 夸克规则（`wsRulesView`）。
7. 云下载：整理方式/触发/间隔/等待 + 115/夸克目录、暂存、范围、一级子目录 + 手动整理（`wsCloudView`）。
8. Webhook：MDC 设置 + 回调地址 + 连接列表 + 最近投递（`wsWebhookView` + `loadWebhookPanel`）。
9. 任务中心：转存任务 / 计划任务两个 tab（`wsTasksView`，计划任务为只读汇总）。
10. STRM：115/夸克源目录、cron、大小、排除、包含子目录、手动生成/扫描、刮削；115 生活监控（`strmProviderView`）。
11. 媒体服务器：媒体库海报网格、封面工坊弹层（`openCoverWorkshop`）、最近入库背景渐变。
12. 链路概览：`.chain-wrap` 加 gap；Webhook 从云下载链路移出，新增 `WEBHOOK_CHAIN_HTML` 03 链路。
13. 全局设置：导入导出移回本页。
14. 通知与交互：通知时间、云下载通知、企微机器人、企微应用、交互指令列表（`settingsNotifications`）。
15. 开发者选项：远程诊断开关 + 运行状态快照（导入导出已移走）。

---

## 7. 本地配置现状（便于复现）

- 本地配置来自真实 env，已写入 `.tmp/local/media.env`，重启不丢。
- 实测可用：TMDB、PanSou、夸克 Cookie、115 Cookie。
- 实测不可用（环境原因，不是代码）：
  - Emby：`192.168.11.239:18096` TCP 可通，HTTP 请求被对端断开，媒体服务器页显示空态；`/api/integrations/emby/images/{id}` 代理未在真实环境验证。
  - OpenList：`https://alist.dunn.fun:666` 可连，但 AList 内部 115 登录态过期（`errNo 990001`），跨盘/整库同步会失败。
- 云下载手动整理接口需要后端重启后才存在（已加入 `backend/app/api/transfers.py`）。

---

## 8. 已知坑（都真实发生过）

1. **文件编码**：不要用 PowerShell `Get-Content`+`WriteAllLines` 改含中文的 `main.js`，会变乱码；用 `[System.IO.File]::ReadAllText/WriteAllText`（UTF-8）或 node 脚本。
2. **Vite 文件锁**：dev server 运行时写 `main.js` 可能报 `EIO Win32 32`；先停 5173 再改。
3. **代码裁剪事故**：本会话裁剪过 `crossState`、`loadCross`，导致跨盘页直接弹回登录页。改大块代码后必须逐路由跑一遍（至少 `#discover`、`#workspace`、`#cross-cloud`、`#system`）。
4. **`.panel + .panel { margin-top }`** 会让并排卡片错位（统计卡 217/231），已删除；布局间距用 flex `gap`。
5. **重复渲染容器**：`#discoverFilters` 曾是重复筛选行的根因，已删。
6. **登录 Cookie**：`PUBLIC_BASE_URL` 为 https 时 Cookie 带 `Secure`，本地登录态不保存。
7. **后端静态托管**：`STATIC_DIR` 指向 `frontend/dist`，改完前端必须 `pnpm build`，否则 8000 还是旧 bundle。

---

## 9. 建议 Codex 的接手顺序

1. 先跑通 8000 本地版，按第 6 节 15 项点一遍，确认没有整页白屏/弹回登录。
2. 补第 10 节的“外观桩”功能，优先级最高的是：
   - 电影「搜索资源」真正进入资源候选/转存流程；
   - 设置页各保存项与后端字段对齐（尤其企微应用、通知时间、开发者诊断）；
   - 计划任务页改为可编辑/可立即执行；
   - 云下载手动整理的目录选择器（现在是手输）。
3. 逐页把 `api()` 调用与 `backend/app/api/*.py` 对齐，删除不再使用的字段。
4. 补自动化：至少一个 Playwright 冒烟，覆盖 8 路由 + 设置 5 tab + 工作台 6 分区。
5. 功能稳定后再考虑删除旧 React 代码（`frontend/src/main.tsx` 等）与依赖。

---

## 10. 外观桩 / 未完成（Codex 重点）

- 详情弹层：电影「搜索资源」只把标题写入发现页搜索框，没有真正拉资源候选；「加入智能追更」调用 `quickTrack`，但电影不显示。
- 计划任务 tab：只读汇总，没有启用/停用/立即执行按钮。
- 通知页：企微机器人/应用的保存字段已接 `/api/config`，但测试按钮与回调验证未全部验证。
- 交互指令：静态列表，没有从后端读取命令定义。
- 媒体服务器：Emby 不可达环境未验证图片代理与封面工坊上传/刷新链路。
- 跨盘：手动复制的目录浏览依赖 `/api/openlist/entries`，本地 OpenList 为空/掉登录，未跑通真实复制。
- 云下载手动整理：目录是手输；建议接 `/api/openlist/entries` 或网盘目录选择器。
- 订阅：真实分集面板、补齐/转存按钮已接后端，但失败分支（如 115 未登录）未逐项验证。
- 发现页豆瓣榜：仍是 TMDB 华语片近似，不是豆瓣官方数据（后端无豆瓣来源）。

---

## 11. 相关文档

- `docs/RELEASE-0.8.9.md`：0.8.9 发布说明、DOM 一致性与验收记录
- `CHANGELOG.md`：0.8.9 条目
- 预览设计源：`D:\Documents\MediaIndex-UI-Preview\index.html`
- 验收截图：`D:\Documents\MediaIndex-UI-Preview\acc-*.png`、`rules1.png`、`cloud1.png`、`wh1.png`、`strm115.png`、`chain2.png`
