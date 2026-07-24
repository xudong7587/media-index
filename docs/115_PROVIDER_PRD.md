# MediaIndex 原生 115 Provider PRD 与技术设计

> 状态：重规划稿（2026-07-23）
> 决策：115 核心链路改为 MediaIndex 原生执行，不再强依赖 MoviePilot
> 目标：MediaIndex 自己完成检索、验链、文件筛选、规范命名、转存与结果确认
> MoviePilot 定位：可选的 STRM/媒体整理后处理器，不参与核心转存闭环

## 1. 决策背景

原规划把 MoviePilot 的 `P115StrmHelper` 作为 115 执行器。该方案可以提交分享转存，但 MediaIndex 无法在提交前稳定读取分享中的真实文件，因此不能完成产品最核心的“确认、筛选、改名”。

新规划将 115 作为原生 provider：

```text
TMDB -> PanSou -> MediaIndex 验链/文件匹配 -> 用户确认 -> MediaIndex 转存/改名 -> 结果确认
```

MoviePilot 不再是必要依赖。用户已经部署 MoviePilot 时，可以让它自行监控 MediaIndex 写入的 115 目标目录并生成 STRM；未部署 MoviePilot 时，MediaIndex 的检索、确认、改名和转存仍应完整可用。

## 2. 产品目标

### 2.1 必须实现

1. 支持两个完整网盘 provider：
   - `qas`：夸克执行器。
   - `p115`：MediaIndex 原生 115 执行器。
2. 原生 115 provider 必须支持：
   - 读取外部 115 分享目录与文件列表；
   - 递归读取目录，保留文件 ID、目录 ID、名称、大小与媒体类型；
   - 使用现有 TMDB 匹配器进行电影、季度和集数核对；
   - 用户选择候选文件；
   - 先生成可审查的改名方案，再执行转存；
   - 转存到暂存目录后执行重命名/移动；
   - 通过目标目录证据确认结果。
3. 设置页允许分别启用 QAS 与原生 115。
4. PanSou 根据启用项搜索 `quark`、`115` 或两者。
5. 单次任务、候选、愿望单、追更和历史均固化 provider，不得静默改投。
6. 只配置 QAS 的旧用户升级后行为不变。
7. 同时启用 QAS 与 115 时，MediaIndex 对同一媒体选择创建一个批次，并为每个
   `provider × season` 创建独立子任务；搜索结果、验链进度、改名计划和执行结果分别记录。
8. 多 provider 批次允许部分成功：成功子任务继续转存，失败子任务不回滚成功结果，并向用户汇总
   “成功网盘、失败网盘、失败原因和可重试项”。

### 2.2 非目标

1. 本阶段不在 MediaIndex 内生成 STRM、提供 302 播放或维护媒体服务器。
2. 不要求用户部署 MoviePilot、CloudMediaSynC、SmartStrm 或其他媒体管理工具。
3. 不自动下载媒体内容到 MediaIndex 服务器；115 转存应在网盘服务端完成。
4. 不把两个 provider 合并成一个不可审计的执行任务；多网盘请求必须拆成独立子任务。
5. 不承诺绕过 115 的验证码、风控、访问频率或账号限制。
6. 不把未经验证的私有接口伪装成稳定官方能力。

## 3. Provider 与组件边界

### 3.1 Provider 标识

| Provider | 含义 | 核心执行者 |
| --- | --- | --- |
| `qas` | 夸克网盘 | QAS |
| `p115` | 原生 115 | MediaIndex |
| `moviepilot_115` | 旧实验执行器/可选兼容项 | MoviePilot 插件 |
| 空 | 本地任务 | MediaIndex 本地流程 |

新任务不再使用 `moviepilot_115` 作为默认 115 provider。已经产生的历史记录保留原 provider 以便审计，不原地改写为 `p115`。

### 3.2 组件职责

```text
TMDB            规范媒体、季集、播出信息和目标命名
PanSou          聚合搜索夸克/115分享链接，不负责验链
MediaIndex      候选评分、分享验链、文件匹配、改名计划、任务编排、审计
QAS             夸克分享读取、转存、重命名和结果确认
P115 Client     115鉴权、分享读取、服务端转存、目录读写、重命名和移动
MoviePilot      可选：监控最终目录、整理媒体库、生成STRM
```

### 3.3 核心能力协议

```python
class TransferProvider(Protocol):
    key: str
    cloud_type: str

    def configured(self) -> bool: ...
    def capabilities(self) -> set[str]: ...
    def inspect_share(self, share_url: str) -> ShareInspection: ...
    def inspect_save_path(self, path: str) -> SavePathInspection: ...
    def execute(self, plan: TransferPlan) -> ProviderExecutionResult: ...
    def reconcile(self, execution: ProviderExecutionRef) -> ProviderExecutionStatus: ...
```

原生 `p115` 首发必须具备：

```text
share_inspection
selective_transfer
rename_plan
save_path_inspection
execution_reconcile
```

缺少任一核心能力时不得对外标记为“完整 115 provider”。

## 4. 115 认证策略

### 4.1 双认证后端

`P115Client` 的业务接口与认证方式解耦：

```python
class P115AuthBackend(Protocol):
    def authenticated(self) -> bool: ...
    def account(self) -> P115Account: ...
    def request(self, operation: str, payload: dict) -> dict: ...
```

规划两种实现：

1. `open_api`：115 官方开放平台授权，长期优先。
2. `cookie`：兼容模式，用于官方开放能力尚不能覆盖外部分享读取/接收的场景。

用户提出的 Cookie 接入可以实施，但必须在 UI 中明确标记为“兼容模式”，不能承诺永久稳定。

### 4.2 官方 Open API

115 官方开放平台公开描述了文件上传、下载、分享、重命名、移动、删除、播放和信息查询能力，但接入需要开发者认证，具体权限以审核后的应用为准。

正式实现前必须验证：

- 是否允许读取任意合法外部分享的完整目录；
- 是否允许按文件 ID 选择性接收外部分享；
- 接收后是否能可靠返回目标文件 ID；
- 授权刷新、限流和多用户模型。

在这些能力未实测前，不假定 Open API 已覆盖完整转存链路。

### 4.3 Cookie 兼容模式

社区 `p115client` 已暴露 `share_snap`、`share_receive`、目录遍历、重命名、移动等能力，可作为可行性验证参考，但它使用的部分接口并非官方稳定契约。

Cookie 模式要求：

- Cookie 仅在服务端保存，前端永不回显原文；
- 状态接口只返回 `has_p115_cookie`、账号掩码和验证时间；
- 禁止写入日志、异常正文、任务表、通知和 URL；
- 支持立即清除 Cookie 和注销 provider；
- 明确展示失效、设备下线、验证码、风控、限流；
- 不自动高频刷新，不绕过验证；
- 所有变更接口必须设置本地幂等保护。

首发可以采用用户粘贴 Cookie；扫码登录、自动刷新和多账号不进入第一个功能 PR。

### 4.4 凭据存储

最低要求：

- Docker 环境通过 secret 文件或仅服务端 `.env` 注入；
- 配置 API 写入时采用原子替换与最小文件权限；
- 日志统一敏感字段过滤；
- 测试连接不得返回上游响应正文；
- 后续支持应用级加密密钥，避免数据库明文保存。

## 5. 原生 115 执行链路

### 5.1 分享解析与验链

1. 解析分享链接中的 `share_code` 和访问码。
2. 请求分享元信息，区分：有效、过期、取消、需要访问码、风控、未知错误。
3. 分页递归读取目录，生成规范化 `SourceFile`：

```text
provider_file_id
provider_parent_id
name
path
size
is_dir
sha1/pickcode（如接口可用）
```

4. 限制最大目录深度、最大文件数和总分页数，超限进入人工确认。
5. 分享读取失败不能降级为“目录为空”。

### 5.2 文件确认与筛选

复用现有 MediaIndex 匹配器：

- 电影：片名、原名、年份、正片体积、扩展名。
- 剧集/综艺：季度、集数、日期、连续范围、文件名置信度。
- 排除：样片、预告、花絮、字幕包、压缩包和明显错误媒体。

执行前必须持久化分享快照和选择结果；文件 ID 与名称共同参与校验，避免分享内容变化后错转。

### 5.3 改名计划

MediaIndex 在转存前生成 `RenamePair`，用户看到的是计划而不是执行结果：

```text
源文件 -> 目标文件名 -> 目标目录
```

若 115 不能在“接收分享”请求中直接指定新名称，则采用：

1. 转存到 MediaIndex 专用暂存目录；
2. 根据返回 ID 或暂存目录差异定位新文件；
3. 重命名选中文件；
4. 移动到最终分类目录；
5. 清理空暂存目录。

不得在无法唯一定位新文件时进行批量重命名。

### 5.4 转存与幂等

提交前创建持久化执行意图：

```text
provider=p115
share_code
selected_file_ids_hash
target_directory_id
rename_plan_hash
status=provider_submitting
```

幂等规则：

- 同一分享、同一选择、同一目标目录只允许一个活动执行；
- 请求超时后先检查目标目录与暂存目录，不直接重试；
- 能关联文件 ID 时以 ID 为主，文件名和大小为辅助证据；
- 只有目标文件全部存在且名称符合计划时进入 `provider_completed`；
- 部分成功进入 `provider_partial`，保留可恢复上下文。

### 5.5 事务补偿

115 不提供跨“接收、重命名、移动”的数据库事务，因此采用 saga：

1. `receive_started`
2. `receive_confirmed`
3. `rename_started`
4. `rename_confirmed`
5. `move_started`
6. `provider_completed`

失败时不自动删除已接收文件。系统展示残留位置，并提供“继续整理”与“保留现状”；删除操作必须再次确认。

## 6. 搜索与双 Provider 展示

### 6.1 PanSou 请求

根据设置动态生成：

```text
仅启用 QAS       -> cloud_types=quark
仅启用原生 115  -> cloud_types=115
两者均启用       -> cloud_types=quark,115
```

PanSou 的 `conc` 表示频道和插件搜索的内部并发度，不表示每种网盘都有独立线程。默认只发一次多类型搜索，返回后按 provider 拆分结果，避免重复执行全部频道和插件。

### 6.2 发现页状态

只启用一个 provider 时显示一个资源状态；启用两个时显示两个并列状态：

```text
夸克检索中… -> QAS 验链中… -> 已验证 / 待确认 / 未找到
115 检索中… -> 115 分享读取中… -> 已验证 / 待确认 / 未找到
```

两个状态共享 PanSou 搜索阶段，但后续验链独立。手动点击某一项“重新检索”时才发送单 provider 请求。

当前前端的定时文字轮播不算真实进度。需要资源探测任务或短轮询接口返回每个 provider 的实际阶段。

### 6.3 候选规则

- 候选去重键：`(cloud_type, normalized_share_url)`。
- 夸克候选只交给 QAS。
- 115 候选只交给原生 `p115` inspector。
- PanSou 标题相关性只用于排序，不能替代真实文件确认。
- 两个 provider 分别评分、分别缓存、分别展示，不互相覆盖。

## 7. 数据模型与状态

### 7.1 Provider 字段

继续使用已经引入的字段：

```text
candidates.cloud_type
candidates.provider
transfer_jobs.provider
tracking_tasks.provider
tracking_episodes.provider
wishlist.provider
```

新增或扩展：

```text
transfer_jobs.external_job_id
transfer_jobs.external_provider_status
transfer_jobs.provider_context_json
transfer_jobs.execution_key
candidates.provider_snapshot_json
```

`provider_context_json` 只保存非敏感执行上下文，例如分享码、选中文件 ID、暂存目录 ID、目标目录 ID和步骤状态；不得保存 Cookie。

### 7.2 通用状态

| 阶段 | 含义 |
| --- | --- |
| `provider_resolving` | 检查 provider 配置和能力 |
| `share_inspecting` | 读取真实分享文件 |
| `matching_files` | TMDB 文件匹配与筛选 |
| `needs_review` | 需要用户确认文件或改名计划 |
| `provider_submitting` | 正在执行 115 接收 |
| `provider_triggered` | 已接受但尚无充分完成证据 |
| `provider_organizing` | 正在重命名/移动 |
| `provider_partial` | 部分成功，等待恢复 |
| `provider_completed` | 目录证据确认完成 |
| `provider_failed` | 明确失败 |
| `provider_confirmation_timeout` | 超时且无法确认结果 |

历史 `qas_*` 和 `moviepilot_115` 状态保持可读，由展示层映射，不批量破坏历史。

## 8. API 与设置

### 8.1 设置状态

```json
{
  "enabled_providers": ["qas", "p115"],
  "default_provider": "p115",
  "p115_auth_mode": "cookie",
  "has_p115_cookie": true,
  "p115_account_masked": "12***89",
  "p115_last_verified_at": "2026-07-23T10:00:00+08:00"
}
```

### 8.2 设置接口

```text
PUT  /api/config/providers
POST /api/config/test-provider/qas
POST /api/config/test-provider/p115
DELETE /api/config/provider/p115/credential
```

设置页提供：

- 启用 QAS；
- 启用原生 115；
- 默认 provider；
- 115 认证模式；
- Cookie/授权凭据；
- 目标根目录与暂存目录；
- 连接与只读能力测试；
- 清除凭据。

测试连接默认只做账号信息、分享读取能力和目录读取能力测试，不执行真实转存。

### 8.3 资源探测

建议引入：

```text
POST /api/resource-probes
GET  /api/resource-probes/{id}
POST /api/resource-probes/{id}/retry?provider=p115
```

响应按 provider 返回真实阶段：

```json
{
  "providers": {
    "qas": {"stage": "share_inspecting", "message": "夸克分享验链中"},
    "p115": {"stage": "matching_files", "message": "115 文件匹配中"}
  }
}
```

## 9. UI 规划

### 9.1 设置页

“资源来源”与“执行器”合并为清晰的 provider 开关：

- 夸克（QAS）复选框；
- 115（MediaIndex 原生）复选框；
- 至少启用一个网盘 provider；
- 每个启用项必须通过配置校验后才能执行，未配置时仍可保存但显示警告。

MoviePilot 配置移入“可选后处理”折叠区，不再影响 115 转存按钮是否可用。

### 9.2 发现与详情页

- 根据启用数量显示一个或两个资源状态按钮。
- 每个按钮显示真实 provider 阶段和候选数量。
- 115 与夸克都能进入文件确认页。
- 确认页展示真实文件树、默认选择、排除原因和改名预览。
- 用户确认后才执行转存和改名。

### 9.3 历史与恢复

- 显示 provider、认证模式、执行步骤和目标目录。
- `provider_partial` 展示“继续整理”，不自动重复转存。
- 账号失效时历史仍可读，执行按钮提示重新认证。
- 改投另一个 provider 必须创建新执行记录。

## 10. MoviePilot 的新定位

MoviePilot 变为可选集成：

1. MediaIndex 将媒体转存并规范命名到 115 最终目录。
2. 用户的 MoviePilot 插件自行监控该目录。
3. MoviePilot 负责其自身的 STRM、媒体库与播放链路。

MediaIndex 不要求 MoviePilot API 地址或 Token 才能使用 115。已有 `MoviePilot115Client` 可以保留为实验/兼容模块，但默认 UI 不启用，后续单独决定是否保留“提交给 MoviePilot”快捷方式。

## 11. 安全与合规

1. 优先推进官方开放平台认证；Cookie 私有接口明确标记兼容风险。
2. 不记录 Cookie、访问令牌、完整账号、上游原始错误正文。
3. 仅允许向预定义的 115 官方域名发请求，禁止凭据随重定向发送。
4. 查询可有限退避重试；转存、重命名、移动不得盲目自动重试。
5. 限制分享递归深度、分页、文件数量和单次选择数量。
6. 所有破坏性操作使用精确文件 ID；不使用名称通配符删除或移动。
7. 风控、验证码、账号下线进入明确状态并停止自动任务。
8. 使用者应遵守 115 服务协议、分享规则和适用法律法规。

## 12. 测试与验收

### 12.1 契约测试

使用 fake server 固化：

- Cookie 有效、过期、账号下线、验证码和限流；
- 分享有效、过期、取消、访问码错误；
- 多层目录、分页、空目录、同名文件、分享变更；
- 选择性接收成功、部分成功、超时和重复提交；
- 重命名冲突、移动失败、恢复执行；
- 目标目录完成确认。

### 12.2 单元测试

- 分享 URL/访问码解析与脱敏；
- 115 文件到 `SourceFile` 的标准化；
- 电影、剧集、综艺匹配和改名计划；
- 幂等键、saga 步骤与部分成功恢复；
- provider 状态映射和历史兼容；
- 双 provider 搜索、缓存和 UI 状态。

### 12.3 验收门槛

在真实测试账号上至少完成：

1. 读取一个多层电影分享并只选择正片；
2. 读取一个多季度剧集分享并准确选择目标季度/集数；
3. 转存到暂存目录、重命名、移动到最终目录；
4. 人为制造超时后不重复转存；
5. 人为制造重名冲突后进入可恢复状态；
6. Cookie 失效后不泄漏凭据且自动任务停止。

未完成真实账号契约验证前，不开放自动追更。

## 13. 新 PR 拆分

### 已完成且继续复用

#### PR 1：Provider 基础模型与兼容迁移

- provider 字段、旧数据迁移和通用状态继续有效。
- QAS provider 门面继续有效。

#### PR 2：PanSou 多网盘搜索与候选标记

- `quark,115` 搜索、候选网盘标记和去重继续有效。
- 115 候选 provider 将从 `moviepilot_115` 迁移为 `p115`。

### 需要调整

#### 原 PR 3：MoviePilot 客户端与设置

- 不再作为原生 115 的前置依赖。
- 已有代码保留为可选实验适配器，不继续扩展核心业务。
- MoviePilot 设置后续移到“可选后处理”。

#### 当前未提交 PR 4

- “确认后提交 MoviePilot”方案停止作为主路径。
- provider 选择、通用状态、历史字段和部分 UI 可复用。
- 提交执行部分在原生 115 client 完成前不得合并为正式 115 功能。

### 新实施顺序

#### PR 3A：115 能力验证 Spike（不开放 UI）

- 用隔离测试账号验证分享读取、分页、选择性接收、目录读取、重命名和移动。
- 对比官方 Open API 与 Cookie 模式能力。
- 形成脱敏契约样本和 fake server。
- 任何核心能力不成立则停止后续开发并更新本 PRD。

#### PR 3B：原生 P115 Client 与凭据安全

- 新增认证后端、Cookie 兼容模式、连接测试和错误分类。
- 凭据脱敏、清除、域名限制、重定向限制和限流退避。
- 不执行转存，不开放发现页 115 执行。

#### PR 4：115 分享读取、确认与改名计划

- 原生读取 115 分享文件树。
- 接入现有电影/剧集匹配器。
- 文件选择与改名预览 UI。
- 仍不执行真实转存。

#### PR 5：单次选择性转存与整理

- 暂存目录、选择性接收、重命名、移动和结果确认。
- 幂等意图、saga、部分成功与继续整理。
- 单次任务正式开放。

#### PR 6：双 Provider 资源探测 UI

- 设置页 provider 复选框。
- 一个/两个实时资源状态按钮。
- 共享 PanSou 搜索、独立 provider 验链和单项重试。

#### PR 7：愿望单与智能追更

- 仅在真实账号验收通过后启用。
- provider 固化、凭据失效暂停、风控退避和通知。

#### PR 8：可选 MoviePilot/STRM 后处理与文档

- 明确不作为转存依赖。
- 若保留集成，只传递已完成的目标目录或由 MoviePilot 自行监控。
- 完成 README、部署示例、安全说明和迁移文档。

## 14. 现有代码迁移原则

1. 不回滚 PR 1/PR 2 的通用模型。
2. 新增 `ProviderKey.P115 = "p115"`。
3. 新产生的 115 候选映射为 `p115`。
4. 已持久化的 `moviepilot_115` 历史任务保持原值；未执行候选可在显式数据库迁移中改为 `p115`。
5. `MoviePilot115TransferProvider` 不注册为默认 115 provider。
6. 当前 PR4 的真实提交入口在原生执行器完成前保持关闭。
7. 设置默认值仍为 `qas`，升级不自动启用 115。

## 15. 开发前阻断项

以下问题必须由 PR 3A 回答：

1. Cookie 模式读取外部分享是否稳定支持访问码、分页和多层目录？
2. 能否按文件 ID 选择性接收，而不是只能接收整个分享？
3. 接收响应能否返回新文件 ID；不能时如何唯一关联？
4. 重名、部分成功和超时后的实际行为是什么？
5. 官方 Open API 是否允许外部分享读取和接收？
6. Cookie 的设备类型、失效条件和账号下线影响是什么？
7. 最低安全请求频率和并发上限是什么？

任何阻断项没有可靠答案时，不进入自动追更开发。

## 16. 发布与回滚

- 原生 115 默认关闭，用户显式启用并通过只读测试后才可使用。
- 首个版本默认只开放单次人工确认任务。
- 凭据失效时停止新执行，不影响历史查询。
- 关闭 `p115` 不删除任务、候选或执行上下文。
- 回滚代码不得删除已经转存到 115 的文件。
- 数据库新增字段保持向前兼容。

## 17. 成功指标

1. 115 候选能够读取真实文件，而不是只依赖 PanSou 标题。
2. 用户能在执行前看到并修改文件选择和改名计划。
3. 单次转存在超时和重试场景下不产生重复副本。
4. 转存、重命名、移动完成后有可验证目录证据。
5. 未部署 MoviePilot 的用户可以完成完整核心流程。
6. 只使用 QAS 的旧用户行为与升级前一致。

## 18. 参考资料

- 115 开放平台：<https://open.115.com/>
- 115 开放平台开发者服务协议：官方平台页面
- 115 分享与转存说明：<https://115.com/115115/T479428.html>
- PanSou：<https://github.com/fish2018/pansou>
- p115client（Cookie/Open API 能力验证参考）：<https://github.com/ChenyangGao/p115client>
