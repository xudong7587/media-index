# MediaIndex 本地版部署速查

这份文档记录用户自用 NAS 版 MediaIndex 的固定路径和部署习惯，供后续 Codex 任务快速恢复上下文。不要在这里写入密码、Cookie、Token、API Key 或完整私钥。

## 固定位置

- 本机开发仓库：`D:\Documents\MediaIndex前端\media-index`
- 本机部署辅助目录：`D:\Documents\MediaIndex前端\.deploy`
- 自用版访问地址：`https://media.dunn.fun:666/`
- NAS SSH：`Sunnydunn@dunn.fun -p 12580`
- 远端部署目录：`/volume2/docker/media-index`
- 正式容器名：`media-index`
- 远端镜像命名：`media-index:<VERSION>`，例如 `media-index:0.5.1`
- 远端 Compose 文件：`/volume2/docker/media-index/docker-compose.yaml`
- 容器内应用端口：`8000`
- 常见宿主机端口：`38000`，公网访问由用户现有反向代理映射到 `https://media.dunn.fun:666/`
- 关键挂载：`/app/data` 保存配置、数据库和缓存；`/downloads` 保存 115 本地下载目录

## 用户习惯

日常开发按这个节奏处理：

1. 用户提出想法。
2. Codex 修改本地代码并做针对性验证。
3. Codex 部署到自用 NAS 版。
4. 用户在 `https://media.dunn.fun:666/` 实测。
5. 用户确认后，再同步 GitHub、走 PR/CI/合并或发布。

不要把“部署到本地版”理解成推送 GitHub；不要把“合并 PR”理解成 NAS 已部署。三者必须分开汇报。

## 部署前检查

在 `D:\Documents\MediaIndex前端\media-index` 先做：

```powershell
git status -sb
Get-Content -Encoding UTF8 .\VERSION
$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m unittest discover -s tests
pnpm --dir frontend build
```

如果本地 `.venv` 不存在，可按项目当时环境改用可用 Python，但不要为了部署引入无关依赖。前端构建使用仓库锁文件和 `pnpm --dir frontend build`。

## 打包原则

必须给 NAS 一个完整、干净、可复现的构建上下文。历史上出现过只增量上传少数文件，导致 NAS 构建目录缺 `frontend/public`，镜像与本地代码不一致，所以后续不要再用增量文件覆盖作为正式部署方式。

打包或 staging 时排除：

- `.git/`
- `.env`、`.env.*`
- `data/`
- `*.db`、`*.sqlite*`
- `.venv/`
- `.tmp/`
- `frontend/node_modules/`
- `frontend/dist/`
- 日志、缓存、临时包、真实密钥
- 部署同步到 NAS 正式目录时，还要排除远端运行态文件：`docker-compose.yaml`、`docker-compose.yml`、`.codex-deploy/`、`.deploy-*/`、`build-*/`、`backups/`

`docker-compose.bridge.yaml` 不是敏感文件，用户已说明不用特别排除；是否带入构建目录按当前任务需要决定。

推荐把源码包放在：

```text
D:\Documents\MediaIndex前端\.deploy\media-index-<VERSION>-<yyyymmdd-HHMMSS>-source.tar.gz
```

优先使用 `.tar.gz`，避免 ZIP 在 NAS 解压环境里把路径层级压扁。

## 远端流程

SSH 优先使用本机已有密钥：

```powershell
ssh -p 12580 Sunnydunn@dunn.fun
```

`Sunnydunn` 通常没有 Docker Socket 权限，Docker/Compose 操作需要 `sudo`。需要 sudo 密码时单独问用户，只通过标准输入传给远端命令，不写进仓库、日志或回复。

远端部署策略：

1. 在 `/volume2/docker/media-index` 下确认现有 Compose、数据目录和当前容器状态。
2. 把完整源码包上传并解到 `/tmp/media-index-deploy-<timestamp>` 这类独立临时目录。
3. 用 `rsync` 从临时目录同步源码到 `/volume2/docker/media-index`，但必须排除远端运行态文件，尤其不能覆盖 `docker-compose.yaml`、`data/`、`.env`、`backups/`、`build-*/` 和旧 `.deploy-*`。
4. 在正式目录构建本地镜像：`sudo docker build -t media-index:<VERSION> .`。
5. 确认远端 Compose 的 `media-index` 服务使用 `image: media-index:<VERSION>`，且 `pull_policy` 不是 `always`。自用 NAS 不应在部署时拉 `ghcr.io/xudong7587/media-index:latest`。
6. 确认远端 Compose 不写入会覆盖 `data/.env` 的应用配置默认值，尤其 `MEDIA_USER`、`MEDIA_PASS`、`QAS_BASE_URL`、`QAS_TOKEN`、`PANSOU_URL`。
7. 用远端 Compose 直接重建本地镜像：`sudo docker compose -f /volume2/docker/media-index/docker-compose.yaml up -d --force-recreate media-index`。
8. 切换失败时保留旧镜像和旧数据，优先回滚容器，不动 `/app/data`。

自用 NAS 版的 compose 是运行配置，不是公共发布模板。仓库根目录的 `docker-compose.yaml` 面向普通用户拉 GHCR 镜像，不能直接覆盖用户 NAS 上的 compose；否则会出现“本地镜像已构建成功，但 compose 又拉取旧 GHCR 镜像”的低效和错版问题。
登录、QAS、PanSou 等运行配置以远端 `data/.env` 为准；公共模板里的示例环境变量不能带到自用版正式容器。

远端常用检查：

```bash
sudo docker ps --filter name=media-index
sudo docker images 'media-index:*'
sudo docker logs --tail 100 media-index
sudo docker inspect media-index --format '{{.Config.Image}}'
```

如果需要检查应用版本，优先通过容器镜像标签、`/app/VERSION` 或页面实际响应确认。

## 部署后验证

至少确认：

- `media-index` 容器处于 running/healthy 状态。
- 正式容器镜像标签是本次目标版本。
- `https://media.dunn.fun:666/` 能打开。
- 登录页或主页静态资源正常，尤其 `frontend/public/assets/media-index-icon.png` 这类公共资源。
- 近期容器日志没有启动错误。
- 数据目录没有被重建或清空。

需要更深入验证时再检查数据库完整性、关键 API、追更/转存状态和通知，但不要在最终回复中泄露媒体标题、Cookie、Token 或 NAS 私密配置。

## 常见坑

- NAS SSH banner 会影响 `scp` 或协议型传输；如果再次出现，优先确认 banner 是否还在，再选择纯 `ssh` 原始字节流或稳定的 `.tar.gz` 上传方式。
- Windows 管道可能转码二进制流；不要用会改写字节的 PowerShell 文本管道传压缩包。
- NAS 上 Python/解压工具处理 ZIP 可能不可靠；用 `.tar.gz` 更稳。
- Windows 换行符可能破坏 Linux 启动脚本；Dockerfile 已清理 `docker-entrypoint.sh` 的 CRLF，修改 shell 脚本后仍需注意。
- 发布到 GitHub/GHCR 后，自用 NAS 不会自动更新；仍需单独部署和验证。
