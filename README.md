<p align="center"><img src="frontend/public/assets/media-index-icon.png" alt="MediaIndex" width="150" /></p>

# MediaIndex

面向个人 NAS 的影视发现、多网盘转存、愿望单、智能追更、OpenList 自动同步和通知交互控制台。

[![GHCR](https://img.shields.io/badge/GHCR-media--index-2f8f8c?style=flat-square)](https://github.com/xudong7587/media-index/pkgs/container/media-index)
![Version](https://img.shields.io/badge/version-0.6.0--rc.3-6d7cff?style=flat-square)
![Docker](https://img.shields.io/badge/deploy-Docker-2496ed?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-111827?style=flat-square)

当前版本：**0.6.0-rc.3**

📖 **[完整使用手册](docs/USAGE.md)** · 🐳 **[Docker Compose 部署](docker-compose.yaml)** · 🛠️ **[变更记录](CHANGELOG.md)** · 🧭 **[路线图](docs/ROADMAP.md)**

MediaIndex 的核心目标不是收藏一个很快失效的分享链接，而是把“发现资源、验证文件、标准命名、转存、追更、同步和通知确认”串成一条可回溯的自动化链路。它会从 TMDB 获取媒体与播出信息，通过 PanSou 搜索候选，再交给 QAS（夸克）或原生 115 Provider 读取真实文件、转存和重命名。遇到证据不足的候选时，系统不会冒进自动执行，而是进入待确认，让你在网页、企业微信或 Telegram 中选择。

作者是编程门外汉，代码 AI 比例 100%。项目会持续做分层测试和对抗性审查，但这不代表不存在缺陷；如发现问题，欢迎在 Issues 中提供已脱敏的复现信息。

本项目不提供媒体资源、分享链接、网盘账号或 Cookie。部署者应自行确保第三方服务和资源的合法使用。

## 重点能力

- **原生 115 支持**：MediaIndex 直接读取 115 分享、匹配文件、转存、改名、移动并确认目标目录，不要求 MoviePilot 执行转存。
- **QAS 夸克转存**：复用 quark-auto-save 的夸克能力，执行前会读取分享真实文件并生成安全命名计划。
- **多网盘并行**：发现页可同时验证夸克和 115；一个网盘失败不会回滚另一个网盘的成功结果。
- **智能追更**：调度和卡片展开时会先刷新 TMDB 分集信息，再读取目标网盘目录真实状态，只从最后已存集的下一集开始找资源；目录为空时才做初始全量处理。资源尚未更新会静默重试，只有真实文件歧义才进入待确认。
- **按集转存、补集与同步**：发现页可按季展开检索到的剧集并选择部分转存；智能追更卡片支持同步所选、同步所有、补齐所选和补齐所有，也可粘贴已有夸克或 115 分享链接，只补所选集。
- **文件级安全校验**：PanSou 负责返回候选，MediaIndex 再读取分享中的真实文件核对名称、年份、季集和播出日期；综艺支持按日期、期数和分段识别跨日发布内容，不改变 PanSou 的查询和候选排序。
- **可追踪的运行反馈**：顶部运行日志按钮会打开可关闭的居中弹窗，显示任务阶段、执行消息、目标路径和时间；设置页使用固定在右下角的圆形保存按钮。
- **OpenList 事件驱动同步**：转存确认完成后才触发同步，不做固定周期全库扫描。自动同步可设为夸克 → 115、115 → 夸克或双向；目标媒体目录不存在时可整目录复制，已存在时只提交缺失文件；同名文件跳过，相同运行中任务不会重复触发。
- **通知与手机端交互**：支持企业微信自建应用、企微机器人和 Telegram；企业微信和 Telegram 共用资源搜索、链接转存、编号确认与状态指令，Telegram 额外支持按钮交互。
- **交互链接转存**：企业微信或 Telegram 中发送夸克/115 分享链接可直接转存；115 可接收磁力、ed2k 和普通 HTTP/HTTPS 离线下载。
- **路径和命名规则**：夸克、115 分开配置保存根目录和分类路径，支持按季目录、媒体文件夹命名、电影命名和剧集命名规则。

## 依赖服务

必需：

- [TMDB API Key](https://www.themoviedb.org/settings/api)
- [fish2018/pansou](https://github.com/fish2018/pansou)

至少启用一个网盘 Provider：

- [Cp0204/quark-auto-save（QAS）](https://github.com/Cp0204/quark-auto-save)：用于夸克分享读取、转存和改名。
- 原生 115：填写包含 `UID`、`CID`、`SEID` 的 115 Cookie 后可用。

可选：

- OpenList：用于已挂载夸克媒体库和 115 媒体库之间的文件同步。
- Telegram 或企业微信：用于外部通知、移动端确认和下载链接交互。
- MoviePilot：只作为可选的 115 Cookie 导入源，不是 115 转存依赖。

## 快速部署

仓库根目录提供可直接运行的 [`docker-compose.yaml`](docker-compose.yaml)。它默认只启动 MediaIndex，同时预留了 PanSou 和 QAS 服务配置。

```bash
mkdir media-index
cd media-index
curl -LO https://raw.githubusercontent.com/xudong7587/media-index/main/docker-compose.yaml
```

打开 `docker-compose.yaml`，至少修改：

```yaml
services:
  media-index:
    image: ghcr.io/xudong7587/media-index:latest
    pull_policy: always
    container_name: media-index
    ports:
      - "38000:8000"
    environment:
      MEDIA_USER: admin
      MEDIA_PASS: 请改成高强度密码
      MEDIA_CONFIG_PATH: /app/data/.env
      STATIC_DIR: /app/frontend
      DB_PATH: /app/data/media_index.db
      CACHE_DIR: /app/data/cache
    volumes:
      - ./data:/app/data
      - ./downloads:/downloads
    restart: unless-stopped
```

启动：

```bash
docker compose up -d
```

访问 `http://你的NAS地址:38000`。首次登录后进入 **设置** 完成服务连接。

如果希望同一套 Compose 一起启动 PanSou 和 QAS，删除 `docker-compose.yaml` 中对应服务每行开头的 `# `，修改 QAS 管理密码后重新执行：

```bash
docker compose up -d
```

应用会拒绝空密码以及密码 `admin`。请不要直接使用示例密码。

## 首次配置顺序

1. **通用服务**：填写 TMDB API Key、PanSou 地址，必要时配置代理，并使用测试按钮确认连通。
2. **夸克 QAS**：在 QAS 中配置夸克 Cookie，复制 API Token 到 MediaIndex，保存后测试连接。
3. **115**：粘贴 Cookie，或从 OpenList 导入 115 Cookie / 115 Open 凭据；填写 115 保存根目录、暂存目录和本地下载目录。
4. **分类路径**：分别配置夸克和 115 的电影、剧集、综艺等分类路径。目录选择使用 QAS、115 原生凭据；115 Open 直连不可用时会通过 OpenList 的对应存储读取目录。
5. **命名与分季**：设置媒体文件夹、季文件夹、电影文件和剧集文件命名规则。
6. **OpenList 同步**：如需两边媒体库自动补齐，填写 OpenList 地址、Token、夸克媒体库目录和 115 媒体库目录，并选择自动同步方向。115 作为主媒体库时建议使用“夸克 → 115”。
7. **通知和交互**：配置企业微信、企微机器人或 Telegram；交互指令由企业微信自建应用和 Telegram 共用，可同时勾选夸克与 115。启用下载链接自动转存后，分享链接按自身类型选择网盘；115 分享链接需要 Cookie，磁力、ed2k、HTTP/HTTPS 可使用 115 Open，并在需要时通过 OpenList 提交。
8. **配置导入导出**：导出 JSON 会包含业务设置、网盘凭据和目录、智能追更及愿望单任务；文件含敏感凭据，须妥善保存。

完整截图级步骤、字段解释和常见问题见 [`docs/USAGE.md`](docs/USAGE.md)。

设置页修改任一分区后，点击屏幕右下角固定的圆形保存按钮提交当前分区；顶部栏不再固定整行保存区域。

## 智能追更逻辑

智能追更每次运行都会读取网盘目录中的真实文件状态：

- 如果目录里已有媒体文件，只从最后一集的下一集开始找资源。
- 如果当前目录一集都没有，才寻找所有已播资源做初始补齐。
- 历史缺集不会在日常追更中自动回头补，必须由用户手动勾选补集。
- 调度和展开卡片时会刷新 TMDB 分集元数据；新增加的已播集会自动加入列表并唤醒休眠任务。
- 分集下拉使用 `E26`、`E27` 这类标签；TMDB 分集会先显示，不等待 115 目录读取完成。
- 刷新按钮会重新读取 QAS 或 115 的实际目录，不把历史记录当成最终状态。
- 资源源尚未更新时，任务会等待稍后重试，不制造无效转存或反复发送待确认通知。
- 只有候选文件存在真实歧义、需要用户判断时才进入待确认。
- TMDB 更新日期到达设定的追更时间后开始巡检；失败或资源尚未更新时按巡检页设置的间隔继续检查。

这一逻辑适合连载剧、综艺和多网盘长期维护，避免每次追更都重新扫旧资源。

## OpenList 自动同步

OpenList 只负责已挂载媒体库之间的文件复制，不替代 QAS 或 115 原生转存。

开启后，MediaIndex 只会在这些明确的时机尝试按媒体目录同步：

- 双网盘批量转存完成后。
- 智能追更某一边补到新集后。
- 用户在智能追更卡片中点击同步。
- 用户在 OpenList 手动同步页面发起同步。

同步会先刷新并读取两边目录，并沿用各网盘设置的根目录、分类目录、媒体目录和 Season 路径。目标媒体目录尚不存在时，MediaIndex 会直接复制已经改好名的媒体或 Season 文件夹；目标目录已存在时，只提交缺失文件并跳过同名文件。自动同步方向可以设为夸克 → 115、115 → 夸克或双向；该方向只约束链接转存、发现卡片、愿望单巡检和智能追更触发的自动复制，手动同步及追更卡片中的手动补齐不受限制。相同目录已有同步任务在运行时不会重复提交。MediaIndex 通过 OpenList 的文件复制接口发起操作，具体跨存储能力及任务保留时间由 OpenList 和对应存储驱动决定。自动同步只由业务事件触发，不做固定周期全库扫描。

## 通知与离线下载

通知设置支持企业微信自建应用、企业微信群机器人和 Telegram。企业微信自建应用启用回调后可接收指令；Telegram 启用 Bot 并配置允许的 Chat ID 后，也使用同一套指令和编号选择逻辑。群机器人仅负责推送。

| 消息或指令 | 功能 |
| --- | --- |
| `资源名` | 搜索影视并默认保存到网盘，多个匹配时回复编号选择 |
| `本地 资源名` | 搜索影视并保存到本地 |
| `分享链接` | 夸克或 115 分享链接直接转存到默认路径 |
| `磁力链接` | 固定提交到 115 离线下载，使用交互默认下载目录；裸链接不带媒体分类与季信息 |
| `/review` | 查看待确认任务 |
| `/status` | 查看追更、愿望单、待确认和未读通知数量 |
| `/tracking` | 查看最近智能追更任务 |
| `/wishlist` | 查看最近愿望单任务 |
| `/notifications` | 查看最近通知 |
| `/cancel` | 取消当前等待中的编号选择 |

下载链接自动转存位于 **设置 → 通知和交互 → 交互指令**。可同时选择参与资源搜索的夸克和 115；分享链接按链接类型使用对应网盘，磁力、ed2k 和普通 HTTP/HTTPS 下载固定使用 115 离线下载：

- 夸克：通过 QAS Token 读取目录。
- 115：通过 115 Cookie 读取目录。

支持：

- 夸克分享链接直转。
- 115 分享链接直转。
- 115 磁力、ed2k、HTTP/HTTPS 离线下载。

115 离线下载提交后会短轮询任务状态：已秒存会返回“115 云下载完成”，失败会返回 115 的具体原因，仍在处理时才提示已提交/处理中；长时间进度以 115 客户端或网页端的离线下载任务列表为准。

## 保存规则

最终保存路径始终由后端生成，前端和搜索结果不能传入任意保存路径。

默认路径示例：

- 电影：`{根路径}/{电影分类}/{媒体文件夹}`
- 剧集：`{根路径}/{剧集分类}/{媒体文件夹}`
- 综艺：`{根路径}/{综艺分类}/{媒体文件夹}`
- 开启按季目录后：`{根路径}/{分类}/{媒体文件夹}/{季文件夹}`

默认命名示例：

- 电影文件：`媒体名.年份.mkv`
- 剧集文件：`媒体名.年份.S01E01.mkv`
- 连续合集：`媒体名.年份.S01E01-E02.mkv`

## 更新、备份和恢复

更新：

```bash
docker compose pull
docker compose up -d
```

备份时只需停止容器并备份：

- `./data`：MediaIndex 配置、数据库和缓存。
- `./downloads`：如果使用 115 本地下载。
- QAS 配置目录：如果同 Compose 部署 QAS。

恢复时把备份目录和 `docker-compose.yaml` 放回同一部署目录后重新启动即可。

仓库 Compose 默认跟随 `latest`。如需锁定版本或回退，请从 [GitHub Releases](https://github.com/xudong7587/media-index/releases) 选择对应镜像标签。

## 本地构建与测试

```bash
docker build -t media-index:local .
PYTHONPATH=backend python -m pytest tests
cd frontend && pnpm build
```

前端开发：

```bash
cd frontend
pnpm install
pnpm dev
```

访问 `http://localhost:5173`。Vite 会将 `/api` 请求代理到 `http://127.0.0.1:8000`。

## 安全建议

- 建议仅在内网、VPN 或可信 HTTPS 反向代理后使用。
- 公网 HTTPS 部署时设置 `COOKIE_SECURE=true`。
- QAS Token、115 Cookie、OpenList Token、TMDB Key、通知凭据和登录密码都应按敏感信息保管。
- 不要将数据卷、数据库或自动生成的配置文件公开。
- 发布前可运行 `git grep` 检查仓库中是否混入真实密钥。

## 免责声明

本项目仅提供个人学习、技术研究和自托管自动化所需的软件代码。项目本身不制作、不存储、不托管、不上传、不下载、不分发、不销售，也不内置或提供任何影视资源、网盘分享链接、提取码、账号、Cookie、破解工具或规避版权保护的能力。

TMDB、PanSou、QAS、网盘服务以及搜索结果均属于独立第三方服务或用户自行部署的服务，MediaIndex 不控制、不审核，也不保证其内容来源、版权状态、准确性、安全性、持续可用性或合法性。搜索、匹配、转存、重命名和 STRM 生成等操作均由部署者使用自己的账号、Cookie、Token 和第三方服务主动配置并触发。

使用者必须确保自己对相关内容拥有合法访问、复制、转存和使用权，并遵守所在地法律法规、著作权规定、网盘及第三方服务条款。禁止将本项目用于盗版传播、未经授权分享、商业侵权或任何违法用途。因部署或使用本项目引起的版权纠纷、账号封禁、数据丢失、隐私泄露、服务费用或其他直接、间接损失，均由使用者自行承担。完整条款见 [DISCLAIMER.md](DISCLAIMER.md)。
