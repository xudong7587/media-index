<p align="center"><img src="docs/media-index-icon.png" alt="MediaIndex" width="150" /></p>

# MediaIndex

面向个人 NAS 的影视发现、夸克转存、愿望单和智能追更控制台。

[![GHCR](https://img.shields.io/badge/GHCR-media--index-2f8f8c?style=flat-square)](https://github.com/xudong7587/media-index/pkgs/container/media-index)
![Version](https://img.shields.io/badge/version-0.3.0-6d7cff?style=flat-square)
![Docker](https://img.shields.io/badge/deploy-Docker-2496ed?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-111827?style=flat-square)

MediaIndex 把 TMDB、PanSou 和 [quark-auto-save（QAS）](https://github.com/Cp0204/quark-auto-save) 串成一条保守的自动化链路：识别媒体、搜索候选、验证夸克分享、匹配真实文件、规范命名并调用 QAS 转存。连载内容会先读取目标目录的已存集数，只处理下一缺失集。

本项目不提供媒体资源、分享链接、网盘账号或 Cookie。部署者应自行确保第三方服务和资源的合法使用。

## 主要功能

- TMDB 电影、剧集、综艺发现与搜索
- PanSou 多关键词候选搜索
- QAS 分享验证、文件读取、转存与重命名
- 已存集数检测和智能追更
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
    image: ghcr.io/xudong7587/media-index:0.3.0
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

## 0.3.0 变更

- 目录读取异常时停止执行，不再误判为“已存 0 集”
- 每次只处理最早的下一缺失集
- 兼容唯一历史目录，多个兼容目录会停止并提示冲突
- 增加活动任务幂等约束，避免重复点击和多调度器重复转存
- 收紧 QAS 返回判断；周期跳过、空响应和“无新任务”不再独立视为完成
- 必须在目标目录确认全部预期文件存在且大小大于 0
- 服务重启后恢复被中断的任务状态
- SQLite 增加外键、锁等待和唯一索引
- 登录接口增加失败次数限流，Cookie 支持 Secure 配置
- 改进长篇剧集、综艺期数、电影版本和 PanSou 候选匹配
- 发现页增加搜索阶段提示和智能追更状态
- 公共镜像改为单 Compose 部署，配置自动持久化到仓库同目录的 `./data`

详细可靠性边界见 [docs/RELIABILITY_0.3.0.md](docs/RELIABILITY_0.3.0.md)。

## 更新

```bash
docker compose pull
docker compose up -d
```

备份时只需停止容器并备份 `./data` 目录。恢复时把该目录和 `docker-compose.yaml` 放回同一部署目录后重新启动即可。

如希望自动跟随最新稳定版，可把镜像标签改成 `latest`。

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

项目仅用于个人学习、技术研究和自托管自动化。本项目不存储、分发、销售或提供任何媒体资源。使用者应遵守所在地法律、第三方服务条款和版权要求，相关账号、数据和法律风险由使用者承担。完整内容见 [DISCLAIMER.md](DISCLAIMER.md)。
