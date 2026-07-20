# MediaIndex 使用手册

MediaIndex 是面向个人 NAS 的媒体发现、转存和智能追更控制台。它负责从 TMDB 获取媒体和播出信息，通过 PanSou 搜索候选资源，再交给 quark-auto-save（QAS）读取真实文件、转存和重命名。

## 部署方式

### 只部署 MediaIndex

1. 下载仓库根目录的 `docker-compose.yaml`。
2. 修改 `MEDIA_USER` 和 `MEDIA_PASS`，不要使用示例密码。
3. 运行 `docker compose up -d`。
4. 访问 `http://NAS_IP:38000`。
5. 在 MediaIndex 设置页填写已有 PanSou、QAS 的可访问地址和 QAS Token。

若 PanSou/QAS 不在同一 Docker 网络，请填写 MediaIndex 容器能访问的地址，不要填容器自身的 `127.0.0.1`。

### 一套 Compose 部署三个服务

`docker-compose.yaml` 已包含 PanSou 和 QAS 服务，两段默认用 `#` 注释。

1. 删除 `pansou` 整段每行开头的 `# `。
2. 删除 `quark-auto-save` 整段每行开头的 `# `。
3. 修改 MediaIndex 的 `MEDIA_PASS` 和 QAS 的 `WEBUI_PASSWORD`。
4. 执行：

   ```bash
   docker compose up -d
   ```

5. 确认三个入口可访问：

   | 服务 | 默认地址 | 用途 |
   | --- | --- | --- |
   | MediaIndex | `http://NAS_IP:38000` | 主控制台 |
   | QAS | `http://NAS_IP:5005` | 夸克 Cookie、转存和 API Token |
   | PanSou | `http://NAS_IP:8888` | 资源搜索 API |

MediaIndex 在这套网络中默认访问 `http://quark-auto-save:5005` 和 `http://pansou:8888`，无需改成 NAS IP。

## 首次配置

### 1. 配置 QAS

1. 登录 QAS。
2. 在 QAS 中填写并验证自己的夸克 Cookie。
3. 在 QAS 页面找到 **API → Token** 并复制。

QAS Token 与 QAS 管理账号、密码有关，修改 QAS 登录信息后需要重新复制并更新 MediaIndex 中的 Token。不要把真实 Token 提交到 Git。

### 2. 配置 MediaIndex

进入 **设置 → 基础设置**，填写并保存：

- TMDB API Key：用于搜索媒体和获取播出日期。
- QAS 地址：同套 Compose 保持 `http://quark-auto-save:5005`。
- QAS Token：粘贴上一步复制的 Token。
- PanSou 地址：同套 Compose 保持 `http://pansou:8888`。
- 网盘和本地根路径，以及电影、剧集和综艺的分类路径。

使用页面中的 PanSou 和 QAS 测试功能确认连接成功。QAS 自带搜索与 MediaIndex 的 PanSou 搜索是两条不同链路；若希望候选来源和判断都由 MediaIndex 控制，可在设置页关闭“QAS 自带搜索”。

## 日常使用

### 发现和单次转存

1. 在发现或搜索中选择影片。
2. 选择保存到网盘或本地。
3. MediaIndex 搜索候选、由 QAS 读取分享中的真实文件，然后生成标准化名称并转存。
4. 证据充足时自动执行；标题、季、年份或集数无法安全确认时进入待确认。

### 智能追更

1. 为剧集或综艺创建追更任务。
2. 选择目标季、保存位置和每个任务的追更时间。
3. 到达 TMDB 播出日和设定时间后，MediaIndex 会先扫描网盘中已存集数。
4. 只对已播出且网盘缺失的集数搜索新资源。若 PanSou 的候选只更新到已存集，任务会显示当前无需更新并稍后重试，不生成无效待确认。

“立即检查”不会提前搜索未播出集。它会跳过当天的时间门槛，但仍以 TMDB 播出日为边界。

### 待确认

待确认代表系统已找到可能的资源，但无法仅凭标题和文件安全地确定。处理时：

- 先核对候选标题、年份、季和实际文件。
- 可选择特定文件后继续，也可删除不相关候选并重新搜索。
- 不要仅因文件名出现一个集数就确认明显无关的资源。

## 通知和企业微信

网页内通知显示在右上角小铃铛。在 **设置 → 通知设置** 中可选配置 Telegram、企业微信群机器人或企业微信自建应用。启用企业微信回调后，可在手机端搜索资源、查看状态并用编号处理待确认。

外部图文通知需要在通知设置中填写外部渠道可访问的 MediaIndex 公网地址，并通过 HTTPS 反向代理发布。

## 更新、备份和恢复

更新：

```bash
docker compose pull
docker compose up -d
```

备份前停止服务，然后备份以下目录：

- `./data`：MediaIndex 配置、SQLite 数据库和缓存。
- `./quark-auto-save/config`：QAS Cookie、任务和配置。
- `./quark-auto-save/media`：仅在使用 QAS 相关媒体插件时需要。

恢复时把备份目录和 `docker-compose.yaml` 放回同一部署目录，然后重新执行 `docker compose up -d`。

## 常见问题

### MediaIndex 显示 QAS 未配置

确认 QAS Token 已从 QAS 页面复制到 MediaIndex 并保存。只有 QAS 地址而没有 Token 时，MediaIndex 会保持未配置状态。

### 容器之间无法连接

同套 Compose 必须让三个服务都加入 `media-index-stack` 网络。若使用独立 Compose，可让服务加入同一外部网络，或在 MediaIndex 中使用可从容器内访问的 NAS IP 和宿主机端口。

### 修改 QAS 密码后转存失败

QAS API Token 会随登录信息变化。重新登录 QAS，复制新 Token，再到 MediaIndex 中更新并保存。

## 安全提示

- MediaIndex 和 QAS 都必须使用强密码。
- TMDB Key、QAS Token、夸克 Cookie 和通知凭据都不得提交到 Git。
- 建议仅在内网、VPN 或可信 HTTPS 反向代理后使用。
- 项目不提供任何资源、Cookie 或网盘账号，使用者需自行确保使用行为合法合规。
