<p align="center">
  <img src="docs/media-index-icon.png" alt="Media Index" width="160" />
</p>

<h1 align="center">Media Index</h1>

<p align="center">
  面向个人 NAS 的影视发现、愿望单、转存与智能追更面板。
</p>

<p align="center">
  <a href="https://github.com/xudong7587/media-index/pkgs/container/media-index"><img alt="GHCR" src="https://img.shields.io/badge/GHCR-media--index-2f8f8c?style=flat-square" /></a>
  <img alt="Version" src="https://img.shields.io/badge/version-0.1.1-6d7cff?style=flat-square" />
  <img alt="Docker" src="https://img.shields.io/badge/deploy-Docker-2496ed?style=flat-square" />
  <img alt="License" src="https://img.shields.io/badge/license-MIT-111827?style=flat-square" />
</p>

---

Media Index 把 TMDB 元数据、PanSou 资源搜索和 quark-auto-save（QAS）任务触发串起来，用来管理影视发现、愿望单、一次性转存和智能追更记录。

> 作者是编程门外汉，本项目从需求梳理、代码实现到文档整理均由 AI 协助完成。如果有设计不成熟、实现不周全或文档遗漏之处，敬请见谅，也欢迎用 Issue 提醒我慢慢修正。

> 本项目不提供任何媒体资源、下载链接、网盘账号、Cookie 或受版权保护的内容。项目只提供个人学习和自托管自动化流程示例，所有第三方服务、资源来源和使用行为均由部署者自行负责。

## 功能

- TMDB 海报流发现：电影、剧集、综艺等分类浏览
- 发现页分页浏览：默认每页 24 个海报，支持上一页/下一页继续请求 TMDB
- 服务端 TMDB 缓存：降低 API 调用频次
- PanSou 快速资源探测：只做可用性检查，不内置资源
- QAS 集成：触发网盘转存和 STRM 流程
- 智能追更记录：适合连载剧集/综艺的后续追踪
- 愿望单：暂无资源或匹配不确定的内容可进入等待队列
- 深浅色主题切换
- Docker / Docker Compose 部署

## 版本

当前版本：`0.1.1`

镜像：

```bash
docker pull ghcr.io/xudong7587/media-index:0.1.1
docker pull ghcr.io/xudong7587/media-index:latest
```

## 依赖服务

你需要自行准备以下服务：

- TMDB API Key
- PanSou 服务：[fish2018/pansou](https://github.com/fish2018/pansou)
- QAS 服务：[Cp0204/quark-auto-save](https://github.com/Cp0204/quark-auto-save)

## 快速开始

创建部署目录并下载示例文件：

```bash
mkdir media-index
cd media-index
curl -o docker-compose.yml https://raw.githubusercontent.com/xudong7587/media-index/main/docker-compose.example.yml
curl -o .env https://raw.githubusercontent.com/xudong7587/media-index/main/.env.example
```

编辑 `.env`，填入你自己的配置：

```env
TMDB_API_KEY=your_tmdb_key
QAS_BASE_URL=http://your-qas-host:your-qas-port
QAS_TOKEN=your_qas_token
PANSOU_URL=http://your-pansou-host:your-pansou-port
MEDIA_PASS=change_this_password
```

启动服务：

```bash
docker compose up -d
```

访问：

```text
http://your-host:38000
```

默认用户名是 `admin`。你必须在 `.env` 中设置自己的 `MEDIA_PASS`，应用会拒绝使用空密码或 `admin` 作为密码。

## 配置说明

| 变量 | 说明 |
| --- | --- |
| `MEDIA_USER` / `MEDIA_PASS` | Media Index 登录用户名和密码 |
| `AUTH_SECRET` | 可选。登录 Cookie 签名密钥；不填写时会自动生成并保存在数据目录 |
| `TMDB_API_KEY` | TMDB API Key |
| `QAS_BASE_URL` | QAS 服务地址 |
| `QAS_TOKEN` | QAS API Token |
| `PANSOU_URL` | PanSou 服务地址 |
| `CLOUD_SAVE_PATH` | 网盘/STRM 根路径，默认 `/strm` |
| `LOCAL_SAVE_PATH` | 本地保存根路径，默认 `/downloads`，可用于 MoviePilot、OpenList 等其他影视服务同步 |
| `CATEGORY_PATHS_JSON` | 分类路径映射，例如 `{"movie":"/movie","tv":"/tv","variety":"/tv"}` |
| `WISHLIST_CRON_ENABLED` | 愿望单定时扫描开关 |
| `WISHLIST_CRON_SCHEDULE` | 愿望单扫描 cron 表达式占位 |

## 本地构建

```bash
docker build -t media-index:local .
```

## 安全建议

- 不要把 `.env` 上传到 GitHub 或分享给别人。
- 不建议把服务直接暴露到公网。
- 建议放在 VPN、内网、可信反向代理或其他访问控制之后。
- QAS Token 可以控制转存任务，请按密码级别保管。
- 本地数据库可能包含媒体名称、路径、任务记录等个人使用痕迹。
- 首次部署后请立刻修改 `MEDIA_PASS`。
- 请持久化挂载 `./data:/app/data`，否则自动生成的登录签名密钥会随容器重建而丢失，用户需要重新登录。

## 当前限制

- PanSou 检查是快速浅层检查，只用于判断是否可能有资源。
- 转存执行采用保守策略，标题或年份不确定时会进入待确认/愿望单，而不是直接宽泛匹配。
- 愿望单 cron 目前保留配置入口，实际生产级定时调度请结合自己的部署环境确认。
- 本项目处于早期版本，建议先在个人测试环境验证流程。

## 免责声明

本项目仅用于个人学习、技术研究和自托管自动化流程验证。软件本身不存储、不分发、不销售、不上传、不下载任何媒体资源，也不提供任何可绕过版权保护的能力。

通过本项目触发的搜索、转存、STRM 生成等行为，依赖用户自行配置的第三方服务。相关服务返回的内容均来自互联网或用户自有服务，本项目无法控制其合法性、准确性、完整性或可用性。

使用者应遵守所在地区法律法规、服务条款和版权要求。请勿将本项目用于侵犯版权、未经授权传播内容、商业盗版或其他违法用途。因使用本项目产生的任何法律责任、账号风险、数据风险或第三方服务风险，均由使用者自行承担。

完整说明见 [DISCLAIMER.md](DISCLAIMER.md)。
