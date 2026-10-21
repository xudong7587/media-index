# 0.8.9 前端替换说明

> 本文保留开发阶段的设计和验收记录。0.8.9 未单独发布，最终正式版本为 [1.0.0](RELEASE-1.0.0.md)，当前功能和限制以该说明及 FRONTEND-INTEGRATION.md 为准。

## 结论

0.8.9 的前端不再是「在旧 React 页面上改样式」，而是以 `D:\Documents\MediaIndex-UI-Preview\index.html`
为唯一设计源重建的一套独立前端，直接对接现有后端接口。

## 结构

- 入口：`frontend/index.html` → `frontend/src/next/main.js`
- 样式：`frontend/src/next/preview.css`（预览页原始样式表，未做作用域裁剪）
- 图标：预览页的 35 个 `<symbol>` 内联在 `frontend/index.html`
- 追加样式：`frontend/src/next/next.css`（登录页、外观面板、通知中心、移动端抽屉等预览未覆盖的部分）
- 使用手册：`frontend/src/next/guide.js`（预览手册页的静态内容 + 章节切换）
- 旧 React 代码（`frontend/src/main.tsx` 及其 features）保留在仓库中但不再被打包引用。

## 页面与接口

| 页面 | 主要接口 |
| --- | --- |
| 发现 | `/api/discover`、`/api/search`、`/api/media/{type}/{id}`、`/api/tracking` |
| 订阅与追更 | `/api/tracking`、`/api/tracking/{id}/...`、`/api/wishlist`、`/api/review` |
| 网盘工作台 | `/api/config/status`、`/api/config`、`/api/config/test-quark`、`/api/config/test-p115`、`/api/config/test-pansou`、`/api/transfers` |
| 跨盘转存 | `/api/config/status`、`/api/config`、`/api/cloud/cross-transfers`、`/api/openlist/test` |
| STRM 与 302 | `/api/config/status`、`/api/config` |
| 媒体服务器 | `/api/integrations/emby/dashboard` |
| 全局设置 | `/api/config/status`、`/api/config`、`/api/config/test-tmdb`、`/api/config/test-telegram-bot`、`/api/config/test-proxy`、`/api/config/export` |
| 使用手册 | 静态内容 |

## 交互

- 外观面板：明暗、圆角（紧致/标准/圆润）、16 种质感、26 套配色，写入 `<html data-*>` 并保存在 localStorage。
- 通知中心：未读角标、列表、全部已读、清空。
- 移动端：≤1000px 隐藏侧边栏，顶栏汉堡按钮 + 遮罩抽屉。
- 订阅页支持网盘开关、保存路径、追更时间、执行/暂停/移除、分集展开、愿望单与待确认操作。
- 链路概览：完整流程图，节点显示配置状态，点击节点或「打开…」按钮跳转到对应页面。
- 目录选择：追更保存路径支持弹窗浏览网盘目录（夸克 / 115），选择后直接保存。
- 扫码登录：夸克与 115 均支持二维码登录；登录 URL 在前端本地渲染为二维码，避免外部图片被 CSP 拦截。
- 任务中心：任务卡可点开详情，查看状态、阶段、路径、源文件与时间。
- 频道订阅：工作台「资源获取」内可启用/停用、同步、删除频道，并从 PanSou 批量导入。
- Emby 封面：媒体服务器页可设置封面风格、刷新计划与参与媒体库，并立即刷新。
- 配置导入/导出：开发者选项支持导出 JSON 与导入还原。

## 验收

- `pnpm --dir frontend build` 通过。
- 8 个一级路由在本地真实数据下逐页截图，浏览器控制台无错误。
- `python -m unittest tests.test_frontend_resource_acquisition_contract` 6 项全部通过。
- 版本号 `VERSION` = 0.8.9，`CHANGELOG.md` 已记录。

## 未包含

- 未推送 GitHub、未创建 PR、未打 tag、未构建镜像；发布需要明确指令 `发布 Git`。
## 0.8.9 追加（验收前补齐）

- 发现页：榜单回到页内，新增 Netflix / HBO Max / Apple TV+ / Disney+ / Prime Video / Amazon / Hulu / 豆瓣高分 八个榜单与地区、类型筛选；新增链接下载；顶栏任务按钮。
- 跨盘转存：改用 /api/cross-copy/config，支持 OpenList / CD2、自动补齐开关、手动复制（目录浏览、条目勾选、整库同步）与复制队列。
- STRM：补回 Emby 库刷新、删除方式与删除 Webhook、115 生活事件监控路径与间隔。
- 云下载：新增手动整理接口 POST /api/transfers/cloud-download-organizer/organize 与前端入口。
- 订阅：分集改为弹窗，支持勾选缺失集直接补齐。
- 全局设置：补回追更/愿望单调度的全部参数、直接下载开关与目录。
- 后端新增测试 tests/test_cloud_download_organizer_manual.py（3 项）。

### 已知限制

- 豆瓣高分榜使用 TMDB 华语片评分近似，非豆瓣官方数据（仓库与后端均无豆瓣榜单接口）。
- Webhook 页面暂未展示 MDC / BiliSync 的历史配置，待实际部署后再对照。
- 手动整理接口需要重启本地后端进程才会在 8000 端口生效。
## DOM 移植收尾

- 发现页：筛选行位于 banner 下方，链接下载为工具栏小条，右侧追更看板/今日概览与 banner 等高，去掉冗余的板块说明与悬浮箭头。
- 订阅页：卡片改为预览 `.task-card` 结构，分集面板在同一卡片下方整行展开（单开互斥），操作行与参考一致。
- 工作台：网盘链接改为 `.switch-row` + `.card-grid > .conn-card`；任务中心、频道订阅、复制队列统一 `.list` / `.list-row`。
- 跨盘 / STRM / 订阅 / 设置：二级菜单统一 `.subnav`；表单使用 `.form-grid` / `.field`。
- 全局设置：修复卡片嵌套错误，保存按钮回到卡片内部。
- 列表内边距统一，移除导致错位的 `.panel + .panel` 外边距。

### 验收记录

- `pnpm --dir frontend build` 通过。
- 8 个一级路由逐页截图，浏览器控制台无异常。
- `python -m unittest tests.test_cloud_download_organizer_manual tests.test_frontend_resource_acquisition_contract` 9 项通过。
