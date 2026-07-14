<p align="center"><img src="docs/media-index-icon.png" alt="MediaIndex" width="150" /></p>

# MediaIndex

面向个人 NAS 的影视发现、夸克转存、愿望单和智能追更控制台。

[![GHCR](https://img.shields.io/badge/GHCR-media--index-2f8f8c?style=flat-square)](https://github.com/xudong7587/media-index/pkgs/container/media-index)
![Version](https://img.shields.io/badge/version-0.3.16-6d7cff?style=flat-square)
![Docker](https://img.shields.io/badge/deploy-Docker-2496ed?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-111827?style=flat-square)

MediaIndex 最大的特点是**智能追更**，而不是保存一个可能很快失效的固定分享链接。剧集或综艺更新时，系统会读取目标目录的已存集数，根据 TMDB 的播出信息确定下一缺失集，重新通过 PanSou 搜索候选，使用 QAS 验证分享和真实文件，再与 TMDB 季集信息匹配，最后按 `媒体名.年份.SxxExx` 标准化命名并转存。旧链接失效或没有更新时，系统会重新找源；证据不足时停止自动执行并进入待确认。

除此之外，MediaIndex 还提供 TMDB 影视发现、单次转存和愿望单。整个后端把 TMDB、PanSou 与 [quark-auto-save（QAS）](https://github.com/Cp0204/quark-auto-save) 串成一条保守、可追溯的自动化链路。

作者是编程门外汉，代码AI比例100%，项目已经做了对抗性安全审查，如果有什么问题感谢各位用户大佬到Issues反馈，请各位大佬轻喷。

本项目不提供媒体资源、分享链接、网盘账号或 Cookie。部署者应自行确保第三方服务和资源的合法使用。

## 主要功能

- TMDB 电影、剧集、综艺发现与搜索
- PanSou 多关键词候选搜索
- QAS 分享验证、文件读取、转存与重命名
- 智能追更：按 TMDB 更新信息重新搜索、匹配下一缺失集并标准化命名
- 按 TMDB 日期运行的愿望单
- 不确定结果进入待确认并通过 QAS 通知
- 网盘 `/strm` 与本地 `/下载_未整理` 分类路径
- 深色/浅色界面和任务进度提示

## Docker Compose 部署

仓库根目录已经提供可直接运行的 [`docker-compose.yaml`](docker-compose.yaml)。下载文件：

```bash
mkdir media-index
cd media-index
curl -LO https://raw.githubusercontent.com/xudong7587/media-index/main/docker-compose.yaml
```

打开 `docker-compose.yaml`，至少修改 `MEDIA_USER` 和 `MEDIA_PASS`，如有需要再修改端口：

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
    restart: unless-stopped
```

然后运行：

```bash
docker compose up -d
```

访问 `http://你的NAS地址:38000`。登录后进入“设置”，填写：

- TMDB API Key
- QAS 地址和 Token
- PanSou 地址
- 网盘、本地根路径和分类路径
- 愿望单巡检设置

不需要创建或单独映射 `.env`。首次保存设置后，程序会自动生成 `./data/.env`。SQLite 数据库、缓存和自动生成的登录签名密钥也都保存在 `./data` 中，方便 NAS 用户直接查看、备份和迁移；更新或重建容器不会丢失。

应用会拒绝空密码以及密码 `admin`。请不要直接使用示例密码。

## 依赖

- [TMDB API Key](https://www.themoviedb.org/settings/api)
- [fish2018/pansou](https://github.com/fish2018/pansou)
- [Cp0204/quark-auto-save](https://github.com/Cp0204/quark-auto-save)

MediaIndex 必须能够从容器网络访问 PanSou 和 QAS。若它们也由 Docker 部署，建议放入同一自定义网络并使用容器名访问。

## 保存规则

最终路径始终由后端生成，前端和搜索结果不能传入任意保存路径：

- 电影：`{根路径}/movie/媒体名(首播年份)`
- 剧集：`{根路径}/tv/媒体名(首播年份)`
- 综艺：`{根路径}/tv/媒体名(首播年份)`

默认网盘根路径是 `/strm`，本地根路径是 `/下载_未整理`。本地根路径可交给 MoviePilot 等其他工具继续同步处理。

文件命名：

- 电影：`媒体名.年份.mkv`
- 剧集：`媒体名.年份.S01E01.mkv`
- 合集：`媒体名.年份.S01E01-E02.mkv`

## 版本更新

每个版本的完整变更、验证结果和固定镜像标签统一发布在 [GitHub Releases](https://github.com/xudong7587/media-index/releases)，README 不再重复维护版本日志。

## 更新

```bash
docker compose pull
docker compose up -d
```

备份时只需停止容器并备份 `./data` 目录。恢复时把该目录和 `docker-compose.yaml` 放回同一部署目录后重新启动即可。

仓库 Compose 默认跟随 `latest`。如需锁定版本或回退，请从 GitHub Releases 选择对应镜像标签。

## 安全建议

- 建议仅在内网、VPN 或可信反向代理后使用。
- 公网 HTTPS 部署时设置 `COOKIE_SECURE=true`。
- QAS Token、TMDB Key 和密码都应按敏感信息保管。
- 不要将数据卷、数据库或自动生成的配置文件公开。
- 发布前可运行 `git grep` 检查仓库中是否混入真实密钥。

## 本地构建与测试

```bash
docker build -t media-index:local .
python -m unittest discover -s tests
```

## 免责声明

本项目仅提供个人学习、技术研究和自托管自动化所需的软件代码。项目本身不制作、不存储、不托管、不上传、不下载、不分发、不销售，也不内置或提供任何影视资源、网盘分享链接、提取码、账号、Cookie、破解工具或规避版权保护的能力。

TMDB、PanSou、QAS、网盘服务以及搜索结果均属于独立第三方服务或用户自行部署的服务，MediaIndex 不控制、不审核，也不保证其内容来源、版权状态、准确性、安全性、持续可用性或合法性。搜索、匹配、转存、重命名和 STRM 生成等操作均由部署者使用自己的账号、Cookie、Token 和第三方服务主动配置并触发。

使用者必须确保自己对相关内容拥有合法访问、复制、转存和使用权，并遵守所在地法律法规、著作权规定、网盘及第三方服务条款。禁止将本项目用于盗版传播、未经授权分享、商业侵权或任何违法用途。因部署或使用本项目引起的版权纠纷、账号封禁、数据丢失、隐私泄露、服务费用或其他直接、间接损失，均由使用者自行承担。完整条款见 [DISCLAIMER.md](DISCLAIMER.md)。
