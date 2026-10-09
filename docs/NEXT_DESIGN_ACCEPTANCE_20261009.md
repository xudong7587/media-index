# Next 视觉迁入本地验收

日期：2026-10-09。视觉开发 Lane L1；用户授权后的发布为 Lane R。Primary module：shared-core。

基线：GitHub main `7a22b58`。工作分支：`chore/shared-core-next-design`。
本地预览：http://127.0.0.1:5174/#discover 。独立验收后端使用 8001；原工作区和 `.tmp/local-055` 未改写。

## 实现范围

- 按 SunnyUI 和 Next 交接设计重做导航壳、紧凑标题、普通说明页尾、表单分组、移动布局。
- 左下项目介绍按后续要求取消；保留账号、主题、GitHub 和退出入口。新增的一级使用手册入口复用已有路由。
- Logo 为原场记板加放大镜的 SVG；同时用于登录与导航，新增对应 favicon。
- 柔软浮雕使用同色基底、双向柔光、圆润凸面，导航选中、输入框与内层内容用凹陷。深色单独控制光影。
- 玻璃恢复实际背景透光和边缘折光；极光使用多色柔光，纸页使用暖纸细纹，双色为实色方向渐变，缎光为斜向釉光，描边保持克制。
- SunnyUI 1.0.3 vendor 文件保持与独立仓库一致；通用材质经验已回收至 SunnyUI，宿主布局、组件映射和页面适配分别放在 app/next-layout.css、app/next-materials.css、features/workspace/next-workspace.css。

## 模块与兼容性

- Changed modules：shared-core、discover、tracking（订阅壳）、cloud、strm、media-server、settings、plugins 展示页，以及 workspace 中的连接展示适配。
- Shared/Core changed：Yes。导航、主题和公共表面跨多个页面，不能只放在单一业务模块内。
- Behavior changed：业务行为 No；导航展示、响应式位置、布局与文字位置 Yes。
- Database changed：No。
- Config / environment contract changed：No。独立预览启动参数仅存在 ignored 临时目录。
- API contract changed：No。
- Backward compatibility：沿用现有路由、旧入口、外观偏好 ID/存储、API、状态和操作回调。未引入 Next SDK、后端、示例任务或能力限制。
- 未修改后端、数据库结构、任务调度、网盘执行或播放代码。用户后续授权发布 Git，版本更新至 0.7.38-rc.6；不操作 NAS。

## 证明

- `pnpm build`：通过（TypeScript + Vite）。保留已有单包超过 500 kB 的提示。
- 6 个定向前端契约测试文件：30 passed。覆盖 shell、115 Cookie、追更重试、Webhook、资源获取、流程概览。
- TypeScript AST 对比：8 个改动 TSX 文件的 on* 回调属性、api.* 调用和 use* Hook 调用与 HEAD 一致。
- `git diff --check`：通过。
- 发布前全量回归：1397 passed、2 skipped、58 subtests passed；浏览器扩展契约测试通过。
- 发布前移除侧栏“我的工作空间”，菜单上移；同步 SunnyUI 1.0.3 通用源码。
- 全局设置二级菜单取消旧 settings-toolbar 的 sticky 定位，浏览器滚动检查确认 position 为 static，随内容离开视口顶部。
- 320、390、700、1024、1440px：主导航九个页面均检查，未发现文档横向溢出。1024×600 侧栏可滚动，全部菜单与收展入口可达。
- 连接页：夸克凭据和验证面板分列；115 小屏状态、Cookie、扫码与验证区按顺序堆叠，未发现区域交叠。
- 八种材质逐项切换并保存截图；柔软浮雕深浅切换、刷新持久化通过。外观弹窗在 390px 正常滚动，Esc 关闭后焦点回到入口。
- 页面真实数据来源：隔离本地后端；发现页使用现有 TMDB 配置读取公开片目。无云盘连接凭据、无合成任务植入。

## 截图

文件位于工作区 `.tmp/next-design-acceptance/screenshots/`，不作为产品素材提交。

| 内容 | 文件 |
| --- | --- |
| 发现桌面 / 手机 | soft-discover-desktop.jpg / soft-discover-390.jpg |
| 浮雕连接 / 深色 | soft-connections-desktop.jpg / soft-dark-connections.jpg |
| 玻璃连接 | glass-connections-desktop.jpg |
| 其余材质对照 | default / paper / aurora / outline / duotone / satin-connections-desktop.jpg |
| 订阅、STRM、设置 | soft-subscriptions-desktop.jpg / soft-strm-desktop.jpg / soft-settings-desktop.jpg |
| 跨盘、媒体服务器、手册、转码 | soft-cross-cloud-desktop.jpg / soft-media-server-desktop.jpg / soft-guide-desktop.jpg / soft-transcode-desktop.jpg |
| 115 手机 / 外观弹窗 | soft-115-320.jpg / soft-appearance-390.jpg |

## 未覆盖的验收

真实云盘扫码、保存凭据、转存/整理、STRM 生成、Emby 播放与封面生成未触发；相关控件与回调保留。Emby 数据看板仅验证未连接状态，真实媒体库和封面工坊仍需已有账号环境验收。

125% / 200% 浏览器缩放、完整键盘遍历、跨标签外观同步及操作系统强制颜色/减少透明度未做实际环境验收；保留对应兼容规则与原偏好逻辑。各深层业务页面的所有动态组合状态未穷举。
