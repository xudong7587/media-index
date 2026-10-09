# 播放优化插件（v0.7.38-rc.2 候选）

2026-10-08。本轮不做 MoviePilot 插件兼容，不下载或执行第三方插件。

## 使用入口

侧栏「插件」管理播放优化开关；「全局设置 → 使用手册」集中显示手册。
旧 `#guide` 和 `#settings-guide` 地址仍有效。
开关保存到数据库所在持久化目录的 `plugins/state.json`，主服务与播放服务须挂载同一目录。
旧部署已显式配置 worker 时保持启用；未配置时默认关闭。
停用阻止新会话，已有会话自然结束，原画 STRM / 302 合同不变。

## 部署边界

主镜像不包含 FFmpeg；独立 worker 容器执行 H.264 / AAC HLS 转码。
参考 `plugins/playback_optimizer/worker/compose.example.yaml` 配置 worker 地址和内部密钥。
主镜像候选为 `ghcr.io/xudong7587/media-index:0.7.38-rc.2`；独立 worker 为
`ghcr.io/xudong7587/media-index-transcoder:0.1.0-rc.2`（linux/amd64）。
主镜像仍构建 amd64 / arm64；当前 worker GPU 驱动栈只支持 x86 Intel / AMD VAAPI。
两个镜像分别发版，worker 通过 `transcoder-v*` 标签构建，主镜像更新不重复构建 worker。
worker 端口仅供容器内部通信；播放器访问 MediaIndex 播放端口的 `/api/transcode/*`。
外网必须把这些路径转发到实际启用插件的实例，并保持 HTTPS；不能仍指向另一套旧实例。
不额外把 worker 暴露到公网，不通过 Emby 302 插件转发 HLS 分片。

可选原片缓存配置在 **MediaIndex 播放网关**：

```
TRANSCODE_SOURCE_CACHE_DIR=/app/data/playback-cache
TRANSCODE_SOURCE_CACHE_BYTES=8589934592
```

该目录需挂载独立可写磁盘，不能复用 worker 的 512 MiB 临时分片缓存。
只有独立播放端口的网关进程拥有缓存；管理端口不执行缓存填充、预读或提供缓存原片入口。
未配置目录时不启用原片缓存。首期缓存目录只允许一个网关进程拥有；
不得让多个容器或多个 Uvicorn worker 共享同一个原片缓存目录。
4 MiB 原片分块按资产身份、版本和账户散列命名，LRU 限额淘汰；
每次读取仍校验签名授权，缓存命中不绕过资产撤销。
仅缓存转码网关实际读取的范围，不更改网盘文件，不生成新媒体库条目。
需要保持原片编码的播放器，也可显式使用 `/api/transcode/buffer/source/{assetToken}` 作为 NAS 缓存中转入口。
该入口不执行 FFmpeg、不降低码率；原有 `/api/play/{assetToken}` 仍走 302。
SunnyTV 本轮画质档位接入的是转码入口，没有把默认原画自动改成 NAS 中转。
暂停时按需预读最多 64 MiB，最多两个任务排队、一个执行；不下载整部影片。
缓存的原片内容、磁盘访问权限与容量由 NAS 管理员管理。

## 画质与提示

保持原画默认走既有 302。转码可选 4K / 2160P（20、10 Mbps）、
2K / 1440P（10、6 Mbps）、1K / 1080P（8、4 Mbps）、0.75K / 720P（4、2 Mbps）。
旧分辨率 ID 和默认码率继续兼容；旧 worker 不声明码率时只展示其旧选项。
输出按原比例限制分辨率，不放大低分辨率源；码率是编码目标，不保证每秒恒定。

NAS 根据实际原片读取样本估算持续速度，至少两个块且累计耗时两秒后才给出提示。
用平均原片码率估算缓存时长，VBR、拖动、音轨与网络波动都会造成误差。
播放器另用 Media3 实际传输样本提示客户端接收速度不足。
115 → NAS 不足时，降低转码输出码率不能减少原片读取需求；
NAS → 客户端不足时，低码率转码能降低家庭上行与移动数据消耗。
暂停预读有容量和时间上限，不能承诺一两分钟后整部持续流畅。

## 本轮模块和验收

Primary：shared-core，提供仅内置白名单的插件注册、鉴权管理与状态文件。
Changed：STRM（缓存和转码入口）、settings（手册）、应用装配（插件入口）。
DB schema：无变化。旧配置：兼容。新增 API：鉴权 `/api/plugins`；
签名资产授权 `/api/transcode/buffer/*`；转码请求新增可选 `videoBitrate`。
没有第三方代码安装、市场、MP SDK 或仓库整体迁移。

本地代码与模拟上游测试不等于 NAS 集成验收。
待实机确认：8K AV1 起播、暂停缓存、拖动、外网代理、电视演员下翻、APK 系统安装。
2026-10-08 用户明确授权发布 GitHub RC，并通过现有 NAS SSH 更新正式实例进行实测。
发布和部署结果以实际 CI 与 NAS 验证记录为准。

### 交付检查

- Lane：B；Primary module：shared-core。
- Changed modules：STRM、settings、应用装配；Shared/Core changed：Yes，插件状态必须同时被管理端和播放端读取。
- Behavior changed：Yes，显式启用的播放优化和缓存；默认原画保持原入口。
- Database changed：No；Config / environment changed：Yes，新增可选缓存目录及限额、独立插件状态文件。
- API contract changed：Yes，新增插件管理和缓存接口、可选码率；旧调用参数和画质 ID 保持兼容。
- Tests run：完整后端 1384 passed、2 skipped（既有跳过）、58 subtests；前端 TypeScript / Vite 构建通过。
- Local browser acceptance：隔离的 127.0.0.1:5186 插件/手册预览，真实插件 API 启停和刷新持久化通过；其他业务 API 使用预览空数据，不代表全系统集成验收。
- SunnyTV：97 单元测试、172 核心契约通过；Android 界面测试编译、APK 构建和 lint 通过（0 errors，35 warnings）。
- Known risks：缓存仅一个播放网关进程拥有；VBR 字节位置和等待时间为估算；NAS GPU / 外网 / TV / 系统安装未实机验证；HDR tone mapping 仍未支持。
- Release / NAS deployment：No。本轮 MoviePilot 兼容与第三方插件执行：No。

## rc.2 插件包与字幕

插件代码位于 plugins/playback_optimizer：plugin.json、gateway、worker。Compose 部署执行容器，主服务页面控制业务启停，无 Docker 管理权限；核心只登记固定白名单清单。旧导入/API 保留兼容入口。

VOD 转码自动烧录默认内嵌字幕。PGS/DVD/DVB 保留字幕图片外观；ASS/SSA 用 libass 渲染并加载内嵌字体，字体附件限16个、单个8MiB、总计32MiB，附件原文件名不作为路径。未内嵌且容器未安装的字体会回退，不能承诺字体完全一致。外挂 Emby 字幕尚未接入。字幕不支持或准备失败时明确失败，不静默丢字幕。

文本字幕按请求批次提取，字幕绝对时间与批次视频时间互相对齐；向前预读60秒，持续时间异常长且起点早于预读范围的字幕事件仍是已知边界。文字渲染或位图叠加需要 CPU 处理像素，随后仍由 GPU 编码；需实测大分辨率负载。带字幕的 live 请求暂不支持，客户端用 HLS VOD。

验证：本地后端1389 passed、2既有skip、58subtests。NAS 指定影片默认中文PGS轨的GPU叠加测试退出0；合成ASS测试提取10/70秒事件后绝对时间保留，70秒拖动后的libass渲染输出1帧。尚未将这些检查等同整片或字体视觉验收。
# RC3：HDR 转 SDR

PQ / HLG 源使用 GPU 解码、保留 10-bit 精度缩放，随后通过 zscale / Hable 色调映射转换成 BT.709 SDR，再上传 GPU 编码 H.264。色调映射在 CPU 上执行，滤镜线程限制为 2；不假设不同驱动都支持 tonemap_vaapi。输出清除 HDR 静态元数据，保留原有字幕烧录、码率限制、VOD 拖动与原画入口。

杜比视界 profile 5 暂不支持，继续明确拒绝；不将其当普通 HDR10 转换。原画播放不受此限制。4K HDR 的实际转码速度、外网首次读取以及颜色观感仍须终端验收，不能根据滤镜存在宣称全硬件转码。

网关只翻译已知错误，SunnyTV dev35.3 显示明确的格式 / GPU / 字幕不支持提示，未知内部诊断仍不下发客户端。
