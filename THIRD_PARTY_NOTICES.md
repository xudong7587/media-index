# 第三方组件声明

## MediaCoverGenerator 静态封面渲染器

MediaIndex 的“媒体库封面工坊”包含下列静态渲染器及其必要工具代码的
改编版本：

- 上游：[`wio-ki/MoviePilot-Plugins`](https://github.com/wio-ki/MoviePilot-Plugins)
- 组件路径：`plugins.v2/mediacovergenerator/style/style_static_1.py` 至
  `style_static_4.py`，以及对应的静态渲染工具。
- 许可证：GNU General Public License v3.0 (`GPL-3.0-only`)。
- 本仓库保留位置：`backend/app/third_party/mediacovergenerator/`。

仅移植静态封面生成路径；动画样式、MoviePilot 插件包装、定时器及其余
MoviePilot 运行时集成均未包含。为适配 MediaIndex，导入路径、日志接入和
Emby 图像读取入口有所调整；这些修改随本仓库在 GPL-3.0 下发布。

其中多海报静态布局的上游文件声明参考了
[`HappyQuQu/jellyfin-library-poster`](https://github.com/HappyQuQu/jellyfin-library-poster)；
该归属在源码注释中保留。

MediaIndex 不随镜像打包上游样式预览图或电影海报。渲染时仅临时读取用户
本人 Emby 媒体库已存在的海报，生成完成后临时文件立即删除。
