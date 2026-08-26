# MediaIndex 架构与可靠性边界

`docs/MODULE_BOUNDARIES.md` is the authoritative map for code ownership, allowed dependency direction, regression tests, and the current legacy-debt quarantine. This document records product-level safety invariants; read the boundary map before adding a feature.

## 架构模型

MediaIndex 采用 **Stable Release + Business Modules + Shared Core + Small PR**：每次任务以 GitHub 最新正式 Release 为稳定基线，一个 PR 默认只有一个 Primary Module；只有稳定合同进入 Shared/Core。

业务归属与技术分层是两个维度。`discover`、`tracking`、`transfer`、`strm` 等回答“谁拥有这项行为”；`api / services / providers / clients / db / domain / core` 回答“代码承担什么技术职责”。现阶段保留技术分层，不以模块化为理由批量搬迁现有文件。

目标依赖方向是：

```text
frontend feature -> frontend API contract -> API adapter -> owning service -> domain contract
                                                        |-> provider -> client
                                                        |-> db
```

业务模块不得读取另一个模块的私有实现；跨模块协作通过明确的 service、domain contract、事件或 API 完成。当前逆向依赖和大型 legacy 文件已在 `docs/MODULE_BOUNDARIES.md` 中隔离，并由架构测试阻止继续扩散；渐进迁移必须保持现有 API、配置、数据库、路径、STRM、部署和用户行为兼容。

## 通用 Provider 门面

MediaIndex 的资源验证、文件匹配、改名和转存通过通用 Provider 门面执行。当前主要
Provider 为原生夸克和原生 115，QAS 保留为兼容执行器；MoviePilot 仅可作为 115 Cookie
的导入源或用户自行配置的后处理器，不参与 MediaIndex 的核心转存事务。

一次多网盘操作会创建一个父批次，并按 `provider × season` 拆分为互相独立的子任务。
父批次统一展示进度和结果；一个 Provider 成功、另一个失败时状态为 `partial`，成功结果
必须保留，失败原因进入通知和任务详情，不能回滚或遮蔽成功任务。

## 产品定位

MediaIndex 是部署在个人 NAS 上的媒体发现和转存控制台。后端连接 TMDB、PanSou 与各网盘 Provider，负责目标识别、候选验证、文件匹配、规范命名、任务调度和通知；前端只负责展示、选择和确认。

QAS 是执行器，不是 MediaIndex 的主状态中心。浏览器、历史任务和搜索结果都不能直接指定最终保存路径或绕过后端校验。

## 核心流程

```text
资源名/发现卡片先通过 PanSou 搜索候选分享
  -> 标准电影若能从 PanSou 标题、年份和真实文件唯一确认：直接生成电影目标
  -> 其他媒体或证据不足：TMDB 匹配规范媒体与目标季集
  -> 检查目标目录和下一缺失集
  -> 验证 PanSou 候选或上一次分享链接
  -> 排序候选并读取真实文件树
  -> 综艺匹配集数/期数/日期；电影和电视剧核对名称、年份及季集标记
  -> 预演 pattern / replace 和目标文件名
  -> 高置信度：提交对应网盘 Provider
  -> 存在歧义：进入待确认
  -> 校验执行结果并更新追更、愿望单和通知
```

电影、剧集、综艺、网页操作和企业微信指令最终都复用同一套后端任务与校验流程。

## 自动执行边界

只有同时满足以下条件时才允许自动执行：

- 普通任务通过 TMDB ID 重新解析规范标题、年份、类型、季和目标集；标准电影直通任务必须具备 PanSou 标题、年份和真实文件三重证据。
- 分享链接有效，并能读取用于判断的真实文件列表。
- 每个源文件最多映射到一个目标，且没有错误年份、错误季或重命名冲突。
- 集号、中文期数、播出日期或文件序列提供足够且可解释的证据。
- 候选标题与媒体明确匹配，第一候选达到阈值并与其他候选拉开分差。
- Provider 执行前完成逐文件匹配和目标名称预演。

证据不足时采用 fail-closed 原则：停止自动执行并进入待确认，不扩大匹配范围，也不猜测成功。

## 文件匹配与命名

自动模式优先使用逐文件精确映射：

```text
pattern = ^<escaped source filename>$
replace = <title>.<year>.S<season>E<episode>.<extension>
```

匹配支持标准季集号、中文期数、播出日期和受约束的数字序列。综艺会额外排除加更、纯享、花絮、预告和陪看等衍生内容。任何新增规则都应先加入脱敏回归样本，避免为提高召回率而引入错误转存。

## 路径与安全

- 夸克、115 和本地根路径由服务端分别配置，两个原生网盘各自维护云下载目录；旧 `CLOUD_SAVE_PATH`/`CATEGORY_PATHS_JSON`
  继续作为夸克兼容回退值。
- 115 网盘暂存目录只用于接收、核对、改名和移动；115 本地下载使用单独的容器挂载目录，
  文件先写入同目录临时文件，完成大小校验后再原子替换最终文件。
- 每个网盘维护独立分类子目录；自定义分类键只允许安全标识符，路径禁止点段。
- 最终路径必须由后端拼接，前端不能提交任意绝对路径。
- 密钥只保存在服务端配置中，接口仅返回是否已配置。
- 登录 Cookie 使用服务端会话，敏感 Token 不写入浏览器存储或日志。

## STRM 对账与清理边界

- STRM 生成继续使用 Provider 的分页/批量只读清单；默认不设文件总量上限，本地资产按 500 条事务批写。
- 增量任务只创建、替换和校验映射，不能推进缺失项清理。外部完成事件 Webhook、Cron、115 生活监控和转存后处理都属于增量任务。
- 清理只允许在完整、非空、未截断的全量枚举后执行，并同时限定 Provider、来源根目录、媒体库标识和所选直接子目录。
- 第一次缺失只进入 `pending_remove` 并保留 STRM 与播放能力；连续第二次完整扫描仍缺失才按已登记精确路径删除。超过范围 10% 或 50 条的删除计划触发熔断。
- Emby 联动删除先以 STRM 相对路径精确映射 115 资产，不按名称猜测且只调用回收站操作；单集和未知类型只删除唯一文件 ID，Emby 明确删除目录或独占电影目录时才按持久化范围删除对应的非根 115 目录 ID。

## 状态与可靠性

- 同一媒体、季和保存目标只允许一个运行中、待执行或待确认任务。
- QAS、Cookie 或目录查询异常不能退化为“目录为空”或“任务成功”。
- 完成状态需要 QAS 明确成功，并验证目标目录和预期文件。
- SQLite 启用 WAL、外键和 busy timeout；进程重启时会恢复或标记中断任务。
- 展示接口不得触发调度计算或数据库状态变化。

## 通知与交互

转存完成、任务提交、待确认、暂无资源和失败事件先写入站内通知，再按配置以海报图文优先的形式推送到 Telegram、企业微信群机器人或企业微信自建应用；无可访问图片时回退文字。

企业微信回调经过签名校验、AES 解密、企业 ID 校验、成员授权和重复投递去重。资源搜索存在歧义时返回编号候选，用户确认后才创建任务；待确认任务同样复用网页端的安全确认逻辑。

增量同步 Webhook 使用独立密钥认证，外部 Body 不能指定 Provider 或扫描路径。连续完成事件先合并，再以服务端保存范围触发只增不删的 STRM 增量任务；MDC-NG 只是可接入的外部服务之一。
