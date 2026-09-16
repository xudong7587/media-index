# 发现页磁力下载路径修复

Lane：B。基于正式版 `v0.7.24`，本地分支 `fix/discovery-magnet-staging-path-20260916`。

## 问题与修复

用户提供的诊断包中，任务 4397、4398、4400 均在磁力提交前报“下载链接目标必须是云下载路径的直属子文件夹”，保存路径为空，没有提交阶段事件。任务 4399 属于原生分享过期，是另一条请求。

发现页已经将磁力交给云下载服务，但服务先生成“云下载根／分类／片名（年份）”，随后错误地对影片目录执行直属分类目录校验。本次改为先验证从网盘实际读取的分类目录，再在该分类下生成影片暂存目录，与互动云下载入口采用相同顺序。完成后的目标核验、定点整理和入库流程继续复用原有实现。

## Module scope

- Primary module: transfer。
- Changed modules: transfer；补充发现页磁力回归测试。
- Shared/Core changed: No。
- Cross-module reason: N/A；未修改共享路径校验函数。

## Compatibility

- Behavior changed: Yes，合法的发现页磁力下载不再因目录层级误判而被拒绝。
- Database changed: No。
- Config or environment variables changed: No。
- API contract changed: No。
- Backward compatibility: 云下载根目录、正式媒体库路径、嵌套分类和越界路径仍被拒绝；停止任务不提交；保留原任务 ID 和 TMDB 身份。

## Proof

- Tests run: 首先移除旧测试中的路径校验模拟，使用真实配置、分类识别、目录选择和路径校验复现 4 个失败；修复后，磁力、直链、115 完成核验和路径相关测试共 **106 passed**，`git diff --check` 通过。
- Local browser acceptance: 本次无前端改动，不重复页面验收；通过服务集成测试验证电影和电视剧均向原生 115 下载客户端传入分类下的媒体暂存路径，外部客户端使用模拟返回，不实际下载。
- Known risks or follow-ups: 尚未发布或执行真实网盘下载；本次解决提交前的目录校验错误，实际下载及后续入库需更新后验证。
- 本地入口：<http://127.0.0.1:5173/>。没有修改 NAS 容器、运行配置或正式任务。
