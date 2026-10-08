# 内置功能插件

每个功能包放在 `plugins/<plugin_name>/`，包含只读 `plugin.json`、网关代码、可选执行器与部署示例。
核心只注册经代码审查的白名单插件，不扫描或执行用户下载的第三方 Python。
当前只迁移播放优化；STRM 生成、多网盘同步仍使用既有模块，不假称迁移完成。

`playback_optimizer/gateway` 拥有转码入口、传输和缓存；`worker` 拥有 FFmpeg、GPU 与字幕渲染。
旧 `app.api.transcode`、`app.services.transcode` 和 `transcoder` import 仅为兼容入口。

Compose 管理执行容器生命周期；MediaIndex「插件」页面管理业务启停。
停用阻止新会话，已建会话自然结束。不开启 Docker socket，不在主镜像安装 FFmpeg。
插件清单是元数据，不含可执行入口、下载 URL 或权限提权指令。
