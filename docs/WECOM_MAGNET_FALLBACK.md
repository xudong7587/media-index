# 企业微信搜剧磁力兜底

v0.7.37，发布基于 v0.7.36。企业微信资源名任务的 115 原生分享仍优先验真；分享无可用文件，或提交时明确提示过期且没有任何已接受写入时，使用同次 PanSou 搜索返回的磁力候选兜底。冻结的分享快照已过期且不含磁力时，重新查询一次 PanSou 磁力候选。夸克及其他自动追更入口不因本次改动开启磁力。

自动云下载要求剧名、明确季度和所需集数证据一致，磁力 dn 名称存在时也要核对。错剧、错季、花絮和排除质量不自动提交。季集证据不全的同剧候选进入 needs_review，企微回复候选编号后提交该磁力。整季资源只有季度、没有明确集数时也需要确认；不会把“全集”文字当作完整文件清单。

自动和人工确认都沿用既有任务与用户已选的 115 云下载直属子目录，下载到媒体暂存目录，再由既有云下载整理流程处理。已经部分写入的分享失败不触发磁力重试。

## Module scope

- Primary module: transfer
- Changed modules: discover, integrations
- Shared/Core changed: No
- Cross-module reason: 企微资源任务复用发现候选判定、转存及待确认接缝。

## Compatibility

- Behavior changed: Yes，企微 115 搜剧增加磁力兜底和人工确认。
- Database changed: No
- Config or environment variables changed: No
- API contract changed: No；内部提交函数增加可选目录参数，旧调用保持兼容。
- Backward compatibility: 网页磁力规则、夸克和追更默认行为保持；已有配置及任务表继续使用。

## Proof

- Tests: discovery_magnets、interaction_cloud_download、review_cleanup、wecom_callback、direct_link_transfer、architecture_boundaries。
- Release checks: 后端全量 1343 passed、2 个既有 skipped、58 subtests passed；前端生产构建和浏览器扩展合同测试通过。
- Local browser acceptance: 尚未进行真实企微回调或真实 115 下载验收；测试使用隔离数据库与模拟 Provider。
- Known risks or follow-ups: 磁力提交前无法获取实际文件清单，最终文件身份仍需既有整理流程核对。
