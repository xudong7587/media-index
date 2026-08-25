<p align="center"><img src="frontend/public/assets/media-index-icon.png" alt="MediaIndex" width="150" /></p>

# MediaIndex

MediaIndex 是面向个人 NAS 的**自托管网盘媒体自动化中心**：以 TMDB 与 PanSou 完成发现和资源核对，原生连接夸克与 115，并把云端转存、分类命名、高效 STRM/302、Emby 入库与安全联动删除、智能追更、愿望单和图文通知串成一条可查看、可追溯、可控制的完整流程。

[![GHCR](https://img.shields.io/badge/GHCR-media--index-2f8f8c?style=flat-square)](https://github.com/xudong7587/media-index/pkgs/container/media-index)
![Version](https://img.shields.io/badge/version-0.6.9-6d7cff?style=flat-square)
![Docker](https://img.shields.io/badge/deploy-Docker-2496ed?style=flat-square)
![License](https://img.shields.io/badge/license-GPL--3.0-111827?style=flat-square)

当前版本：**0.6.9**

📖 **[完整使用手册](docs/USAGE.md)** · 🐳 **[Docker Compose 部署](docker-compose.yaml)** · 🛠️ **[变更记录](CHANGELOG.md)** · 📜 **[第三方组件声明](THIRD_PARTY_NOTICES.md)** · 🧭 **[路线图](docs/ROADMAP.md)**

MediaIndex 不提供影视资源或分享链接，也不替用户作版权判断；它只使用你自行配置的 TMDB、PanSou、网盘、OpenList、Emby 与通知服务，把已有的媒体工作流自动化。证据不足的资源会保留为待确认，不会以不确定的标题或过期链接直接执行转存。

## 它解决什么

| 环节 | MediaIndex 的职责 |
| --- | --- |
| 资源发现 | 从 TMDB 发现和核对媒体信息；通过 PanSou 查询候选，读取分享内真实文件再匹配标题、年份、季集和播出信息。 |
| 网盘转存 | 原生夸克与原生 115 Cookie 连接；按媒体类型、质量优先级和文件范围选择资源，转存到各自保存目录。 |
| 整理命名 | 以统一的电影、剧集、季目录与媒体文件夹规则改名、移动；所有目标路径由后端生成。 |
| 跨盘补齐 | 只有夸克可转而 115 没有可用资源时，才按已配置的 OpenList 方向执行夸克 → 115 补齐。 |
| STRM 与播放 | 从 115 或夸克目录生成并维护 `.strm`；同一容器提供 302 播放入口，供 Emby 与其他播放器访问。 |
| Emby 联动 | 刷新匹配的媒体库、生成可实时预览与独立配置中英文字体的静态媒体库封面；接收 Emby 删除 Webhook 后可同步处理 MediaIndex 生成的网盘媒体。 |
| 追更和通知 | 愿望单、智能追更、任务中心、运行日志；企业微信与 Telegram 接收海报图文通知，外部刮削器或整理器完成后可通过 Webhook 触发安全增量同步。 |

每个转存任务都可在右上角运行日志与发现详情的流程预览中查看：网盘资源查询、TMDB 核对和改名、转存、按需 OpenList 补齐、STRM、Emby 入库和通知。单独启用一个网盘时，不会显示不适用的跨盘步骤。

## 核心能力

- **原生双网盘**：夸克和 115 均通过 Cookie 连接，不需要额外部署 QAS；两个网盘可独立启用，一个失败不覆盖另一个的结果。
- **安全的资源核对**：不会把普通结果标题当作真实文件，也不会把缓存分享链接当作永久可用；执行前重新验证，失效链接不会被提交。
- **媒体级而非逐集噪声**：剧集转存、STRM 生成与删除通知按媒体目录汇总；必要的分集选择仍保留。
- **可控 STRM 维护**：分别配置 115/夸克来源目录和必须明确勾选的直接子目录，不默认扫描整盘；全量、增量、Cron 与 Webhook 均完整分页，不设 10,000 条总量上限。
- **302 播放入口**：MediaIndex 容器同时监听管理端口与播放端口，`.strm` 写入可被播放器访问的播放地址；不需要独立 playback 容器。
- **Emby 生命周期联动**：按输出路径自动匹配媒体库并刷新；四种静态封面模板支持常驻实时预览、每库中英文标题、独立字体上传及文字位置和大小微调；可把 Emby 删除事件交给 MediaIndex 同步处理。
- **OpenList 只做应做的事**：用于已挂载媒体库的复制和必要的夸克 → 115 补齐，不宣称无落盘或秒传，具体行为由 OpenList 与其存储驱动决定。
- **通知与交互**：企业微信自建应用、企微机器人和 Telegram；媒体通知优先使用海报图文卡片与易读字段，支持自定义 STRM 扫描、追更查看和添加下载快捷菜单。
- **通用 Webhook 联动**：MDC-NG 等外部刮削器、整理器或其他容器可通过带密钥的 POST Webhook 通知 MediaIndex；连续完成事件会合并为一次只增不删的 STRM 增量同步，扫描范围强制沿用对应网盘已保存的勾选目录。

## 依赖与可选服务

**基本配置**

- [TMDB API Key](https://www.themoviedb.org/settings/api)：媒体资料、海报与分集信息。
- [fish2018/pansou](https://github.com/fish2018/pansou)：资源候选检索。可单独部署，或使用已有服务。
- 至少一个网盘：原生夸克 Cookie 或原生 115 Cookie。115 的旧 Open 配置会为升级兼容而保留，但不会参与执行。

**按需启用**

- OpenList：夸克/115 媒体库的手动复制，以及发现页必要时的夸克 → 115 补齐。
- Emby：入库刷新、封面工坊和删除 Webhook；不配置 Emby 仍可完成转存与 STRM。
- 企业微信或 Telegram：外部通知、移动端待确认与交互。
- 外部刮削或整理服务：可选；例如 [MDC-NG](https://github.com/mdc-ng/mdc-ng)，任务成功后可通过通用 Webhook 触发 MediaIndex 增量生成 STRM。

## 快速部署

仓库根目录提供可直接运行的 [`docker-compose.yaml`](docker-compose.yaml)。默认只启动 MediaIndex；PanSou 是可选的注释服务，可按需启用。PanSou 地址始终在管理面板保存，不需要写入 Compose 环境变量。

```bash
mkdir media-index
cd media-index
curl -LO https://raw.githubusercontent.com/xudong7587/media-index/main/docker-compose.yaml
```

至少修改用户名、密码与 STRM 目录挂载。标准 Compose 使用容器同端口映射，部署者按自己的 NAS 端口规划只改左侧即可：

```yaml
services:
  media-index:
    image: ghcr.io/xudong7587/media-index:latest
    pull_policy: always
    container_name: media-index
    ports:
      - "8000:8000" # 管理面板
      - "8097:8097" # STRM/302 播放入口
    environment:
      MEDIA_USER: admin
      MEDIA_PASS: 请改成高强度密码
      MEDIA_CONFIG_PATH: /app/data/.env
      STATIC_DIR: /app/frontend
      DB_PATH: /app/data/media_index.db
      CACHE_DIR: /app/data/cache
      STRM_OUTPUT_ROOT: /strm
      MEDIA_PLAYBACK_INTERNAL_PORT: 8097
    volumes:
      - ./data:/app/data
      - ./downloads:/downloads
      - /你的NAS媒体路径/strm:/strm # 与 Emby 扫描的同一目录
    restart: unless-stopped
```

`8000` 是管理面板，`8097` 是 STRM/302 播放入口。若 NAS 已占用端口，改左侧即可，例如 `24680:8000` 与 `24697:8097`；无需把宿主机端口写进 environment。`/strm` 必须挂载到 Emby 实际扫描的目录，并需具有写入 `.strm` 的权限。

启动：

```bash
docker compose up -d
```

首次访问 `http://你的NAS地址:8000`。进入 **STRM 与 302 → STRM 通用设置**，填写播放器实际能够访问的播放地址：内网可填 `http://NAS_IP:8097`，反向代理则填写对应的 HTTPS 域名。不要把管理端口或 `127.0.0.1` 写入 STRM 播放地址。

### 从旧版本升级到 0.6.0

0.6.0 把 302 播放服务合并进 `media-index` 容器：

1. 备份 `./data`，停止旧容器。
2. 使用当前 Compose，保留管理端口和播放端口；可按 NAS 规划修改左侧映射。
3. 挂载 Emby 实际扫描的 STRM 目录到 `/strm`。
4. `docker compose pull && docker compose up -d`；不要保留旧的独立 `media-index-playback` 容器。
5. 保存 STRM 通用设置；旧 `.strm` 若仍指向旧端口或 `127.0.0.1`，重新执行对应网盘的全量扫描更新。

若 NAS 目录有固定属主，可设置匹配目录权限的 `PUID`、`PGID`。不要为了播放端口添加 `EMBY_PROXY_PORT`。

## 首次配置建议

1. 在 **全局设置** 保存 TMDB、PanSou 与网络代理（如需要）。
2. 在 **网盘工作台 → 网盘连接** 粘贴并验证原生夸克 Cookie、115 Cookie；只启用要使用的网盘。
3. 在 **转存和整理规则** 配置各网盘的根目录、云下载目录、分类路径、质量优先级、媒体文件夹/季/文件命名规则。
4. 如需跨盘复制，在 **全局设置 → OpenList 同步** 保存地址、Token、两个挂载目录和同步方向；跨盘转存页只负责选择路径与查看任务。
5. 在 **STRM 与 302** 分别设置网盘来源、STRM 输出目录和播放地址，读取并明确勾选需要生成的直接子目录；未勾选时不会默认扫描整盘。将 `/strm` 与 Emby 媒体库目录对应。
6. 如需自动入库，在 **媒体服务器** 保存 Emby 地址、API Key；可选择媒体库封面样式、刷新与删除同步策略。
7. 最后在 **全局设置 → 通知和交互** 配置企业微信或 Telegram，并先发送测试通知。
8. 如需接入外部刮削器或整理器，在 **通知和交互 → Webhook** 生成密钥、选择网盘和来源目录，保存后把完整 Endpoint URL 填入外部服务；页面提供可复制的 `curl` 测试命令。

详细字段、路径选择、追更、Webhook 与故障排查请看 [完整使用手册](docs/USAGE.md)。

## STRM、Emby 与删除同步

- 115 与夸克 STRM 各自选择网盘来源目录；`/strm` 输出目录是 NAS 上的本地文件操作，不从属于网盘转存保存规则。
- 全量、手动增量、Cron 周期增量、115 生活监控和 Webhook 触发增量都会完整分页遍历当前范围，不设置 10,000 文件总量上限；内部仍以 500 条为一批写入本地数据库。勾选来源目录的直接子目录后，仅读取和维护这些目录；运行日志会显示当前扫描目录。
- 增量扫描永不执行缺失项清理；远端返回空清单、只有海报/NFO 而未发现任何视频，也直接跳过清理。只有明确完成的有效全量扫描才可推进清理：首次缺失进入 `pending_remove`，连续第二次仍缺失才允许删除；异常批量删除或批量路径改变会在写入前触发熔断。
- Emby 自动入库会根据当前 STRM 输出与媒体库关联刷新对应媒体库；通用设置不再展示历史的路径自动匹配与后备媒体库选项。
- Emby Webhook 使用 MediaIndex 设置页生成的完整回调 URL，并通过设置页的 Webhook 密钥校验。公共 STRM 根目录会保留 Emby 具体媒体库的首层目录；只对能唯一解析到 115 文件 ID 的完整 STRM 路径执行联动删除，不按名称猜测，重复事件不会再次执行。
- 302 播放入口代理的是实际 Emby 媒体请求；它不是新的 Emby 服务器，也不替代 Emby 的真实地址与认证。

## 运行、备份与开发

更新：

```bash
docker compose pull
docker compose up -d
```

备份 `./data`（配置、数据库和缓存）、`./downloads`（若使用本地下载）以及 NAS 上实际的 STRM 目录。仓库 Compose 默认跟随 `latest`；需要固定版本或回退时，从 [GitHub Releases](https://github.com/xudong7587/media-index/releases) 选择镜像标签。

本地开发与测试：

```bash
docker build -t media-index:local .
PYTHONPATH=backend python -m pytest tests
cd frontend && pnpm build
```

## 开源许可证

从 `0.6.1` 起，MediaIndex 以 [GPL-3.0](LICENSE) 发布。媒体库封面工坊包含
从 MoviePilot-Plugins 移植的静态 MediaCoverGenerator 代码；原作者、上游来源、
移植范围和不随镜像分发样图的说明见 [第三方组件声明](THIRD_PARTY_NOTICES.md)。

## 致谢

MediaIndex 的设计和实现过程中参考了社区项目与作者的经验，特此感谢：

- [Cp0204/quark-auto-save](https://github.com/Cp0204/quark-auto-save)（QAS）
- [tgtodriver](https://github.com/Tech-Solutions-Group/tgtodriver)
- [MoviePilot](https://github.com/jxxghp/MoviePilot)
- MoviePilot 社区的 115 STRM 助手及相关插件作者
- [fish2018/pansou](https://github.com/fish2018/pansou)、OpenList、TMDB 及所有相关开源项目贡献者

## 免责声明

本项目仅提供个人学习、技术研究和自托管自动化所需的软件代码。项目本身不制作、不存储、不托管、不上传、不下载、不分发、不销售，也不内置或提供任何影视资源、网盘分享链接、提取码、账号、Cookie、破解工具或规避版权保护的能力。

TMDB、PanSou、网盘服务、OpenList、Emby 以及搜索结果均属于独立第三方服务或用户自行部署的服务，MediaIndex 不控制、不审核，也不保证其内容来源、版权状态、准确性、安全性、持续可用性或合法性。搜索、匹配、转存、重命名、STRM 生成和删除同步等操作均由部署者使用自己的账号、Cookie、Token 和第三方服务主动配置并触发。

使用者必须确保自己对相关内容拥有合法访问、复制、转存和使用权，并遵守所在地法律法规、著作权规定、网盘及第三方服务条款。禁止将本项目用于盗版传播、未经授权分享、商业侵权或任何违法用途。因部署或使用本项目引起的版权纠纷、账号封禁、数据丢失、隐私泄露、服务费用或其他直接、间接损失，均由使用者自行承担。完整条款见 [DISCLAIMER.md](DISCLAIMER.md)。
