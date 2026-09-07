# v0.7.20 智能追更修复验收记录

基线：GitHub Release `v0.7.19`，提交 `692cfa9`。本地修复分支：`fix/tracking-completion-fill-v0719`。

## 问题与最终行为

原有元数据同步只增加和更新分集；网盘扫描还会把额外集号插入同一张表，卡片随后把全部记录计入总数。现在以当前 TMDB 分集作为有效集合，撤回的元数据和仅在网盘发现的集号保留历史，但不参与集数、缺集或跨盘补齐计算。新增、撤回分集及播出日期修改会重新计算检查时间；未变化的元数据不会重置失败重试间隔。TMDB 异常空结果保留原集合。

已播集收齐与本季完结收齐分开处理。归档需要本季完结依据（TMDB 末集 finale 标记、剧集结束状态，或用户确认的最终集号）、有效分集逐集保存、有效播出日期、可靠存储清单，以及没有活动转存和待执行后处理。电视剧元数据中间缺号不能宣告完整；综艺保留既有衍生集过滤语义。

每个网盘的卡片提供最终集号设置，可恢复使用 TMDB 集数。归档任务保留文件及历史，并进入“已归档”筛选；手动恢复后保持追更，不立即再次自动归档。重新保存最终集数设置可重新启用自动归档。

补集的去重范围由“相同选集且 running”扩展为同一追更链路的 running、ready、triggered 执行。相同请求返回已有任务，不同选集或不同分享链接返回冲突提示，不新建失败占位。数据库事务和触发器阻止并发创建新追更执行，保留旧版本已存在的外部任务记录。夸克和 115 的独立执行不互相覆盖；原有多链接转存和 STRM 后处理继续复用该次主任务及其步骤。

## 模块与兼容性

- Lane：B；Primary module：tracking。
- Changed modules：tracking；discover 的 EpisodeTarget/分集解析只增加可选 episode_type；openlist 的追更补齐查询使用有效集合；settings 的备份白名单保留新字段。
- Shared/Core changed：Yes。数据库是追更持久化和任务并发约束的必要接缝；迁移为增量字段及追更专用触发器，不删除历史记录，不限制无关转存任务。
- Behavior changed：Yes。有效集数、自动归档及补集冲突处理。
- Database changed：Yes。有效元数据标记、最终集号、归档与存储核验字段；新追更任务创建/恢复的数据库约束。
- Config or environment variables changed：No。
- API contract changed：Yes，增加 `PUT /api/tracking/{id}/final-episode`（`final_episode` 为整数或 null）；追更列表增加 completion_state、final_episode_override、auto_archive；补集冲突返回 ok=false、duplicate=true、blocked=true。
- Backward compatibility：既有接口保留；新字段默认值保守；旧备份缺少字段时使用默认值；新备份保留校正设置和撤回分集；不把旧存储记录直接视为可靠核验。

## 验证

- 完整后端：1113 passed，37 subtests passed；一条既有 Starlette/httpx 弃用提示。
- 最终并发约束与新增业务回归文件：15 passed，6 subtests passed。
- `pnpm --dir frontend build` 通过；保留既有大包体提示。
- `git diff --check` 通过。
- 本地浏览器已操作：26 集手动校正为 24 集后自动归档；查看归档卡片；恢复追更；撤销校正后重新显示 26 集；等待网盘确认时选择 E02，补齐所选/全部/链接入口仍禁用。已检查新增表单实际布局。

验收地址：http://127.0.0.1:5173/#subscriptions 。运行的是本修复工作树，后端监听 127.0.0.1:8000，前端监听 127.0.0.1:5173。`.tmp/local-055/` 为此次新建的隔离沙箱，使用明确标注“验收示例”的虚拟任务；自动巡检、外部通知及跨盘自动同步关闭，没有网盘凭据，未触发真实转存。运行文件、测试日志和虚拟数据不进入 Git。

## 限制与交付状态

TMDB 自身错误仍可能需要用户校正最终集号；缺少完结证据时继续保留追更。未使用用户 NAS 的真实故障记录验证，也未测试真实网盘转存。旧版本已存在的重复外部任务不会被自动删除或撤销。

尚未提交、推送、创建 PR、修改版本号、发布 GitHub Release 或部署 NAS。主检出的未提交工作保持原样。本地浏览器服务不启用后端自动重载，后续修改后需重启本修复目录的后端。

