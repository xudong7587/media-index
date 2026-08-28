<p align="center"><img src="frontend/public/assets/media-index-icon.png" alt="MediaIndex" width="150" /></p>

# MediaIndex

MediaIndex 是面向个人 NAS 的**自托管网盘媒体自动化中心**：以 TMDB 与 PanSou 完成发现和资源核对，原生连接夸克与 115，并把云端转存、分类命名、高效 STRM/302、Emby 入库与安全联动删除、智能追更、愿望单和图文通知串成一条可查看、可追溯、可控制的完整流程。

[![GHCR](https://img.shields.io/badge/GHCR-media--index-2f8f8c?style=flat-square)](https://github.com/xudong7587/media-index/pkgs/container/media-index)
![Version](https://img.shields.io/badge/version-0.7.4-6d7cff?style=flat-square)
![Docker](https://img.shields.io/badge/deploy-Docker-2496ed?style=flat-square)
![License](https://img.shields.io/badge/license-GPL--3.0-111827?style=flat-square)

当前版本：**0.7.4**

📖 **[完整使用手册](docs/USAGE.md)** · 🧩 **[浏览器扩展](browser-extension/README.md)** · 🐳 **[Docker Compose 部署](docker-compose.yaml)** · 🛠️ **[变更记录](CHANGELOG.md)** · 📜 **[第三方组件声明](THIRD_PARTY_NOTICES.md)** · 🧭 **[路线图](docs/ROADMAP.md)**

MediaIndex 不提供影视资源或分享链接，也不替用户作版权判断；它只使用你自行配置的 TMDB、PanSou、网盘、OpenList、Emby 与通知服务，把已有的媒体工作流自动化。证据不足的资源会保留为待确认，不会以不确定的标题或过期链接直接执行转存。

## 从用户的问题开始

如果你的影片和剧集保存在网盘，真正麻烦的通常不是“找到一个链接”，而是后面这一整串事情：确认内容是否正确、选清晰度、转存到合适目录、统一命名、持续补齐更新、让 Emby 能播放，并在失败时知道卡在哪里。

MediaIndex 把这些步骤放进一个自托管控制台。你仍然决定使用哪个来源、保存到哪里、哪些任务可以自动运行；系统负责执行重复工作，并把不确定的结果交还给你确认。

## 特点与优势

- **一条完整的使用链路**：从发现、搜索和链接输入开始，一直到网盘整理、STRM、Emby 与通知，不必在多个脚本之间来回维护状态。

- **自动化始终有边界**：网盘、目录、定时任务和处理范围都由你明确选择；无法可靠判断的内容进入待确认，不会自行扩大操作范围。

- **夸克与 115 可以并存**：两个网盘分别设置连接、保存位置、任务和 STRM，可按资源与使用习惯选择目标。

- **适合持续维护媒体库**：云下载整理、分类命名、追更、愿望单、全量与增量 STRM 形成长期工作流，而不只是一次性转存工具。

- **过程看得见**：任务中心展示执行进度和失败原因，通知中心、活动记录与日志帮助你判断下一步该做什么。

- **按需连接现有服务**：TMDB、PanSou、Emby、OpenList、企业微信和 Telegram 都是可选能力；不用的功能无需配置。

## 使用逻辑

```text
发现内容或提交链接
        ↓
确认媒体、季数、来源和目标网盘
        ↓
按分类与命名规则转存、整理
        ↓
生成 STRM，并由 Emby 扫描和播放
        ↓
用追更、愿望单、定时任务和通知持续维护
```

这条流程可以从任何一段开始：已有整理好的网盘目录，可以只用 STRM；只想找资源，可以只用发现和搜索；已经在使用 Emby，也可以仅接入媒体库查看、封面和安全删除联动。

## 你可以完成什么

| 目标 | 对应能力 |
| --- | --- |
| 看看最近有什么值得入库 | 通过榜单、分类、搜索和详情页发现电影、剧集、动漫与综艺。 |
| 把现成链接交给系统处理 | 识别夸克、115、磁力、ED2K 与 HTTP 链接，并可从网页、互动消息或仓库内的浏览器扩展选择云下载整理或直接入库。 |
| 让网盘目录长期保持一致 | 自动把已选云下载分类核对、命名并复制或移动到同名正式媒体库分类。 |
| 自动关注未上映或连载内容 | 使用愿望单等待资源，使用智能追更观察更新并补齐缺集。 |
| 处理不确定的搜索结果 | 在待确认中查看候选、重新搜索或明确选择，不让模糊结果直接执行。 |
| 在夸克已有而 115 缺失时补齐 | 通过独立的 OpenList 页面自动或手动执行夸克到 115 补偿。 |
| 让 Emby 播放网盘媒体 | 为 115 或夸克目录生成 STRM，通过单独的 302 播放入口访问原文件。 |
| 查看和维护 Emby 媒体库 | 查看媒体库、用户、播放会话、最近入库，并按库制作和替换封面。 |
| 随时掌握自动任务状态 | 使用站内通知、企业微信或 Telegram 接收结果，也可在聊天中提交链接和指令。 |

完整页面说明、设置顺序和使用场景见 **[使用手册](docs/USAGE.md)**；发现、双网盘、OpenList、云下载和 Webhook 的系统边界见 **[流程与架构审计](docs/FLOW_AND_ARCHITECTURE_AUDIT.md)**。

## 适合谁

MediaIndex 适合已经拥有 NAS 或常驻 Docker 环境、使用夸克或 115 保存自己有权访问的媒体，并希望用 Emby 建立个人媒体库的用户。你不需要会写脚本，但需要能够维护 Docker Compose、准备自己的服务账号，并理解转存、删除和第三方服务都有各自风险。

如果你只需要本地文件播放器、没有常驻设备，或希望系统直接提供影视资源，MediaIndex 并不适合；项目不提供资源、账号、Cookie 或第三方服务。

## 开始前准备

| 项目 | 用途 |
| --- | --- |
| Docker 与 Docker Compose | 运行 MediaIndex。 |
| 夸克或 115 账号 | 至少连接一个，作为转存和媒体文件来源。 |
| 一个持久化目录 | 保存数据库、网页设置、STRM 与必要的任务文件。 |
| TMDB API | 推荐，用于海报、详情、季集信息和播出状态。 |
| PanSou | 可选，用于在站内聚合搜索资源。 |
| Emby | 可选，用于媒体库扫描、展示和播放。 |
| OpenList、企业微信或 Telegram | 可选，用于跨盘复制或消息交互。 |

所有凭据都由你在自己的部署中填写，并保存在挂载的 `./data` 中。镜像不预置账号或第三方 Token。

## 快速部署

官方 GHCR 镜像同时支持 `linux/amd64` 和 `linux/arm64`（64 位 ARM）。Compose
无需区分架构，Docker 会自动拉取与宿主匹配的镜像；暂不支持 32 位 `arm/v7`。

先创建工作目录：

```bash
mkdir -p media-index/{data,downloads,strm}
cd media-index
```

保存为 `docker-compose.yaml`：

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
      MEDIA_PASS: change-this-password
      MEDIA_CONFIG_PATH: /app/data/.env
      DB_PATH: /app/data/media_index.db
      CACHE_DIR: /app/data/cache
      STRM_OUTPUT_ROOT: /strm
      MEDIA_PLAYBACK_INTERNAL_PORT: 8097
      PUID: ${PUID:-10001}
      PGID: ${PGID:-10001}
      # 可选：也可在启动后从“系统设置 → 网络代理”填写。
      PROXY_URL: ${PROXY_URL:-}
      HTTP_PROXY: ${HTTP_PROXY:-}
      HTTPS_PROXY: ${HTTPS_PROXY:-}
      NO_PROXY: ${NO_PROXY:-localhost,127.0.0.1,::1,media-index,pansou,quark-auto-save,openlist}
    volumes:
      - ./data:/app/data
      - ./downloads:/downloads
      - ./strm:/strm
    restart: unless-stopped
```

将 `MEDIA_PASS` 改成强密码后启动：

```bash
docker compose up -d
```

打开 `http://你的NAS地址:8000`。`8000` 是管理面板，`8097` 是供播放器访问的 STRM/302 入口；NAS 端口冲突时只修改映射左侧。`./strm` 应挂载到 Emby 实际扫描的目录，并确保容器有写入权限。

### 容器网络代理

如果 TMDB 等外部服务无法直连，可在 **系统设置 → 网络代理** 填写 NAS 可访问的完整代理地址，例如 `http://192.168.31.81:7890`，然后点击“测试代理”。测试由 MediaIndex 容器实际访问 TMDB，不是由浏览器发起。代理软件需允许局域网连接，且 NAS 防火墙需放行对应端口；不要填写 `127.0.0.1`，因为它在容器内指向容器自身。

也可在 Compose 的 `.env` 中设置 `PROXY_URL`，或使用标准的 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`。网页保存的 `PROXY_URL` 优先于 Compose 中同名的启动默认值；PanSou、QAS、OpenList、网盘等 Docker 服务名、本机或局域网目标仍保持直连。

## 第一次使用建议

1. 在 **网盘工作台 → 网盘链接** 中启用夸克或 115，保存凭据并测试连接。

2. 在 **全局设置** 中配置 TMDB；需要站内搜索时，再配置 PanSou 和搜索来源。

3. 在 **转存和整理规则** 中设置保存根目录、暂存位置、分类路径和命名偏好。

4. 从发现页选择一部熟悉的媒体做单次转存，先核对结果目录与名称。

5. 在 **STRM 与 302** 中填写来源目录、输出目录和播放器能够访问的地址，并只勾选需要处理的目录。

6. 连接 Emby，建立对应媒体库，确认扫描和播放都正常。

7. 最后再逐项开启追更、愿望单、定时 STRM、通知、删除联动或 OpenList。

## 典型使用方式

### 从一部电影开始

在发现页或搜索框找到电影，打开详情，选择目标网盘和候选资源，确认后转存。任务完成后检查网盘目录，再生成增量 STRM 并刷新 Emby。

### 长期追一部连载剧

先保存已有季集并创建追更。MediaIndex 会展示云端已存进度与作品播出状态；发现缺集时可以自动尝试，也可以由你选择要补的集数。

### 管理已经存在的网盘媒体

跳过发现和转存，直接配置 STRM 来源根目录，读取直接子目录并明确勾选处理范围。首次运行全量扫描，之后使用增量或定时任务维护。

### 用手机处理日常任务

配置企业微信或 Telegram 后，接收成功、失败和待确认消息；也可以发送资源名称或下载链接，在聊天中确认候选、查看追更和任务状态。

## 更新、备份与许可

更新前建议备份 `./data`、`./strm`、`./downloads` 和 `docker-compose.yaml`。然后执行：

```bash
docker compose pull
docker compose up -d
```

从 0.6.0 以前版本升级时，请使用当前 Compose 的单容器双端口结构，并移除旧的独立播放容器；已有数据库和网页设置无需重建。完整升级、备份和排障步骤见 [使用手册](docs/USAGE.md)。

MediaIndex 本体采用 [GNU General Public License v3.0](LICENSE)。第三方组件及其许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

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
