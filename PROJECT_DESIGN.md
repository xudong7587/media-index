# Media Index 重写设计稿

## 设计定位

Media Index 不是单纯的前端页面，而是一个部署在 NAS 内网里的媒体自动化控制台。

它负责把 TMDB、PanSou 和 QAS 串成一个稳定流程：

1. 从 TMDB 发现和识别影视内容。
2. 用 PanSou 搜索最新夸克分享资源。
3. 用 QAS 验证分享链接和读取文件列表。
4. 根据 TMDB 集数信息匹配真实视频文件。
5. 调用 QAS 完成转存、重命名和后续 STRM 生成。
6. 对连载内容做保守追更、重试和人工介入提醒。

核心原则：前端只做展示、选择和确认；所有密钥、路径、调度、匹配、转存决策都在服务端完成。

README 维护要求：任何版本更新或 README 重写都必须保留两项核心说明：第一，项目最大特点是智能追更——媒体更新时根据 TMDB 信息重新确定目标集、重新搜索来源、匹配文件并标准化命名；第二，必须保留醒目的版权与第三方资源免责声明，不得弱化为普通的一句话提示。

## 产品模式

### 单次转存

用户在发现页或搜索页进入影视详情，选择：

- 存网盘：调用 QAS 转存到网盘路径，由 QAS 及其插件完成 STRM 生成等后续动作。
- 存本地：转存到服务端配置的本地目标路径，其他工具如何处理该目录不属于本项目范围。
- 加入愿望单：按 TMDB 上映/播出日期自动检查，默认 09:00；卡片可修改检查时间或立即搜索。

### 智能追更

用户对连载剧集或综艺点击追更后，系统保存一条追更任务。

后端定时根据 TMDB 的播出信息决定何时搜索，而不是依赖固定夸克分享链接。每次执行时：

1. 查询 TMDB 当前季和已播集。
2. 找出还没成功转存的目标集。
3. 用片名、原名、年份、季号、集号组合搜索 PanSou。
4. 验证候选夸克链接。
5. 匹配文件名。
6. 高置信匹配自动转存。
7. 模糊匹配进入待确认。
8. 连续失败达到阈值后暂停该集自动重试，并提示人工介入。

## 自动与人工边界

默认策略：

- 高置信匹配：自动转存。
- 模糊匹配：进入待确认队列。
- 年份冲突：禁止自动转存。
- 多个候选质量接近：优先展示给用户确认。
- 分享失效：自动换源搜索。
- 连续失败 5 次：停止该集重试并提示。

高置信匹配包括：

- 明确集号命中，如 `S01E08`、`E08`、`08` 且边界安全。
- 中文期数命中，如“第8期上”，且没有“纯享”“花絮”“预告”等排除词。
- 文件年份与 TMDB 年份不冲突。

模糊匹配包括：

- 只命中 TMDB 描述片段。
- 文件名没有明确集号但疑似目标集。
- 同一集匹配多个文件且质量选择不确定。

## 路径设计

路径允许用户配置，但必须受服务端白名单控制。最终路径只能由后端拼接，不能采用前端、历史 QAS 任务或搜索结果携带的保存路径。

服务端配置保存路径根：

- 网盘根路径，例如 `/strm`
- 本地根路径，例如 `/下载_未整理`

前端允许用户选择：

- 保存目标：网盘或本地
- 媒体分类：电影、剧集、综艺
- 分类子目录，例如电影 `/movie`、剧集和综艺 `/tv`

前端不允许传入任意绝对路径。服务端最终生成路径：

- 电影：`{root}/movie/{title}({year})`
- 剧集：`{root}/tv/{title}({year})`
- 综艺：`{root}/tv/{title}({year})`

其中 `{root}` 按保存目标确定：网盘固定取配置的 `/strm`，本地固定取配置的 `/下载_未整理`。因此 `/tv` 只表示分类子目录，绝不是最终保存根目录。任何缺少已配置根目录的执行路径都必须在调用 QAS 前被拒绝。

后续可增加高级模式，但需要明确开关和路径前缀校验。

## 系统架构

推荐技术栈：

- 后端：FastAPI
- 数据库：SQLite
- 定时任务：APScheduler
- 前端：React + TypeScript + Vite
- 样式：Tailwind CSS + CSS variables
- UI 基础：Radix primitives 或轻量自建组件
- 图标：Phosphor Icons 或 Tabler Icons
- 部署：Docker Compose

Taste Skill 适用方式：

本项目属于工具型产品 UI，不是营销落地页。因此采用 Taste Skill 的审美约束，而不套用它的营销页结构：

- 默认浅色主题。
- 支持深浅色切换。
- 避免 AI 紫色渐变、玻璃拟态堆叠、三等分卡片。
- 信息密度中等偏高，但保留呼吸感。
- 海报和任务状态是主视觉，不做装饰性假图。
- 所有加载、空状态、错误状态、待确认状态都要完整设计。

设计读法：

Reading this as: a local NAS media automation console for one power user, with a clean media-library and operations-dashboard language, leaning toward light-first Tailwind UI with restrained motion.

设计拨盘：

- DESIGN_VARIANCE: 5
- MOTION_INTENSITY: 3
- VISUAL_DENSITY: 7

## 后端模块

### auth

职责：

- 登录、登出、会话校验
- Cookie 使用 `HttpOnly`
- 支持登录失败限速
- 默认只绑定内网

禁止：

- 把 Token 放入 localStorage
- 把 `.env` 或配置文件暴露到静态路由

### config

职责：

- 读取服务端环境变量
- 管理可编辑配置
- 提供健康检查

敏感字段：

- TMDB API Key
- QAS Token
- PanSou Token
- 登录密码

这些字段只允许服务端保存和使用。前端只能看到“已配置/未配置”。

### tmdb_client

职责：

- 搜索电影、剧集、综艺
- 获取详情、季列表、集列表
- 获取热播和发现页数据
- 归一化 TMDB 结果

关键字段：

- `tmdb_id`
- `media_type`
- `title`
- `original_title`
- `year`
- `status`
- `season_number`
- `episode_number`
- `air_date`
- `match_tokens`
- `desc_hint`

### pansou_client

职责：

- 调用 PanSou 搜索 API
- 支持未认证和 JWT 认证两种模式
- 只返回夸克资源
- 归一化候选链接
- 缓存短期搜索结果

默认请求：

- `POST /api/search`
- `kw`
- `cloud_types: ["quark"]`
- `res: "merge"`
- 必要时带 `Authorization: Bearer <token>`

### qas_client

职责：

- 读取 QAS 任务列表
- 创建或更新 QAS 任务
- 验证夸克分享详情
- 设置 pattern 和 replace
- 触发立即运行
- 清理临时 runweek
- 回滚失败操作

QAS 是执行器，不是主状态中心。

### matcher

职责：

- 过滤非正片文件
- 集号匹配
- 中文期数匹配
- 描述片段模糊匹配
- 年份校验
- 质量选择
- 生成 QAS pattern 和 replace

质量选择规则：

- 优先主视频格式：`.mkv`、`.mp4`、`.ts`、`.m2ts`、`.iso`
- 优先 `2160p/4K`、`1080p`
- 大体积 4K 可降权，避免误选超大合集
- 排除预告、花絮、纯享、OST、音频、游戏、补丁等

### transfer_service

职责：

- 单次转存电影、剧集、综艺
- 创建或复用 QAS 任务
- 调用 matcher
- 执行 QAS
- 记录转存日志
- 成功后可自动加入追更

### tracking_service

职责：

- 管理追更任务
- 计算目标集
- 管理重试状态
- 判断待确认状态
- 判断完结或季终
- 保存每集转存结果

### scheduler

职责：

- 保守触发追更任务
- 支持手动立即运行
- 防止同一任务并发执行
- 限制整体频率，避免触发账号风控

默认调度策略：

- 播出日后 1 小时开始检查。
- 播出日当天每小时最多检查一次。
- 非播出日低频检查或不检查。
- 单集连续失败 5 次后进入人工介入状态。

## 数据库草案

### media

- `id`
- `tmdb_id`
- `media_type`
- `title`
- `original_title`
- `year`
- `poster_url`
- `backdrop_url`
- `overview`
- `status`
- `created_at`
- `updated_at`

### tracking_tasks

- `id`
- `tmdb_id`
- `media_type`
- `title`
- `year`
- `season_number`
- `save_target`
- `save_root`
- `save_path`
- `status`: active, paused, completed, needs_review, error
- `last_checked_at`
- `next_check_at`
- `created_at`
- `updated_at`

### tracking_episodes

- `id`
- `task_id`
- `season_number`
- `episode_number`
- `air_date`
- `title`
- `status`: pending, saved, failed, needs_review, skipped
- `matched_file`
- `share_url`
- `save_path`
- `retry_count`
- `last_error`
- `saved_at`

### transfer_jobs

- `id`
- `media_id`
- `task_id`
- `target`
- `status`
- `stage`
- `message`
- `share_url`
- `source_file`
- `renamed_file`
- `save_path`
- `created_at`
- `finished_at`

### candidates

- `id`
- `job_id`
- `share_url`
- `source_title`
- `file_count`
- `files_json`
- `score`
- `match_stage`
- `is_fuzzy`
- `created_at`

### wishlist

- `id`
- `tmdb_id`
- `media_type`
- `title`
- `year`
- `poster_url`
- `overview`
- `status`
- `created_at`

### settings

- `key`
- `value`
- `is_secret`
- `updated_at`

## API 草案

### 认证

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

### 配置

- `GET /api/config/status`
- `PUT /api/config`
- `POST /api/config/test/tmdb`
- `POST /api/config/test/pansou`
- `POST /api/config/test/qas`

### 发现与详情

- `GET /api/discover`
- `GET /api/search`
- `GET /api/media/{media_type}/{tmdb_id}`
- `GET /api/media/{media_type}/{tmdb_id}/seasons/{season_number}`

### 转存

- `POST /api/transfers`
- `GET /api/transfers`
- `GET /api/transfers/{id}`
- `POST /api/transfers/{id}/confirm`
- `POST /api/transfers/{id}/retry`

### 追更

- `GET /api/tracking`
- `POST /api/tracking`
- `GET /api/tracking/{id}`
- `PATCH /api/tracking/{id}`
- `DELETE /api/tracking/{id}`
- `POST /api/tracking/{id}/run`
- `POST /api/tracking/{id}/pause`
- `POST /api/tracking/{id}/resume`

### 待确认

- `GET /api/review`
- `POST /api/review/{candidate_id}/approve`
- `POST /api/review/{candidate_id}/reject`

### 日志

- `GET /api/logs`
- `GET /api/logs/{job_id}`

## 前端信息架构

### 发现

第一屏就是可用的海报流，不做营销页。

功能：

- 搜索框
- 类型切换：电影、剧集、综艺
- 地区或语言筛选
- 海报瀑布/网格
- 每张海报显示标题、年份、评分、可用状态

状态：

- 加载骨架
- 空结果
- TMDB 未配置
- 网络错误

### 媒体详情

功能：

- 海报、背景图、简介
- 季选择
- 已播集摘要
- 存网盘
- 存本地
- 加入愿望单
- 开启追更
- 查看候选资源

### 追更

功能：

- 活跃任务
- 待确认任务
- 失败任务
- 已暂停任务
- 已完结任务

每条任务显示：

- 海报
- 当前季
- 已保存集数
- 最新目标集
- 下次检查时间
- 最近错误
- 手动运行、暂停、恢复、删除

### 待确认

功能：

- 展示模糊匹配文件
- 展示 TMDB 目标集
- 展示候选分享源
- 用户批准或拒绝

### 日志

功能：

- 按任务、媒体、状态过滤
- 展示每次执行阶段
- 展示失败原因
- 可复制调试信息，但默认隐藏密钥

### 设置

功能：

- TMDB 配置状态
- QAS 地址和 Token
- PanSou 地址、认证模式、账号或 Token
- 网盘保存根路径
- 本地保存根路径
- 调度策略
- 深浅色偏好

敏感字段保存后不回显。

## 主题与视觉

默认浅色。

主题：

- Light 默认
- Dark 可切换
- 跟随系统可选

浅色建议：

- 背景：柔和白灰
- 主文本：近黑
- 辅助文本：中性灰
- 强调色：琥珀或蓝绿二选一，整站一致
- 卡片圆角：8px
- 按钮圆角：10px 或 pill，但全站一致

视觉重点：

- 海报是真实视觉资产。
- 任务状态用清晰的标签和细线分组。
- 不使用大面积紫色渐变。
- 不做装饰性假屏幕。
- 不滥用卡片套卡片。

## 安全边界

### 必须修复

- 静态文件路径穿越。
- `.env` 泄露风险。
- Docker Compose 污染。
- 前端 localStorage 保存 Token。
- 任意 QAS URL 和任意路径由浏览器传入。

### 密钥处理

- 不在前端返回真实密钥。
- 不在日志中打印 Token。
- 不把 `.env` 放入静态目录。
- 不把备份 zip 暴露到 Web 服务目录。

### SSH 与 NAS 操作

不建议在聊天中直接发送 NAS 用户名和密码。

推荐方式：

1. 使用 SSH key。
2. 你在 NAS 上创建临时低权限部署用户。
3. 只授权该用户访问项目目录和 Docker 命令。
4. 密码或私钥通过本机安全凭据管理，不直接写进聊天记录。
5. 如果必须使用密码，由你在本机终端执行一次登录命令，我只给命令和步骤。

更稳妥的开发流程：

1. 我先在当前 `Z:\docker\media-index` 工作区完成代码重写。
2. 生成新的 `docker-compose.yml` 和 `.env.example`。
3. 你确认配置后，在 NAS 上拉起容器。
4. 需要我远程协助时，再用临时 SSH key 授权。

## 迁移策略

当前版本不直接覆盖。

阶段一：清理与设计

- 保留现有 zip 存档。
- 生成本设计文档。
- 确认技术栈和交互。

阶段二：新项目骨架

- 建立 `backend/`
- 建立 `frontend/`
- 建立 `docker/`
- 建立 `.env.example`
- 修复 Compose

阶段三：后端核心

- 配置管理
- TMDB 客户端
- PanSou 客户端
- QAS 客户端
- matcher
- SQLite migration

阶段四：追更状态机

- 单次转存
- 自动追更
- 待确认
- 失败重试
- 日志

阶段五：前端

- 浅色主题
- 海报流
- 媒体详情
- 追更控制台
- 待确认
- 设置

阶段六：部署验证

- 本地构建
- 容器构建
- NAS 路径挂载
- QAS 联调
- PanSou 联调
- 手动转存测试
- 追更 dry-run 测试

## 待确认问题

1. PanSou 是否开启了认证。如果开启，需要配置用户名密码或固定 Token。
2. QAS 是否只在内网可访问。
3. “存网盘”和“存本地”的根路径最终分别是什么。
4. 是否需要通知渠道，例如企业微信、Telegram、邮件。
5. 是否需要 Emby/Jellyfin 刷新状态在本项目内展示，还是完全交给 QAS 插件。

