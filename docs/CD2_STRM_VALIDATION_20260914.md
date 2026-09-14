# CD2 通路与夸克 STRM 复测

基线：GitHub `main` 的 `812e1e1` 与 PR #92 的 `7f7088c`。在独立 worktree 中继续开发，未修改主源码目录的未提交工作。

## Module scope

- Primary module: cloud。
- Changed modules: cloud、strm。
- Shared/Core changed: No（本轮追加修改）。
- Cross-module reason: CD2 实际连接兼容问题与夸克 STRM 页面交互是本次两个明确任务；仍复用既有复制、目录、STRM 任务和落盘核验合同。

## Compatibility

- Behavior changed: Yes。CD2 在首次只读请求遇到原生 gRPC 传输不兼容时尝试二进制 gRPC-Web；协议选定后同一个写请求不通过另一协议重发。第一个调用若为写操作，先查询复制队列确定协议。两种协议均使用相同 protobuf、Bearer 令牌、复制回执及落盘核验。
- Database changed: No。
- Config or environment variables changed: No。
- API contract changed: No。
- Backward compatibility: 原生 gRPC 可用时继续使用原生连接；OpenList 选择不变。gRPC-Web 校验最终状态、帧完整性、唯一单次响应和 16 MiB 总响应上限；拒绝重定向，不读取系统代理，不输出远端错误正文。授权失败不再被协议层的 `Stream removed` 遮蔽。
- STRM: 选择来源后自动读取可勾选子目录；重新选择同一目录保留勾选，真正改变来源时清空旧范围，忽略旧目录的迟到响应。生成按钮显示缺少登录、来源、扫描范围或输出目录的具体原因。手动扫描无需开启自动生成，点击后先保存本页设置。空目录提示选择上一级并勾选当前目录，仍不默认扫描整盘。

## Proof

- 完整后端：1160 passed、43 subtests passed；1 个既有 Starlette 弃用提示。
- 前端生产构建通过，保留既有 chunk-size 提示；浏览器扩展合同测试通过。
- 新增 gRPC-Web 合同测试：流式多消息、最终状态、授权失败、截断/非法帧、超限响应、HTML/重定向、单次响应数量、写前只读协商以及原生写请求失败不重发。
- 将 CD2 官方完整 proto 编译为描述符，与本项目子集逐字段比较：42 个字段的编号、类型、重复性和类型名称及全部子集枚举值一致。
- 浏览器隔离验收：模拟夸克只有一个子目录和一个文件。子目录自动出现，未勾选时按钮禁用并提示原因，勾选后按钮可用；目录选择器再次选择原目录后仍保留勾选。清空输出目录显示具体提示，恢复后可扫描。增量任务生成 1 个本地 STRM；随后全量任务保持 1 个、生成 0 个，无重复文件。
- 上述浏览器云端目录为模拟数据，STRM 任务、数据库、配置保存与本地文件写入使用实际业务代码；不能据此宣称真实夸克播放或 CD2 跨盘验收完成。模拟器和数据全部位于忽略的 `.tmp/`，不进入提交。

## 真实 CD2 验收结果

Docker CD2 实例的 API 令牌通过 gRPC-Web 鉴权；此前令牌属于另一台 CD2 实例，不能通用，不能根据 UUID 外观判定令牌类型或有效性。

- 仅在 `/Quark/MediaIndex测试` 和 `/115open/MediaIndex测试` 建立测试目录，写入 1 个 1 KiB 的测试源文件并复制到 115。共 5 次云端写请求（2 次建目录、创建/写入源文件、1 次复制），串行执行，相邻写请求至少间隔 10 秒。源文件保留，目标无覆盖，无删除。
- 使用实际 `_copy_client(job_id).copy`，提交前回调将 1 条复制回执持久化至隔离数据库，然后结束该 Python 进程。新的进程先验证待处理任务拒绝切换通路，再调用生产恢复和续查入口。恢复 1 个任务，CD2 返回完成，原生 115 确认目标文件落盘；后处理生成 1 个本地 STRM，任务最终为 `done / openlist_post_processing_done`。远端复制记录始终只有 1 条。
- 原生夸克接口也确认源文件；在独立映射数据库中，从 `/` 仅扫描授权的 `/MediaIndex测试` 子目录，成功生成 1 个本地夸克 STRM。
- 测试过程中发现并修复两个既有问题：夸克只读根目录解析误用了禁止创建根目录的校验；按网盘/来源范围生成 STRM 时，遗漏其他网盘/来源已经占用的输出路径。只读解析现在允许 `/`，创建根目录仍被拒绝；路径冲突现在在写文件前转为待复核，保留已有内容。真实同名夸克/115 路径冲突验证返回 `conflicts=1`，已有 115 STRM 字节不变。
- Emby 自动刷新及外部通知保持关闭，未访问 NAS 的 MediaIndex 服务。样本为复制/元数据合同测试文件，不是可播放电影；本轮不宣称已验证真实 Emby 回调或视频播放。

协议参考：[CD2 API 指南](https://www.clouddrive2.com/api/CloudDrive2_gRPC_API_Guide.html)、[gRPC-Web 协议](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md)。
