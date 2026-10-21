# 原生前端对接记录 · 2026-10-20

本文补充 FRONTEND-HANDOFF.md。原交接文档中的“外观桩 / 未完成”与环境可用性描述是交接时状态，不代表本次结果。

## 范围与兼容性

- Lane：B。Primary module：settings。
- Changed modules：discover、tracking、transfer、cloud、openlist、strm、media-server、integrations、activity。
- Shared/Core changed：新增前端 DOM 表单、弹窗、按钮事件和目录选择组件，供上述页面共用，避免重复事件与重复提交。未修改后端 shared-core。
- Cross-module reason：新原生前端替代旧 React 入口，需要补齐这些页面已有后端功能；保留各业务模块独立实现。
- Behavior changed：Yes，原先只展示、无响应或字段错误的控件现在调用对应接口，并显示失败。
- Database changed：No。
- Config or environment variables changed：No；只修正前端使用的已有字段和编辑入口。
- API contract changed：No。
- Backward compatibility：继续使用已有后端、配置和数据库；没有删除旧 React 代码。未改版本、提交、推送、创建 PR 或发布；未操作 NAS。

## 补齐和修正

| 页面 | 对接内容 |
| --- | --- |
| 发现 | 真实资源候选、目标目录、选择候选后转存、愿望单、分季追更；榜单按钮防重复绑定，快速切换防旧请求覆盖 |
| 订阅 | 每个网盘独立任务 ID、保存目录、最终集数、分季执行、暂停与归档、115 跨盘补齐、愿望单设置、待确认文件选择；多网盘部分失败单独报告 |
| 网盘工作台 | 实际网盘目录选择；配置字段纠正；分类规则保存；明确目录的手动整理；频道保存错误保留输入；QAS 兼容配置与分享只读检查 |
| Webhook | 连接创建、编辑、启停、删除、密钥操作、测试和投递重试；内建 MDC 与普通连接区分 |
| 任务 | 六类计划编辑；真实任务记录、停止和整理重试；右上角范本浮层、筛选和五秒刷新；范本时间线详情 |
| 跨盘 | 队列刷新/清理入口、选择状态和失败反馈、重复提交保护 |
| STRM | 生成范围校验、生活监控、删除意图列表和确认入口、Emby 联动字段与回调地址 |
| 媒体服务器 | 封面工坊真实参数、字体、预览、单库/批量应用、定时设置；保留各媒体库独立标题 |
| 设置 | Telegram 字段、企微应用与机器人字段、回调与接收人、交互网盘与快捷指令、短时诊断令牌、导入导出及错误提示 |

“通知启用时间”是后端启用后的时间戳，不是可配置的定时发送时间，已移除误导控件。后端没有豆瓣官方榜单和动态命令定义接口，榜单明确标记 TMDB 华语高分，命令说明按现有实现列出。

## 外观约束

保留 preview.css 原样；补充样式仅放在 next.css。右上角任务浮层和任务详情复用范本的 popover/pop-task/task-dialog/step/td-facts 结构和样式。流媒体榜保留平台切换、横条、评分、右侧操作。

任务 API 只有当前阶段，没有六步完整事件历史。已知转存阶段按范本六步展示；未记录的步骤时间显示“—”，不会生成假百分比或假完成记录。Emby 等非转存任务展示其实际状态。若需要截图中每一步精确时间和完整历史，需要另行扩展后端事件记录。

## 验证

- `pnpm --dir frontend test`：15 项通过，使用 HappyDOM 和模拟接口。覆盖八个路由、设置五分区、工作台六分区、字段契约、密钥留空保留、目录失败关闭选择、资源转存防重复、网盘 ID、部分失败、频道保存错误、封面参数、六类计划、范本任务浮层与详情。
- `pnpm --dir frontend build`：通过。
- 后端相关回归：`test_discovery_destinations.py`、`test_cloud_download_organizer_manual.py`、`test_frontend_resource_acquisition_contract.py`、`test_tracking_retry_config.py`、`test_notification_channels.py`、`test_diagnostic_support.py`，共 50 项通过；一个现有 Starlette/httpx 弃用警告。
- 本地浏览器：实际登录、设置分区、工作台分区、计划任务弹窗和窄屏布局检查。修正窄屏弹窗标题造成的横向溢出。
- 验收地址：<http://127.0.0.1:8000/>，使用构建后的 dist；无需 5173。
- 未触发真实云端转存/删除、通知发送、Webhook 外发、支持令牌授权或 Emby 封面写入。自动化成功不等于这些外部服务的端到端验收。

本地配置、数据库和凭据保持原状。真实外部动作需按指定作品、目录或媒体库逐项人工验收。


## 2026-10-21 本地验收反馈修正

本轮 Lane：B（路径保存与设置契约），Primary module 为 settings；涉及 integrations、tracking、cloud、strm、discover 和共用目录组件。后端、数据库结构、API 和环境变量定义均未变更，未发布。

1. 外观面板改用幂等事件绑定，切换选项后能继续正常开关。
2. 圆角改为六档滑条（6/10/14/18/22/28px）；不同质感使用相同基准，卡片与二级菜单外框一致。
3. 任务中心和通知设置的三级页签使用普通卡片页签样式。
4. 分类路径只保留通用表单；点击保存通用规则时清除 115/夸克的独立分类覆盖，使两者继承通用值。
5. TG 导入结果只在频道操作按钮左侧显示；离开分区或关闭频道源后清除，不出现在其他保存区。
6. 网盘、云下载、STRM、分类、跨盘、全局路径与追更设置统一使用地址栏内的线条文件夹按钮；QAS、本地挂载目录沿用后端已有浏览范围限制。
7. 云下载手动整理的网盘和目录输入对齐；目录按钮不再增加一行。
8. 两个网盘 STRM 的全量/增量选择与生成按钮相邻；指定目录扫描单独一行。生成使用源根目录与明确的包含范围，扫描使用单独目录输入。
9. 流媒体榜单卡片使用最近入库式背景图与渐变，宽屏两列、窄屏一列；评分和操作保留。
10. 概览文案恢复旧版含义：云下载先接收/发现、暂存、TMDB 匹配、整理、正式库、STRM、Emby；已整理的 Webhook 走增量旁路。
11. 追更与愿望单的巡检开关、节奏归还订阅页；直接下载放入通知与交互的云下载设置。
12. 通知与交互恢复通知 / 交互指令 / 云下载设置三级结构；企业微信应用和回调在同一卡片保存，云下载页显示路由说明、目录入口与交互转存记录。

验证：20 项前端回归通过，生产构建通过。本地浏览器核验设置三级页签、外观面板、两种极端质感的相同圆角、手动整理对齐、STRM 分行与榜单背景卡片；未触发真实转存、整理、STRM 生成或外部消息发送。


### 海报边缘与榜单切换补充修正

- 横向海报条为阴影增加上下及左右留白，保留第一张海报的对齐；海报装饰层继承相同圆角轮廓，去除边框裁切毛线。浏览器确认页面未产生额外横向溢出。
- 删除发现页独立榜单渲染路径与覆盖平台按钮的通用事件。平台切换只更新发现页内榜单，并即时标记选中和加载状态；失败保留平台按钮及上次结果。
- 轮播改为仅更新图片和圆点状态，不再定时重建整个发现页，避免中断榜单请求或重置横向海报条。
- 21 项前端回归通过，包括延迟接口下平台切换和轮播保持页面节点。构建通过；未改变后端、配置或数据库。


### 媒体详情与窄屏链路补齐（2026-10-21）

- Primary module: discover；Changed: activity、transfer、settings；Lane: B；Shared/Core changed: No。
- 媒体详情恢复作品资料、季度选择、分类、网盘资源/候选、授权目录、愿望单、转存、追更与手动链接核对；每个网盘独立展示失败，重复提交受阻。执行仍走原批次与直链接口，目录由后端授权。
- 新版横向链路与任务详情共用八节点视图；任务详情展开后按钮变为“关闭完整记录”，刷新保留展开状态。
- API contract changed: Yes，新增鉴权只读 GET /api/transfers/{job_id}/workflow，按精确历史任务 ID 查询已保存节点；不启动任务、不初始化缺失节点，历史缺失状态为 unknown。原媒体级查询接口保持兼容。
- Database changed: No；Config/environment changed: No；Behavior changed: Yes（上述界面和新增查询）；原执行/目录/Provider 合同保持不变。
- 外观弹窗移出顶栏滤镜容器，窄屏固定在视口内；链路概览按实际容器宽度换行，手机竖向展示节点，修复标题与标签挤压。
- Proof: frontend 24 tests passed；test_media_workflow.py + test_transfer_api.py 57 passed；frontend production build passed。测试覆盖完整链路、旧任务精确查询与不写入、展开状态、单 Provider 失败隔离、重复转存阻止及手动链接失效。
- Browser acceptance: 本地桌面媒体详情/横向链路、390px 外观弹窗/链路概览及完整记录展开收起。真实网盘连接错误显示在对应 Provider；未提交真实转存、整理或通知。
- Known follow-up: 无历史节点记录时显示“未记录”，不倒推各步骤成功；现有真实 115 目录连接返回错误，未修改其凭据。无 Git 发布、无 NAS 操作。


### 媒体详情改为工作区页面、链路节点按需展开（2026-10-21）

- Lane: L1；Primary: discover；Changed: transfer（共享链路视图的横向呈现）、activity（沿用纵向呈现，行为不变）。Shared/Core changed: No。
- 详情使用 #discover/{media_type}/{tmdb_id} 路由，占用右侧内容区，一级菜单和顶栏可继续使用；返回发现、浏览器前进后退和详情地址刷新均保留页面入口。离开详情停止轮询，晚返回的接口结果不得覆盖新页面。
- 横向节点默认仅显示名称、状态和标识，点击后在对应网盘链路下方展开说明与更新时间，再次点击或收起按钮关闭；轮询后保留展开项。按实际容器宽度展示 8/4/2 列，窄屏不横向溢出。
- Behavior changed: Yes（上述 UI）；Database/config/environment/API changed: No；原转存、路径、Provider 与任务纵向链路合同不变。
- Proof: 26 frontend tests passed；production build passed；本地浏览器验收右侧详情、一级菜单、节点展开收起与窄屏分行。真实转存未执行；未发布 Git。


### 媒体详情窄屏整体走查与 Logo 统一（2026-10-21）

- Lane: L1；Primary: discover；Changed: shared-core（Logo 的 SVG 与外观 token，影响侧栏和登录图标）、tracking（仅追更设置弹窗的移动端尺寸）。Shared/Core changed: Yes，仅图标呈现，原因是同一品牌符号由应用外壳共享，不属于发现页。
- 按右侧实际内容宽度切换布局；320/390 手机与 768 平板均无页面横向溢出。长标题与简介分区，资料两列，主操作满行、次操作合理换行，按钮和目录选择增加触控高度。
- 授权目录加载/失败/空列表时禁用选择；选中路径完整回显。分 Provider 更新资源区和目录区，另一查询返回不会重建当前目录下拉框；刷新后按 child_name 保留目标，不按选项序号猜目录。节点展开支持长路径换行，轮询后保留展开与关闭按钮焦点。
- 共享 Logo 保留图形，移除固定粉色渐变和黑色线条，使用 currentColor + 当前主色，背景、边线和阴影复用 mat-control 质感。favicon 不变。
- Behavior changed: Yes（上述 UI）；Database/config/environment/API changed: No；执行与授权目录合同不变。
- Proof: 27 frontend tests passed；production build passed；本地 320/390/768 浏览器模拟数据走查愿望单、追更弹窗、目录切换、手动链接预览与确认、转存提交状态及节点展开收起。像素宽度 client/scroll 分别 305/305、375/375、753/753。实际页面检查 Logo 跟随当前配色与控件质感。
- 真实网盘写入未执行；模拟数据只用于布局验收；未发布 Git，未操作 NAS。

- 补充验收：共享登录图标与侧栏 Logo 均在本地浏览器检查；长路径说明强制合理换行，模拟验收临时静态入口已清理，原用户 #strm 页面保持打开。


### STRM 窄屏、统一下拉面板与外壳图标（2026-10-21）

- Primary: strm；Lane: B（手动提交互斥保护）；Changed: shared-core，仅通用控件和外壳呈现。原因：下拉面板、Logo 与导航按钮由所有模块共用，无法只在 STRM 内修正。
- 三页签按实际内容宽度响应：通用设置/115/夸克在手机同时可见；表单单列，模式与生成按钮相邻，目录扫描独立一行，目录图标保持输入框右侧，长路径/记录/反馈可换行。目录对话框统一关闭与确认按钮触控尺寸。
- 保留原生 select 值、change 事件和键盘行为，浏览器支持 base-select 时，面板使用系统圆角、表面、边线和柔和选中态；不支持时保留原生回退。多选 select 不变。影响各模块单选控件，既有表单与提交合同不变。
- STRM 生成与目录扫描提交期间互斥，防止手机连点；页签切换清理其他分区的保存提示，过期配置响应不能覆盖新页面。
- Logo 内图形位移改为 translate(7.5 7.75)，保留当前主题色和质感；手机菜单按钮使用现有 icon-btn 外观，补充展开状态。
- Shared/Core changed: Yes（上述呈现）；Database/config/environment/API changed: No；Behavior changed: Yes（响应式与重复提交保护）。
- Proof: 28 frontend tests passed；production build passed；模拟数据浏览器走查通用本地目录、115 一级子目录、夸克源目录、保存反馈、模式选择和生成/扫描提交状态；真实 STRM 生成、删除和配置写入均未执行。菜单圆角实测 18px 并随圆角变量变化。
- 本轮无 Git 发布、无 NAS 操作；临时浏览器验收资源交付前清理。

- 最终窄屏证明：320/390/768px 下 clientWidth 与 scrollWidth 分别 305/305、375/375、753/753；三页签均走查。手机顶栏仅保留当前页面标题以避免换行挤压。所有临时 qa-strm 静态入口已移除。

### 1.0.1 部署反馈修复（2026-10-21）

- Lane: B；Primary: discover；Changed: transfer、cloud、openlist、tracking、integrations、activity、media-server、settings、shared-core（共享按钮对齐和侧栏）。公共控件由应用外壳共享，无法只在一个业务页面修正。
- 媒体详情的返回按钮与箭头居中，分类选项位于文字右侧并留出间距；作品资料、资源、目录浏览、链路说明适度增大字号。
- 发现页分享资源省略云下载子目录，复用批次接口按作品身份核验、命名并写正式媒体库；详情和快捷资源弹窗均不再请求 destination-options。普通链接下载仍走原云下载流程，磁力也仍需先下载。
- 夸克和 115 各自有转存、打开资源、复制分享和 PanSou 入口；兼容候选的 cloud_type="115"。底部双盘按钮在两盘资源可用时提交两个独立 Provider；夸克有、115 明确无资源时改为夸克完成后补齐 115，不把查询错误当成无资源。115 有、夸克无的反向自动补偿不开放。
- 显式双盘补齐使用已有 openlist_fallback_to_p115 请求字段；本次请求可在全局自动补齐关闭时执行，仍要求启用跨盘功能，不修改全局开关、自动方向或复制其他任务。
- CD2 手动复制增加 115 → 夸克方向；服务端验证来源与目标均在已保存挂载范围内。复制回执与 target_provider 复用现有任务 JSON；CD2 队列完成且原生夸克核验精确目标后，才按原接缝执行 STRM/Emby。OpenList 反向请求继续拒绝，自动方向保持夸克 → 115。
- 链接下载使用清晰的返回按钮；追更目录按钮改为文件夹图标，巡检设置移到二级菜单下方横向区域，任务使用整行宽度。
- PanSou 排除词保留原有文本与换行，使用不可拖动调整大小的固定高度编辑框；频道订阅增加全部开启/关闭，保留每个频道的规则并逐项显示部分失败，不触发同步或转存。
- 任务中心三级菜单增加内边距和统一控件表面；媒体库占据整行，播放会话从概览卡打开独立窗口。
- 窄屏链路概览增加向下汇合箭头，顺序处理说明采用正文中文字体；手册绑定实际 chapter 元素，九章及四张顶部入口均可切换。
- 左下角移除单独的深色按钮，GitHub 图标移至右侧；外观面板保留明暗切换。
- 发现 banner 将 cover / center / no-repeat 应用到真实背景层 hero-art，修复宽屏平铺重复，轮播行为不变。
- Compatibility: Behavior changed: Yes（上述修复）；Database schema changed: No；Config/environment changed: No；API contract changed: Yes（CD2 手动复制方向兼容扩展、已有显式补齐字段按单次意图执行）；旧调用、OpenList 单向与自动补齐默认规则保留。
- Proof: 全量 Python 回归 1491 passed、2 skipped、61 subtests passed；前端 35 项回归及生产构建通过。真实外部写入未执行，浏览器动作使用隔离模拟响应；本轮不发布 Git、不操作 NAS。

### 后续四处界面修正（2026-10-21）

- Lane: L1；Primary module: discover；Changed modules: integrations（PanSou 来源表单）、settings（链路概览）；Shared/Core changed: No。各模块局部选择器与交互修正，未增加共享组件。
- 分类标签与选项横排；分享复制使用独立浮动提示，约 1.8 秒自动移除，成功或失败均不写到手动链接表单下方。页面退出清理提示计时器。
- PanSou 排除词恢复固定高度 textarea，完整回显已有关键词和换行，可直接编辑；禁止拖动尺寸，保存字段与接口保持原样。
- 窄屏直接复用宽屏原有曲线，通过 SVG transform 顺时针旋转 90°，并随来源区域横向展开；沿用线宽、柔光与汇合节点，节点位于旋转后的 58% 高度。
- Compatibility: Behavior changed: Yes（上述界面反馈）；Database changed: No；Config/environment variables changed: No；API contract changed: No；Backward compatibility: 原值回显、原保存合同和复制内容（含提取码）保留。
- Proof: 两项针对性前端回归通过（复制内容/短暂提示/错误反馈、原关键词回显及编辑保存）；production build 通过；390/1280px 隔离模拟数据浏览器验收通过，390px 无横向溢出。没有写真实配置、网盘或 NAS；未发布 Git。

- 括号最终修正：Lane L1；Primary/Changed module: settings；Shared/Core changed: No。依用户最新要求，撤销另画的大括号，直接复用宽屏原曲线旋转 90°；SVG 使用 preserveAspectRatio="none" 随来源区域展开，避免此前等比例缩成中间一小段。Behavior changed: Yes（呈现）；Database/config/environment/API changed: No；Backward compatibility: 入口与链路行为不变。Proof: 生产构建通过，真实本地浏览器中 SVG 和来源区域宽度同为 572.67px、transform 为 rotate(90)，clientWidth/scrollWidth 均 738；纯 SVG/CSS 修正不增加逻辑测试。未发布 Git、未操作 NAS。

- 1.0.1 发布检查（R）：用户确认发布后同步更新 VERSION 与前端包版本；Python 全量回归 1491 passed、2 skipped、61 subtests passed，前端 35 项、冻结锁文件安装、生产构建和浏览器扩展合同检查均通过。未纳入本地模拟器、临时验收入口、沙箱配置或数据库；GitHub 负责镜像与 Release，NAS 由用户手动更新。
