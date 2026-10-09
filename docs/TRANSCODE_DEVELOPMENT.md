# MediaIndex 独立转码服务开发记录

2026-09-30。开发基线：正式 v0.7.34（908dc95）；分支 `codex/transcode-worker`。
本地候选实现，尚未发布或部署到 NAS。

## 产品约定

Emby 继续管理媒体库、元数据和观看进度。原画沿用既有签名 STRM 和302直连115。
选择清晰度后，MediaIndex 管理会话，独立容器读取源视频并输出临时 HLS；不生成新的媒体条目、不上传云盘、不保存完整清晰度副本。

| 显示名称（用户指定） | API标识 | 输出上限 | 视频码率上限 |
| --- | --- | --- | --- |
| 原画 | original（客户端路径） | 原片 | 原片 |
| 4K / 2160P | 4k | 3840×2160 | 15 Mbps |
| 2K / 1440P | 1440p | 2560×1440 | 10 Mbps |
| 1K / 1080P | 1080p | 1920×1080 | 8 Mbps |
| 0.75K / 720P | 720p | 1280×720 | 4 Mbps |

名称是界面标签，不能当作接口协议。保持原始宽高比；两个方向均不超过源尺寸和选项上限，并对齐偶数。1080P原片选择4K仍输出1080P，可以转换编码以兼容电视。输出 H.264 High、8bit NV12、AAC双声道192kbps；VOD 自动选择默认（其次 forced/第一条）内嵌字幕并烧录：PGS/DVD/DVB 图形字幕保留其图像外观，ASS/SSA 保留样式和特效并加载受限字体附件，其它支持的文本字幕转为 ASS；音频仍选择第一条音轨。HDR色调映射尚未实现，拒绝已识别的PQ/HLG来源，不假称输出保留HDR。

## 服务分工与部署

- 主镜像不添加 FFmpeg 或GPU驱动。仅新增可选HTTP网关和播放应用路由。
- `plugins/playback_optimizer/worker/` 自成构建上下文，独立镜像、独立版本；包含FFmpeg、Intel及AMD VAAPI用户态驱动、小型API服务。运行时枚举映射的render节点，读取厂商并通过vainfo实际初始化，确认源解码编码能力后启用；不会修改宿主内核驱动。Intel使用隔离的新版iHD栈，AMD使用Mesa/radeonsi。NVIDIA后端尚未实现，不会误报支持；设备权限或宿主驱动不兼容时返回不可用。
- `plugins/playback_optimizer/worker/compose.example.yaml` 是合并配置示例，不是可以替换现有服务的完整Compose文件。服务名、内部端口按实际部署调整；不发布worker端口。
- 主容器：`TRANSCODE_WORKER_URL=http://transcoder:8098`，`TRANSCODE_WORKER_KEY`。
- worker：相同密钥，`MEDIAINDEX_SOURCE_BASE=http://mediaindex:8097`，默认 `TRANSCODE_MAX_SESSIONS=1`。
- 密钥必须32至128个URL安全字符，由用户部署时生成，不写入Git。映射 `/dev/dri`（可选 `TRANSCODE_RENDER_DEVICE` 指定一个 render 节点），补充设备所属组数字GID，使用非root用户10002。
- 缓存使用512MiB tmpfs，单会话超过384MiB回收；默认一个会话。提高并发时必须同时重新评估tmpfs、内存和GPU预算。
- 容器只读根文件系统，独立缓存，不挂载媒体目录、115 Cookie、Emby配置或Docker socket。

## 客户端API（播放入口端口与主API均注册）

`GET /api/transcode/capabilities`：未配置或故障返回 `available:false`。可用响应带 `protocol:mediaindex-transcode-v1` 和稳定profile列表；`hardwareValidated:false`明确不把设备存在当作解码能力验收。

`POST /api/transcode/sessions`：JSON `assetToken`、`profile`、`startPositionMs`、`delivery`（`vod`或`live`，省略保持旧的`live`行为）。SunnyTV明确申请`vod`。
先验证现有签名播放令牌、资产状态与来源；首期仅115。客户端不能提交任意URL或FFmpeg参数。
返回 `sessionId`、`sessionToken`、相对 `playlistUrl`、实际宽高、源 `durationMs`、`startPositionMs`、`heartbeatSeconds:30`。VOD返回`seekMode:hls-vod`，live返回`seekMode:restart-session`。

`GET /api/transcode/sessions/{id}?st=...`：状态与续租。
`POST /api/transcode/sessions/{id}/pause?st=...`：VOD没有持续转码进程，当前最多16秒媒体范围的批次允许完成；live冻结Linux子进程，继续时从暂停位置建立新会话。
`DELETE /api/transcode/sessions/{id}?st=...`：停止子进程并清理缓存。
`GET /api/transcode/sessions/{id}/index.m3u8?st=...` 及分片路径：播放网关代理worker响应，不经过原片302路由。

worker所有路由要求内部Bearer密钥；会话路由另要求会话凭据。播放列表为每个子列表/分片补齐会话凭据。错误响应不透传上游URL、Cookie或FFmpeg日志；访问日志脱敏source路径与会话query。内部来源路径 `/api/transcode/source/{assetToken}` 要求worker密钥，复用现有播放服务的范围读取和失效直链刷新，不将内部密钥转发给115。

## HLS通用接入与边界

单清晰度会话只编码所选一路。额外 `profile:adaptive` 提供标准多清晰度主列表，列出实际 `RESOLUTION` 与 `BANDWIDTH`。VOD按播放器请求的档位生成对齐片段；live使用一次解码、四路同时编码。标准参考：[RFC 8216](https://www.rfc-editor.org/rfc/rfc8216.html)。

HLS播放器可以消费返回的播放链接；是否显示“1080P”或完整名称由播放器决定。绿联影视中心与Moonfin的清晰度菜单尚未实测，不宣称现有按钮自动连接本服务。客户端需取得会话链接；既有STRM不会被静默替换。

`delivery:vod` 提供包含整片时长的VOD列表，4秒分片、每批最多4片；创建会话和读取列表只探测元数据，请求分片才启动GPU。播放器可以使用原生HLS全片拖动，不需要重建会话。跳转或切换档位终止旧批次；缓存命中复用，缓存超过96MiB时淘汰旧片，不保存整片转码副本。输出统一30 FPS，每批带独立帧并在批次边界标记不连续，保留源时间偏移；尾帧补齐后按目标时长裁剪。此模式暂限24小时以内片源。

VOD会话一小时无访问后回收；暂停后再次访问会续租，超过一小时需重新取得会话链接。每个会话只运行一个批次编码进程，同时请求不同批次/档位可能返回409，待实际播放器兼容验收。稳定STRM转码入口尚未实现。旧`live`仍为约48秒滚动窗口，SunnyTV遇到此旧模式时继续通过重建会话完成跳转。

## 生命周期和验证

会话创建包含并发预约，探测失败释放名额。探测20秒预算，媒体读取15秒超时，等待首个文件25秒；失败不无限重试。live闲置90秒、VOD闲置一小时回收；每5秒清理过期、live失败或超额缓存，容器重启只清除自己的UUID缓存目录。正常编码结束保留末尾分片至过期，避免影片结束前被删掉。

本地验证涵盖签名令牌先验证、来源访问密钥、会话隔离、路径白名单、滚动片段凭据、主列表子列表凭据、并发预约、失败释放、结束保留与过期回收、不放大、日志脱敏、暂停/终止和VAAPI命令；新增VOD完整时长、按需启动、目标批次、缓存复用、取消旧批次与一小时回收测试。完整后端回归1350项通过、2项既有跳过、58个subtests通过；随后补充网关live/VOD参数透传定向回归。SunnyTV debug构建、JUnit89项通过，lint为0错误/31项既有警告；先前Kotlin契约172项通过。

补充自动硬件探测后的转码定向测试28项通过，含Intel/AMD选择、驱动初始化失败、仅解码设备、不支持的厂商、来源中止后连接释放及错误日志脱敏；AMD使用模拟探测结果，尚无实体AMD验收。两个仓库`git diff --check`通过。

`scripts/validate_transcode_vod.py`在本机真实调用软件FFmpeg，使用24、29.97、30、60 FPS合成片源，三批9片完整解码975帧，检查跨批次PTS、精确尾片时长及音频总时长。此脚本明确替换硬件解码/编码，不属于VAAPI或NAS验收；工具包仅安装在忽略的`.tmp/transcode-tools`。

本机无Docker CLI、Linux render设备或连接的Android设备。2026-09-30经用户授权，已在NAS部署独立测试网关（38021）及不公开端口的worker，使用现有配置和数据库副本，不启动主应用调度器。宿主Intel Wildcat Lake GPU的旧版容器驱动不能初始化，换用隔离的Intel媒体驱动26.2.4后，vainfo确认AV1/H.264/HEVC/VP9解码及H.264编码可用。真实8K AV1来源已分别输出1080P（1920×1080）和4K（3840×2160）首片及160秒跳转分片，完整时长11701790毫秒，VOD列表和停止清理通过。首片分别约4.24秒、4.55秒，跳转首片约6.77秒、8.58秒。早先出现的115上游403在增加探测/跳转提前中止时的上游连接释放后，本轮复测未再出现；不以一次通过保证长期稳定。随后4K前36秒共9片跨三个批次连续读取及160秒跳转通过（测试约38.85秒含跳转），实际分片由FFprobe确认H.264 + AAC及正确尺寸。四路实时吞吐、整片连续播放和实体电视仍待验证。测试版SunnyTV dev33仅将转码API编译时定向至NAS测试网关（`mediaindexTranscodeTestOrigin`）；正常构建此属性为空，仍使用原STRM服务origin。原画链接不受该测试定向影响。当前SunnyTV只自动识别无query的 `/api/play/{token}` 稳定入口；其他反代路径需显式接入，不猜测CDN来源。

## 模块交付字段

- Lane B；Primary module：strm。
- Changed modules：strm、media-server播放应用注册、settings环境配置契约；另修改SunnyTV的source/transcode与feature/player。
- Shared/Core：仅main.py路由注册及新增来源路径诊断脱敏，因两个应用均须暴露同一公共接口；未改变其他业务API。
- 数据库：无结构或媒体映射变更。
- 配置/API：上述可选环境变量与新增 `/api/transcode`；默认不启用。
- 兼容：原片302、既有签名STRM、Emby路由和云盘文件保持原行为；没有新增后台自动转码。
- 人工验收：播放器选项、切换、绝对进度、暂停/继续、全片拖动和实体电视起播仍需端到端验证。

## 2026-10-08 main 对齐

转码工作区 `codex/transcode-worker` 已快进至 `github/main` @ `dbc4f2c`（v0.7.37），随后恢复全部转码未提交改动；既有调试覆盖层和本地配置不受影响。同步后转码定向28项通过，无数据库结构变更，未发布或更新NAS。

SunnyTV整合工作区：`D:/Documents/ChatGPT/SunnyTV-transcode-main`，分支 `codex/transcode-main-alignment`，基线main @ `5f7ca4c`（dev34.3）。保留本地音频解码模块及main播放器修复，再整合原dev33 HLS转码逻辑；当前默认没有NAS测试origin覆盖。旧dev33已交付的NAS测试部署仍为历史验收对象，不能把旧结果直接当成新main整合版本的电视验收。
