# 追更终点与转存后处理修复（本地待验收）

基线：GitHub 正式发布 `v0.7.21`，未调整版本号、未发布。本文的模块与测试字段记录初始追更修复范围；后续 CD2 实现和跨电脑交接见 `CD2_CROSS_COPY_20260912.md`。

## 诊断证据

- 用户提供的 CSV 与诊断 ZIP 仅作只读故障证据，未导入运行数据库。
- 《凡人修仙传》任务 #4364：115 原生转存于 2026-09-12 05:05:49 UTC 完成；后续 STRM 两次报 `TargetedStrmError`，Emby 与入库通知被跳过。该任务的 OpenList 步骤为 skipped。因此本次失败不在 OpenList 复制阶段。
- 夸克任务 #4365：原生转存成功，但“当前网盘未启用自动 STRM 生成”，这是开关行为，未擅自开启。
- 诊断包不含追更任务的完结元数据、最终集号覆盖值、自动 STRM 来源与勾选范围，也未保存 `TargetedStrmError` 的具体原因。不能仅据附件断言真实自动归档由哪条元数据触发，或认定此次 STRM 失败一定是目录配置错误。

## 已修改行为

1. 连载状态下，TMDB 当前最后一集的 `finale` / `season_finale` 标签不再单独触发自动归档。自动完结仍需整剧终态（Ended/Canceled）、有效分集全已播、全已保存和网盘核验；用户指定最终集号仍有效。这会使已经季终、但整剧仍连载的任务保持追更，可用最终集号设置明确结束。
2. 已追平的连载保留下一次元数据检查；自动归档记录也参与元数据复核，撤回完结证据时恢复任务。暂停和手工最终集号归档不自动恢复；已保存集数不重置。
3. 新增内容的完成通知改称“本轮更新”，不再称“本季追更已完成”。沿用无新增内容不通知、批次通知去重的已有规则。
4. STRM 已写好、Emby 刷新失败/执行中断时，重试不会因 STRM 无变化而跳过未完成的刷新步骤；重放成功任务保留等待 Emby Webhook 的状态。入库成功仍必须等待真实回调，刷新提交不等于入库完成。
5. 定点 STRM 的错误显示固定、可操作的原因，如“目标路径不属于已勾选的媒体一级子目录”。原始远端异常不透出凭据；没有扩大目录授权或全盘扫描兜底。

## 尚未确认

#4364 的原始 STRM 失败原因仍需 115 的已保存 STRM 来源目录与勾选子目录，或修复后带具体原因的新日志。已向用户询问非敏感目录信息。本次修复并不宣称真实网盘和 Emby 已恢复入库。

## CD2 调查

核对 [CD2 官方 proto](https://www.clouddrive2.com/api/clouddrive.proto) 和 [开发者指南](https://www.clouddrive2.com/api/CloudDrive2_gRPC_API_Guide.html)：

- `CopyFile` 返回 `FileOperationResult`（success/errorMessage/resultFilePaths）；此回执不单独证明目标网盘上传完成。
- `GetCopyTasks` 返回源/目标路径对应的任务，状态包含 Pending、Scanning、Scanned、Completed、Failed，并有 uploadedFiles、failedFiles、cancelledFiles、skippedFiles 等计数。
- 可以设计独立可选复制通路。完成条件应为精确关联的复制任务成功、无失败/取消，并通过 115 原生接口验证目标文件身份与大小，然后进入同一个 STRM/Emby 流程。任务消失或仅 Scanned 不能作为完成证据。
- 初始修复先处理已证实的后处理缺口；随后已按用户要求新增 CD2 单选通路，见 `CD2_CROSS_COPY_20260912.md`。未连接真实 CD2，也没有将既有 OpenList 配置自动替换。更换复制工具不能修复此次原生 115 转存后的 STRM 校验错误。

## 夸克官方 skill 与 115 秒传

[夸克官方 skill 的文件检索协议](https://github.com/quark-clouddrive/quarkclouddrive_offical/blob/main/skills/quarkclouddrive/references/file-search.md) 明确支持在完整 Search/Browse Artifact 中透传 `content_hash`，但定义为夸克自定义规则生成的云端哈希，没有保证等于原始文件 SHA-1。不能将其改名或转换成 SHA-1 就交给 115。

[OpenList 的 115 SDK 上传实现](https://github.com/OpenListTeam/115-sdk-go/blob/main/upload.go) 使用完整文件 SHA-1、前 128 KiB SHA-1，并支持服务端校验挑战字段。即使以后获得标准 SHA-1，也需完成 115 校验且命中其服务端文件，不能保证秒传。

后续实测：已按用户授权安装、登录并使用官方 skill 浏览指定文件，完整在线记录没有返回 `content_hash` 或标准哈希。仅下载指定 ZIP 与本地文件比对，两者逐字节一致。公开合同及本次实测仍不足以建立可验证的“免下载夸克→115 秒传”通路，未做真实秒传。可交接的实测摘要见 `CD2_CROSS_COPY_20260912.md`，账号凭据和文件本体不纳入 Git。

## Module scope

- Primary module: tracking。
- Changed modules: tracking、transfer（post_transfer_pipeline）、strm（错误原因）；media-server/integrations 仅复用既有刷新和通知合同，未修改其实现。
- Shared/Core changed: No。未改配置、数据库、Domain 或 Scheduler 文件；追更的调度语义在 owner 服务内修复。
- Cross-module reason: 转存后恢复必须接续同一条精确 STRM/Emby 链路，错误原因由 STRM owner 提供。

## Compatibility

- Behavior changed: Yes，见上方。
- Database changed: No schema/migration；只在既有授权任务生命周期中更新状态，不重置历史。
- Config or environment variables changed: No。
- API contract changed: No。
- Backward compatibility: 旧配置、Provider、路径、API、手动最终集号仍兼容；STRM 开关、选定目录和不删除合同保持不变。

## Proof

- 初始聚焦回归：54 passed / 15 subtests；真实本地 STRM 写入与追更补齐回归：23 passed。
- 完整后端回归：1120 passed / 37 subtests；1 个既有 Starlette 弃用警告。首次全测遇本机缺字体和 pytest 临时目录权限，补齐官方测试字体并使用新的隔离 basetemp 后全测通过，未跳过或弱化断言。
- 覆盖：190 集已保存→元数据出现 191 集恢复追更；连载 finale 不归档；手动最终集号不被覆盖；Emby 首次失败后复用同一 STRM 成功刷新；重放不重复写文件且保留回调等待；范围不匹配不调用 Emby；远端错误不泄露 token。
- Local browser acceptance: 已登录本地沙箱并打开追更页，显示 v0.7.21，自动巡检关闭，空任务状态正确。未向用户管理的数据库添加测试媒体。
- 临时验收入口：[本地追更](http://127.0.0.1:5174/#subscriptions)，后端 `127.0.0.1:8001`。默认 8000 被另一款本机软件占用，未停止该软件；临时 Vite 配置位于 Git 忽略目录，没有修改正式端口配置。
- Known risks or follow-ups: #4364 原因待非敏感目录配置或新日志确认；真实云盘/Emby/CD2 未联调；用户验收可查看追更终点、下一次巡检和后处理失败原因。

本次以草稿 PR 交接；未合并、未发布 GitHub Release，未接触 NAS 的 MediaIndex-public。
