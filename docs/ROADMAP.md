# MediaIndex 开发规划

> 本文只记录尚未实现或尚未发布的产品规划。现役架构以
> [`ARCHITECTURE.md`](ARCHITECTURE.md) 和代码为准。

## 近期：115 原生 Provider 收尾

- 认证入口保留两种简便方式：
  - 用户直接粘贴包含 `UID`、`CID`、`SEID` 的 115 Cookie；
  - 用户填写 MoviePilot 后端地址和 API Key，从 `P115StrmHelper` 安全导入 Cookie。
- 设置页在 Cookie 字段旁提供圆形信息按钮，以弹窗简要说明 Cookie 获取方式，并链接到
  [OpenList 115 文档](https://docs.openlist.team/zh/guide/drivers/115)。
- MoviePilot 只作为可选凭据导入源和用户自己的 STRM 后处理器；MediaIndex 的验链、筛选、
  改名、转存和结果确认不依赖 MoviePilot。
- 同时启用 QAS 与 115 时，按 `provider × season` 创建独立子任务。一个 Provider 失败不得
  阻止另一个 Provider 成功转存；批次最终汇总成功、失败和待确认项。

## 后续：115 独立扫码与官方授权

- 增加 MediaIndex 内置的 115 扫码登录，不要求用户部署 MoviePilot 或 OpenList。
- 扫码获得的 Cookie 与手工 Cookie 使用同一加密/脱敏存储边界，二维码会话应短期有效、可取消，
  且不得把 Cookie 返回浏览器或写入日志。
- 评估 115 官方开放平台 OAuth。具备稳定的应用凭据、授权回调和 Token 刷新方案后，优先使用
  Access Token/Refresh Token，Cookie 后端保留为兼容方式。
- 不把 OpenList 设为运行依赖；只参考其用户指引和公开实现边界。

## 后续：Bark 通知渠道

- 在“设置 → 通知设置”增加 Bark，参考 [Bark 官方说明](https://bark.day.app/#/?id=bark)。
- 支持填写 Bark 服务地址或完整推送地址、设备 Key，并提供测试通知。
- Bark 与 Telegram、企业微信共用现有站内通知、失败重试、启用时间和敏感配置边界。
- 转存成功、部分成功、失败、待确认、愿望单和追更事件均可按统一通知模型推送。
- Key 只保存在服务端；状态 API 只返回“是否已配置”。

## 后续：Emby 联动与播放跳转

- 在设置中增加 Emby 开关、服务器地址和 API Key，并提供只读连接测试。
- 转存成功后请求 Emby 刷新对应媒体库；刷新操作必须异步，不得把 Emby 故障误判为网盘转存失败。
- 使用 TMDB ID、媒体类型、季集号和最终规范文件名查询 Emby 条目，避免只按标题模糊命中。
- 成功找到唯一 Emby 条目后，通知图文卡片的点击链接直接指向该媒体的 Emby 详情/播放页面。
- Emby 尚未扫描到文件时，通知先保留 MediaIndex 任务链接，并在有限次数重试后更新可播放链接。
- Emby 地址必须经过 HTTP/HTTPS 根地址校验；API Key 不回显、不写日志、不进入前端存储。

## 验收要求

- 每项规划独立提交和发布，不与 115 核心转存修复混在同一不可回滚变更中。
- 新通知渠道必须具备配置脱敏、测试接口、失败回退和回归测试。
- Emby 联动必须验证“转存已成功但 Emby 暂不可用”不会改变转存终态。
- 115 新认证后端必须保留手工 Cookie 回退，并提供失效、风控和撤销提示。
