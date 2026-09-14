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

- 完整后端：1157 passed、37 subtests passed；1 个既有 Starlette 弃用提示。
- 前端生产构建通过，保留既有 chunk-size 提示；浏览器扩展合同测试通过。
- 新增 gRPC-Web 合同测试：流式多消息、最终状态、授权失败、截断/非法帧、超限响应、HTML/重定向、单次响应数量、写前只读协商以及原生写请求失败不重发。
- 将 CD2 官方完整 proto 编译为描述符，与本项目子集逐字段比较：42 个字段的编号、类型、重复性和类型名称及全部子集枚举值一致。
- 浏览器隔离验收：模拟夸克只有一个子目录和一个文件。子目录自动出现，未勾选时按钮禁用并提示原因，勾选后按钮可用；目录选择器再次选择原目录后仍保留勾选。清空输出目录显示具体提示，恢复后可扫描。增量任务生成 1 个本地 STRM；随后全量任务保持 1 个、生成 0 个，无重复文件。
- 上述浏览器云端目录为模拟数据，STRM 任务、数据库、配置保存与本地文件写入使用实际业务代码；不能据此宣称真实夸克播放或 CD2 跨盘验收完成。模拟器和数据全部位于忽略的 `.tmp/`，不进入提交。

## 真实 CD2 验收状态

用户提供的反向代理上，原生 gRPC 返回 `UNKNOWN / Stream removed`，公开的 gRPC-Web 方法成功响应。新兼容层已能取得服务端鉴权错误；已尝试的令牌返回 `Invalid auth token`，令牌查询返回 `token not found`。待有效令牌后继续真实复制，当前尚无云端写操作。

授权范围仅为 `/Quark/MediaIndex测试` 与 `/115open/MediaIndex测试`。创建和复制串行，每次云端写请求至少间隔 10 秒，只使用少量测试文件，保留源文件、不覆盖既有目标。不得将上述模拟验收当作真实复制、原生 115 落盘、STRM/Emby 或重启续查的验收结果。

协议参考：[CD2 API 指南](https://www.clouddrive2.com/api/CloudDrive2_gRPC_API_Guide.html)、[gRPC-Web 协议](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md)。
