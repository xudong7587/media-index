# 0.8.9 前端替换说明

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

## 验收

- `pnpm --dir frontend build` 通过。
- 8 个一级路由在本地真实数据下逐页截图，浏览器控制台无错误。
- `python -m unittest tests.test_frontend_resource_acquisition_contract` 6 项全部通过。
- 版本号 `VERSION` = 0.8.9，`CHANGELOG.md` 已记录。

## 未包含

- 未推送 GitHub、未创建 PR、未打 tag、未构建镜像；发布需要明确指令 `发布 Git`。
