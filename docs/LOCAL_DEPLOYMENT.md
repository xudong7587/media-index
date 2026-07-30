# MediaIndex 自用 NAS 部署

本页是自用 NAS 的唯一运行手册。它不定义 GitHub 发布，也不定义 `MediaIndex-public` 的职责。

## 当前参数

- 自用版反代：`https://media.dunn.fun:666/`
- 内网地址：`http://192.168.11.239:38000`
- SSH：`media-index-nas` alias，实际 endpoint 为 `dunn.fun:12581`
- SSH 账户：`mediaindex-scp`，私钥由本机 SSH config 管理
- root 文件系统中的 staging：`/volume2/docker/media-index`
- SCP/SFTP 上传根目录：`/docker/media-index`（UGOS 将部署账户限制在共享文件夹视图；不要在 SCP 命令中写 `/volume2`）
- 自用容器：`media-index`
- 当前运行版本：`0.5.3`，已通过受限 SSH `status` 验证
- `MediaIndex-public`：独立容器，只确认 GitHub 正式镜像呈现

## SCP 基线状态：已完成

已于 `2026-07-30` 从公开 `0.5.3` 完成 SCP staging 基线重置。日常 A1/A2 部署现在可以上传变更文件并调用对应 reload；之后 staging 的 `VERSION` 会随开发变化，不再是就绪检查条件。

这是已验证事实，不是每个新会话都要重新检查的前置条件。`mediaindex-scp` 被故意禁止执行通用 SSH shell 命令；因此通过 SSH 执行 `test -f /volume2/...`、`ls /volume2/...` 失败，只代表该命令不被允许，**绝不代表 staging 文件不存在**。日常部署直接使用下方的 SCP 路径。

以下命令保留给未来更换 NAS 或 staging 再次损坏时使用：它将旧 staging 的源码移入可恢复归档，然后从当前运行的公开 `0.5.3` 容器复制干净基线。它不会重启或修改运行容器。

```sh
set -eu
APP_DIR="/volume2/docker/media-index"
ARCHIVE="$APP_DIR/.abandoned-0.5.4-$(date +%Y%m%d-%H%M%S)"
SERVICE="media-index"

mkdir -p "$ARCHIVE"
for item in backend frontend VERSION; do
  [ -e "$APP_DIR/$item" ] && mv "$APP_DIR/$item" "$ARCHIVE/"
done

mkdir -p "$APP_DIR/backend" "$APP_DIR/frontend/dist"
docker cp "$SERVICE:/app/backend/." "$APP_DIR/backend/"
docker cp "$SERVICE:/app/VERSION" "$APP_DIR/VERSION"
docker cp "$SERVICE:/app/frontend/." "$APP_DIR/frontend/dist/"

chown -R mediaindex-scp:users "$APP_DIR/backend" "$APP_DIR/frontend" "$APP_DIR/VERSION"
printf 'staging_version='
cat "$APP_DIR/VERSION"
```

预期输出为 `staging_version=0.5.3`。仅在未来重新执行此恢复操作且尚未确认输出时，禁止执行 `backend`、`frontend` 或 `all` reload；`status` 始终可以安全执行。

## 日常 SCP + Reload

部署用户只能上传文件和调用受限 reload，没有远程 shell、Docker 组权限或保存的 sudo 密码。UGOS 共享文件夹权限只授予 `docker`；staging 目录必须由 `mediaindex-scp:users` 管理。若 SCP 出现 `setstat` 或权限错误，立即停止部署并由 NAS root 修复 staging 所有权；不能把部分传输当作成功。

后端单文件示例：

```powershell
scp backend/app/services/example.py media-index-nas:/docker/media-index/backend/app/services/example.py
ssh -o BatchMode=yes media-index-nas "sudo -n /usr/local/sbin/media-index-reload backend"
```

前端：只在用户要看页面效果时运行 `pnpm --dir frontend build`，再上传 `frontend/dist` 中变更的产物并执行：

```powershell
ssh -o BatchMode=yes media-index-nas "sudo -n /usr/local/sbin/media-index-reload frontend"
```

只上传业务源码、`VERSION` 或前端构建产物。不得上传 `data/`、`downloads/`、`.env`、数据库、缓存、源码压缩包，或改动 compose。

状态检查：

```powershell
ssh -o BatchMode=yes media-index-nas "sudo -n /usr/local/sbin/media-index-reload status"
```

## 完整部署

当前没有验证过新 NAS 的完整 build/deploy 脚本。只有改动 Dockerfile、依赖、镜像布局，或轻量 reload 无法恢复时，才先确认完整部署方案和回退方式；小修一律不构建镜像。

## 换 NAS

换设备时更新本页的地址、alias、账户、staging 路径、容器名和 reload 权限；再验证 `status`、staging 版本、应用页面。开发 -> GitHub 发布 -> `MediaIndex-public` 的交付链不变。
