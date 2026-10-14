# 115 cloud video protocol v1

## 2026-10-14 实测修复（尚未发布）

用户随后明确授权发布 0.8.5 并将 NAS 升级到 GitHub 构建的 latest，正式升级替代临时补丁；以发行和容器验证回执确认完成。

Primary module: cloud；B lane。基于 0.8.4 / main `6226a6d`，分支 `codex/115-cloud-query-fix`。用户另行授权已登录 NAS 和 USB 手机诊断。

真实 `files/get_info` 返回 `fid`/`pc`，原代码漏读 `pc`；`files/video` 返回的是需要 Cookie 的官方主清单入口，而不是免认证 CDN 清单。现已兼容字段，并且只向由已核对 pickcode 构造、与返回值完全一致的 `https://115.com/api/video/m3u8/{pickcode}.m3u8` 附加 Cookie/Referer。跳转、其它路径、其它文件、子域及 CDN 均不继承 Cookie。保持 HTTPS 和原文件身份校验。

NAS 使用既有登录态实测得到 3840×2160 / 7.5 Mbps 和 1920×1080 / 3.0 Mbps；两个子清单为完整 VOD，分片 Range 返回 206。手机 dev36 已验证 NAS 代理的两档播放和切换；Wi-Fi 对该 CDN 的 TLS 连接重置，用户切换移动数据后两档直连均正常播放，视频不经 NAS。1080p 切换出现过一次响应头前 EOF，手动重试恢复，配套客户端修复首帧自动重试。没有让 SunnyTV 登录 115 或取得 Cookie。

验证：42 个定向测试通过；全套 1523 passed、2 skipped、58 subtests passed。只改云端客户端及测试，无共享核心、数据库、配置或 API 结构变更；STRM/签名、Emby、原下载链路和 NAS FFmpeg 协议不变。NAS 容器中已应用有备份的临时修复并重启；容器重建会丢失，正式镜像尚未发布。

以下为 dev36 首次交付时的协议说明与历史验证记录；当前实测状态以上述更新为准。

2026-10-13，MediaIndex 0.8.4，基于 main `3409aa6` / 0.8.3，分支 `codex/115-cloud-playback`。配套 SunnyTV dev36 基于 main `4546c74`。用户已授权 Git 发布，最终发行状态以 GitHub CI/Release 为准；NAS 服务仍由用户手动升级。

## 行为和授权

复用现有 asset token，验证 token 后精确映射 `provider=p115` 的 `file_id`。固定 `files/get_info` 核对文件并取得 pickcode，再调用 `files/video?local=0` 查询主清单。此请求可能触发 115 云端准备，因此只由用户显式查询/选择触发。没有付费加速、云盘删除/移动/重命名、数据库迁移或配置格式修改。

API 与媒体统一使用调用设备的 UA。账号 Cookie 仅发往固定 API 和上述精确匹配的官方主清单入口，不转发给子清单或 CDN。HTTPS 域名白名单、逐跳校验、最多四次重定向；清单中受支持的 HTTP 地址仅升级 TLS，失败不降级。清单上限 2 MiB、最多 32 档；会话最多 32 个、每会话最多 16384 资源，闲置 2 小时/绝对寿命 8 小时。

## API

| 方法和路径 | 输入 | 输出 |
| --- | --- | --- |
| POST `/api/cloud-video/discover` | JSON `assetToken` | `protocol=mediaindex-cloud-video-v1`、`variants`（id/width/height/bandwidth/label） |
| POST `/api/cloud-video/sessions` | JSON `assetToken`, `variantId`, 可选 `delivery`（默认 direct，可选 proxy） | protocol、sessionId、sessionToken、相对 playlistUrl、variant、seekMode=hls-vod、实际 delivery |
| GET `/api/cloud-video/sessions/{sid}/index.m3u8?st=…` | 会话凭据及同一 UA | 只包含选择档位的重写主清单 |
| GET `/api/cloud-video/sessions/{sid}/resources/{rid}?st=…` | 会话凭据及同一 UA，可带单 Range | 重写子清单，或流式媒体/16 字节 AES 密钥 |
| DELETE `/api/cloud-video/sessions/{sid}?st=…` | 会话凭据及同一 UA | 204 |

每个网关资源请求再次检查 asset 授权。默认 direct 模式的子清单包含经校验的短期 CDN 视频、音频和初始化段地址，播放器直接读取；proxy 模式的全部资源地址重写回网关。两种模式都不返回账号 Cookie，资源 ID 只在会话内有效，不接受调用者提供任意代理 URL。响应不缓存，网关访问日志对 `st` 脱敏。外部反向代理也应避免记录完整查询参数。已下发的直连 CDN 地址受 115 自身有效期限制，网关撤销会话无法立即撤销这些地址。

主清单保留音频/字幕 rendition，重写 AES-128 identity 密钥为网关地址。拒绝不支持的加密、动态 URI、非完整 VOD。直连模式保留 BYTERANGE 和签名编码，Range 由播放器向 CDN 发送；代理模式保留上游 200/206 语义。与 FFmpeg 会话、暂停、续租独立。默认只占用少量查询、清单及密钥带宽，代理模式才转发视频主体；不自动回退代理。

## 模块与兼容

- 修改：backend cloud 客户端/服务/API；main 和 playback_main 注册路由；playback_optimizer 网关日志脱敏；新增模拟测试。
- 共享核心：仅入口路由及日志脱敏扩展；既有播放 token、STRM 签名、下载、扫描及转码协议不变。
- 数据库/配置：无迁移，使用既有 `p115_cookie`；无新依赖。
- 当前会话是进程内状态，要求单 worker 或粘性路由；重启需重新选档。尚未实现跨进程共享或签名流自动续期。

## 测试与限制

`PYTHONPATH=backend;. python -m pytest tests -q --disable-warnings`：1514 passed、2 skipped、58 subtests passed。包括 asset/UA 授权、凭据隔离、清单改写、直连不读取视频字节、显式代理、范围请求、跳转拒绝、资源上限及会话清理等合成测试；现有播放/115/转码回归通过。

SunnyTV 侧 Android 编译、112 个 Gradle 单元测试、172 个纯 Kotlin 契约及 API 30 模拟器清晰度/面板集成验证通过。没有真实云端媒体播放证明。

本机一次只读账号查询返回登录过期 `990001`；用户要求暂不登录。真实主清单结构、CDN HTTPS、可用档位、会员权限、跨出口 IP 和长时间播放仍待有效登录态后验收。未部署 NAS 或修改运行中服务。
