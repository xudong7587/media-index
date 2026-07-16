# MediaIndex 0.4.3

- 新增企业微信自建应用交互回调配置。
- 支持回调 Token、EncodingAESKey 和允许指令成员配置。
- 推送页面自动显示当前站点的企业微信回调 URL，并支持复制。
- 实现企业微信回调 URL 验证、SHA1 签名校验、AES 消息解密和企业 ID 校验。
- 支持文本消息和自定义菜单点击事件。
- 新增 `/status`、`/review`、`/tracking`、`/wishlist`、`/notifications` 和 `/help` 指令。
- 指令结果只回复给触发成员，并对企业微信重复投递做短期去重。
