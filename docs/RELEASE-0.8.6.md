# MediaIndex v0.8.6

移除 NAS 本地转码服务、原片缓存中转、服务页面和手册入口，以及独立 FFmpeg/GPU 转码容器的代码与构建工作流。主镜像不再包含转码插件目录。

保留 STRM 生成、原片 302／代理播放、Emby 反代和 115 云端清晰度／CDN 播放。115 播放会话日志仍脱敏，不再依赖转码模块。数据库无需迁移。

升级已有双容器部署时，删除 Compose 中独立的 mediaindex-transcoder 服务（部分部署命名为 transcoder）和主服务 TRANSCODE_* 配置；如果主服务 depends_on 引用了该服务，也需移除该引用。已运行的旧容器不会被新版主镜像自动停止，可用更新后的 Compose 执行 docker compose up -d --remove-orphans，确认只清理该项目的旧转码容器。主服务端口、数据挂载和 STRM 配置保留。

旧 /api/transcode 和 /api/plugins 接口已退役；客户端应使用原片或 115 云端播放。更新本次 GitHub 版本不自动修改 NAS Compose，也不删除已有缓存和状态文件。
