# MediaIndex 业务模块边界与回归策略

## 目的与权威范围

本文是业务模块归属、当前源码位置、允许依赖、Shared/Core、高风险合同和 legacy 隔离的权威说明。`docs/ARCHITECTURE.md` 只维护产品级不变量，`AGENTS.md` 只维护执行规则；发现冲突时以当前 GitHub 最新正式 Release 的代码、配置和测试为事实依据，就地修正文档。

模块化采用渐进策略：先明确所有权和公开接缝，再在实际功能任务中一次迁移一个能力。不得仅为目录整齐而批量移动源码、改变 API/配置/数据库/路径/STRM/部署语义，或删除兼容逻辑。

## 两维分类与目标依赖

每个文件同时具有业务归属和技术职责。例如 `backend/app/api/tracking.py` 的业务归属是 `tracking`，技术职责是 HTTP adapter；平铺在 `services/` 中不代表它属于 Shared/Core。

```text
frontend feature -> frontend/src/lib/api.ts -> API -> owning service -> domain contract
                                                     |-> provider -> client
                                                     |-> db
```

- API 只做鉴权、校验、序列化和流程装配；新业务流程进入 owning service。
- Service 可以调用稳定的跨模块公开接口，不能调用别的模块的路由私有函数。
- Provider 实现统一云端能力；Client 只处理远端协议。业务模块不得复制夸克、115、QAS 或 OpenList 调用。
- Domain 不依赖 HTTP、数据库、Provider 或 Client。
- 前端 feature 通过 `lib/api.ts` 的合同访问后端；跨 feature 只复用明确的共享 UI/合同，不读取对方页面内部实现。

现有逆向依赖列在“耦合隔离”中。它们是待减少的 allowlist，不是新代码模板。

## 现役模块与源码归属

表中的既有路径以 GitHub Release `v0.6.17` 为稳定基线。后端路径相对 `backend/app/`，前端路径相对 `frontend/src/`。文件以后可以渐进迁移，但业务归属和受保护合同不能在未更新本文与测试的情况下改变。Settings 所维护的配置/安全文件、Activity 所读取的数据库文件仍属于高风险 Shared/Core，业务 owner 不会降低共享合同等级。

| Primary Module | 职责 | 当前后端归属 | 当前前端归属 | 受保护合同 |
| --- | --- | --- | --- | --- |
| `discover` | TMDB 发现/搜索/榜单、PanSou 候选、媒体与季集识别、资源评分和待确认前判定 | `api/media.py`、`clients/{tmdb,pansou}.py`；`candidate_ranker`、`direct_movie`、`episode_*`、`link_resolver`、`media_target`、`movie_*`、`previous_source`、`provider_compat`、`quality_priority`、`query_planner`、`resource_aliases`、`resource_probe`、`share_inspector`、`standard_resolver` | `features/discover/`；详情装配仍部分位于 `main.tsx` | TMDB identity、证据阈值、候选排序、歧义进入 review、不得猜测成功 |
| `tracking` | 智能追更、愿望单、播出元数据、缺集/补集、频道监控和巡检 | `api/tracking.py`、`api/wishlist.py`、`api/cloud.py` 的 channel endpoints；`tracking_engine_v2`、`wishlist_*`、`saved_episode_scanner`、`channel_monitor`、`channel_source_poller` | `features/tracking/`；愿望单和部分追更 UI 仍在 `main.tsx`；频道入口暂在 `features/cloud/`、`features/workspace/` | 自动追更不回补历史缺集；同一媒体/季/Provider 只有一个活动任务；存储读取失败不等于空目录 |
| `transfer` | 转存计划与执行、直链转存、云下载整理、命名和目标路径、Provider 子任务、恢复、人工 review 和转存后处理 | `api/transfers.py`、`api/review.py`；`cloud_download_organizer`、`direct_link_transfer`、`transfer_service_v2`、`transfer_recovery`、`media_workflow`、`post_transfer_pipeline`、`qas_executor`、`qas_reconciler`、`review_notification` | `features/transfer/CloudDownloadOrganizerSettings.tsx`、`features/discover/DirectLinkTransfer.tsx`、`features/workspace/ResourceAcquisitionPage.tsx`、任务/历史视图及 `main.tsx` legacy | 最终路径由后端生成；Provider 结果彼此隔离；逐文件命名预演；终态可恢复；批准候选不能跨 Provider；整理歧义/冲突/失败时不得清理源残留；移动清理只针对重新确认仍在范围内的精确文件 ID，绝不回收整个源媒体目录 |
| `strm` | 资产映射、全量/增量 STRM、Cron/Webhook/115 生活事件、播放 token/Range、清理安全和删除联动 | `api/playback.py`、`playback_main.py`；`api/cloud.py` 的 inventory/strm/deletion endpoints；`strm_jobs`、`strm_reconciler`、`media_assets`、`playback`、`bounded_range_stream`、`p115_life_monitor`、`deletion_workflow` | `features/strm/` | 增量绝不清理；全量清理必须完整、非空、限定范围、连续两次确认并受熔断保护；播放映射不按名称猜测 |
| `media-server` | Emby 连接、媒体库面板/刷新/封面、Webhook 删除联动和反向代理 | `api/emby.py`、`services/emby_*`、`third_party/mediacovergenerator/`；播放进程与 `strm` 共用 `playback_main.py` 接缝 | `features/media-server/` | Emby 与 STRM 通过精确映射协作；删除只进 115 回收站；反向代理和封面任务不能改变媒体资产语义 |
| `cloud` | 夸克/115/QAS 身份和目录、Provider 适配、云资产清单、跨网盘传输 | `api/cloud.py` 的 workspace/directory/cross-transfer/assets endpoints；`providers/`、`clients/{quark,p115,qas,moviepilot_115}.py`；`cloud_inventory`、`cross_cloud_transfer`、`p115_login`、`quark_login` | `features/cloud/{CloudCenter,CrossCloudTransferCenter,MediaLibraryWorkspace}.tsx` | Provider 接口稳定；源/目标身份不混淆；跨盘任务可恢复；业务层不绕过 Provider/Client 复制远端协议 |
| `openlist` | OpenList 客户端、浏览、复制任务、路径映射和同步 | `api/openlist.py`、`clients/openlist.py`、`services/openlist_sync.py` | `features/openlist/` | 只复制缺失文件；不重复活动任务；自动同步方向只约束自动触发；OpenList 不替代原生转存 |
| `integrations` | 企业微信、Telegram、通知渠道、外部回调与 MDC-NG 传输层 | `api/wecom_callback.py`、`api/notifications.py`、`api/mdc_webhook.py`；`wecom_callback`、`telegram_callback`、`notifications`、`notification_channels`、`poster_cache` | `features/integrations/`；通知设置和列表仍部分位于 `main.tsx` | 回调鉴权和去重；通知晚于状态持久化；外部 body 不得扩大 STRM 扫描范围；业务模块只调用标准通知接口 |
| `settings` | 全局及模块配置、导入导出、环境变量兼容、连接测试、登录和安全 | `api/config.py`、`api/auth.py`、`core/{config,env_file,security}.py` | `features/settings/`；部分分区仍在 `main.tsx` | 旧字段和环境变量继续兼容；更新一个分区不擦除其他值；secret 只在服务端；鉴权默认拒绝 |
| `activity` | 跨模块任务、通知、运行状态和日志的只读呈现；不接管各模块执行语义 | 各 owning API 的 list/query、`db/database.py` 中的任务/通知读模型；当前无独立执行 service | `features/activity/`、`features/workspace/TaskCenterPage.tsx` | 展示查询不得触发调度或改变状态；Activity 只聚合公开状态，不调用模块私有执行函数 |

`frontend/src/features/workspace/` 和 `frontend/src/app/` 是页面装配层，不是新的业务模块。新业务必须进入上表 owner；workspace 只能组合 owner 导出的页面/合同。

当前错位但已明确归属的前端文件：`features/cloud/ChannelWorkspace.tsx` 与 `features/workspace/PansouChannelImport.tsx` 属于 Tracking；`features/workspace/ResourceAcquisitionPage.tsx` 属于 Transfer；`features/workspace/TaskCenterPage.tsx` 属于 Activity；`features/workspace/WorkspaceSections.tsx` 属于应用装配。它们只在相应功能被修改并有聚焦验收时渐进迁移。

## 云下载整理的跨模块接缝

云下载整理以 `transfer` 为 Primary Module。它只编排公开接缝，不改变其他模块的所有权：

| 分类 | 模块或区域 | 本次接缝与边界 |
| --- | --- | --- |
| Primary | `transfer` | `cloud_download_organizer` 负责稳定性、TMDB 唯一核对、电影/剧集计划、字幕/NFO 伴随、目标预检、复制/移动、目标核验与任务状态；`api/transfers.py` 只校验总开关/Provider 范围并提交后台任务。 |
| Changed | `cloud` | 夸克和 115 Provider/Client 提供目录、创建目录、改名、复制、移动和回收站能力；业务流程不得复制远端协议，也不得调用永久删除。 |
| Changed | `settings` | `api/config.py` 与 `core/config.py` 保存总开关、复制/移动模式、检查间隔、稳定窗口及两个 Provider 的已选直接子目录；字段均为新增且默认关闭，旧配置继续有效。 |
| Changed | `strm` | 整理成功只通过既有 `post_transfer_pipeline` 请求增量对账；Provider 开关、来源根、输出根和已选直接子目录范围继续生效，整理器不能自行指定更大范围。 |
| Changed | `integrations` | 整理结果继续通过标准通知/入库接缝发送；通知晚于任务状态持久化，并继续受事件和渠道开关约束。 |
| Shared/Core | Scheduler | `services/scheduler.py` 仅在总开关开启时按间隔触发，启动后立即首扫，并保持 `max_instances=1` 与 coalesce；业务规则不得进入调度器。 |
| Downstream unchanged | `media-server` | Emby 刷新仍由 `post_transfer_pipeline` 的既有步骤决定，不新增 Organizer 到 Emby 的私有依赖或第二套刷新合同。 |

目录合同固定为“云下载根的已选直接子目录 → 正式媒体库根的同名直接子目录”。范围下的一级媒体目录是稳定性与清理单元；直接媒体文件则按标题/年份/剧集标记保守分组，移动时不清理同级其他文件。指纹变化重新等待；电影全部视频、剧集全部季度/集数必须唯一进入计划；逐文件清洗后的文本身份必须等于 TMDB 标题/别名，仅无文本的 CD/集数标记可继承目录身份；剧集始终建立季目录；只携带能以同 stem 唯一关联的字幕/NFO。`copy` 保留来源；`move` 仅在所有目标与已持久化的路径、文件 ID、名称和大小强绑定逐项核验后，按精确 ID 清理并轮询确认该 ID 消失，永不回收整个源媒体目录。新到达文件转入新稳定周期；疑似视频、当前授权/身份变化、未匹配视频、TMDB 歧义、目标冲突或任一步失败都必须 fail closed 并给出可见状态。

异常退出与重试属于 Transfer 的幂等恢复合同：以稳定执行键读取既有任务计划，复制前记录暂存目录 ID、基线文件 ID 和源文件身份，并只在 Provider 调用正常返回后确认意图；只将已确认意图后在该暂存目录新出现且唯一符合的 ID 升级为回执，调用未返回、多候选或无意图文件 fail closed。正式媒体库中已唯一核验的目标复用，只续作缺失项，无法证明一致时停止而不是重复写入或猜测成功。该状态继续复用既有任务字段，不引入数据库 schema 变化或 migration。

兼容合同如下：

- API 只新增 `POST /api/transfers/cloud-download-organizer/run` 以及配置读写字段，不改变现有 URL、payload 或响应字段的语义；115 与夸克分别返回接受结果，一侧配置不完整不能遮蔽另一侧。
- 数据状态复用 `transfer_jobs` 和 `media_workflow_steps`，没有数据库 schema 变化或 migration。
- Docker Compose、容器路径、卷挂载和升级步骤不变；旧部署升级后因总开关默认关闭而不会自动扫描或改变已有网盘内容。
- 整理完成继续复用 `post_transfer_pipeline`；STRM、Emby 与通知的既有范围和开关仍是最终权限边界。

## Shared/Core

Shared/Core 不是“暂时不知道放哪里”的收容区，而是多个模块共同依赖且必须稳定的合同。

| 区域 | 当前内容 | 修改要求 |
| --- | --- | --- |
| 后端核心 | `core/`、`db/`、`domain/`、`schemas/`、`services/cache.py` | 配置/迁移/对象语义向后兼容；按受影响模块回归 |
| Provider 合同 | `providers/base.py`、`registry.py`、`status.py` | 新能力优先可选且兼容旧实现；验证全部 Provider |
| 基础客户端 | `clients/http.py` | 不含业务判断；代理、超时和错误语义保持兼容 |
| 调度与路径 | `services/scheduler.py`、`services/paths.py` | 属于高风险共享接缝；单模块需求不得顺带重写 |
| 应用装配 | `backend/app/main.py`、`combined_server.py`、`frontend/src/app/` | 只注册进程、路由、Provider 和页面；不承载新业务流程 |
| 前端合同 | `frontend/src/lib/api.ts` | API 类型和调用兼容；以后可按 domain 拆文件，但保留稳定出口 |

单模块任务修改 Shared/Core 前必须满足：模块内部无法合理实现；说明原因和所有受影响模块；采用最小兼容改动；验证旧调用、配置、数据和 API；在 PR 标为 `cross-module`。

## 当前耦合隔离

以下是源码事实，不是推荐方向：

- `services/wecom_callback.py` 直接导入 `api/transfers.py` 和 `api/review.py` 的内部函数。架构测试固定这两个例外；应先提取 Transfer/Review application service，再删除例外。
- Provider 层仍调用 `share_inspector`、`paths`，QAS Provider 还调用 `qas_executor`；`clients/tmdb.py` 仍依赖 service 层的 cache/alias。架构测试以精确 allowlist 阻止新增逆向依赖。
- `tracking_engine_v2`/`wishlist_engine` 调用 Transfer，Transfer 又调用 Discover、OpenList 和 Provider；`post_transfer_pipeline` 扇出到 Cloud inventory、STRM、Media Server、OpenList 和通知。这些是公开编排接缝，修改调用两端时属于 cross-module。
- `cloud_download_organizer` 属于 Transfer，通过 Provider/Client 的目录、改名、复制、移动和回收站能力操作 Cloud，并在成功后调用 `post_transfer_pipeline`。稳定判断、TMDB 计划和清理门槛留在 Transfer；Provider/Client 不接收媒体业务规则。
- `scheduler.py` 同时调度 Tracking、Wishlist、云下载整理、STRM、115 生活事件、Emby 封面和活动记录。业务逻辑留在各 owner，Scheduler 只保留触发与失败收口。
- `api/cloud.py` 当前混合 Cloud、Tracking channel、STRM 和 deletion endpoints；`api/config.py` 混合 Settings、Provider 登录/测试和调度配置。保持 URL 不变，未来只迁移内部 handler/service。
- 前端现有 cross-feature import 主要是 Cloud/STRM/Integrations/Workspace 复用 `features/settings` 控件，以及 Activity/STRM 复用 OpenList 组件。架构测试固定现状；新共享控件应先移动到明确的 shared UI 出口。

## Legacy 隔离与渐进拆分

| Legacy 位置 | 当前问题 | 下一次触及时的安全接缝 |
| --- | --- | --- |
| `frontend/src/main.tsx` | 应用装配、Discover、Tracking、Transfer、Settings 和通知混合 | 每次只抽一个被修改页面/组件到 owner feature；保持 props、API 调用和路由行为；行数不得超过当前门禁 |
| `frontend/src/styles.css`、`app/emil-workbench.css` | 全局和页面样式体量大、归属混合 | 新 domain 样式与 feature 共置；只迁移本次组件用到的选择器，不全量改名 |
| `frontend/src/lib/api.ts` | 所有模块类型和请求共用单文件 | 先按 domain 提取实现并从原入口 re-export，保持调用方和响应类型兼容 |
| `backend/app/api/config.py` | Settings、Provider、登录、目录和测试 handler 混合 | 先提取 service；保持 `/api/config/*` URL、payload、secret 和兼容回退不变 |
| `backend/app/services/wecom_callback.py` | 传输层、命令解析、Discover/Transfer/Review 编排混合且反向依赖 API | 先建立 channel-neutral interaction service 和 Transfer/Review 公开入口，再迁移一个命令 |
| `backend/app/api/cloud.py` | Cloud、Channel、STRM、Deletion 共用 route 文件 | 按 owner 拆 router/handler，但继续挂载原 URL；先为每组 endpoint 保留合同测试 |
| `backend/app/clients/p115.py`、`services/openlist_sync.py`、`tracking_engine_v2.py` | 大型协议或工作流文件 | 只提取纯 helper 或明确阶段对象；保持异常、状态机、重试和幂等语义 |

legacy 文件仍然受上表业务 owner 约束；“尚未搬目录”不等于允许继续混入新模块逻辑。

## 任务、分支和 PR 边界

1. 开工时声明一个 Primary Module；默认分支使用 `feature/<module>-*`、`fix/<module>-*` 或行为不变的 `chore/<module>-*`。
2. 默认只修改 owner 路径、公开合同和相关测试。发现无关问题，另开任务，不在当前 PR 顺手处理。
3. 必须记录：Primary module、Changed modules、Shared/Core、Database、Config、API contract、Backward compatibility、Tests。
4. Shared/Core、数据库、配置或 API 任一变化都要说明旧调用方/旧数据/旧配置如何继续工作。
5. 一个 PR 若包含多个独立业务目标，应拆分；真正不可分的 cross-module 编排要有调用两端的合同测试。
6. 禁止通过 skip、弱化断言、删测试、提高 legacy 上限或绕过检查让门禁通过。

仓库 PR 模板位于 `.github/pull_request_template.md`。

## 按风险选择回归证据

| 变更 | 最低证据 |
| --- | --- |
| Discover 匹配、解析、命名或路径 | 能阻止错误候选/错误转存的表驱动边界样本 |
| Tracking/Wishlist/Channel | 播出时间、进度、不回补、重试/幂等及 Provider 隔离测试 |
| Transfer/Review/Provider | 独立成功失败、重复执行、命名预演、恢复和 review 身份测试；云下载整理还需覆盖直接子目录映射、稳定窗口、TMDB 歧义/未匹配视频、电影与季目录命名、同 stem 伴随文件、目标冲突、复制保源、崩溃重试目标复用、移动核验后仅按 ID 清理普通残留并保留目录壳、新到达/疑似视频停止清理、失败不清理和后处理范围 |
| STRM/Playback/Delete | 增量不删、两次确认、熔断、精确路径、token/Range 测试 |
| Media Server | Emby 鉴权、刷新/Webhook、删除联动或封面任务的聚焦测试 |
| Cloud/OpenList | 源目标身份、目录边界、复制缺失项、任务去重/恢复测试 |
| Integrations/Settings/Auth | 签名/权限/去重/脱敏/无效输入及旧配置保留测试 |
| DB/Shared/Core/Scheduler | 旧 schema 升级与受影响查询；所有调用模块的合同测试；必要时全量后端测试 |
| UI-only | 聚焦合同测试；需要用户可见验收时使用本地浏览器；编译证明有价值时再 build |

## 盘点基线

2026-08-26 云下载整理正式纳入 GitHub Release `v0.6.15`；代码、配置、接缝与本文说明保持一致。浏览器级 Transfer/Review 端到端固定夹具仍待后续独立任务建立。
