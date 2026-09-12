# CD2 跨盘复制本地验收

Lane: B。Primary module: cloud。基线：GitHub v0.7.21。

## Module scope

- Primary module: cloud。
- Changed modules: openlist、tracking、transfer、settings、shared-core；STRM/Emby 继续调用原有后处理合同。
- Shared/Core changed: Yes。增加 Settings 字段、路由装配、前端 API 类型与共享表单/复制组件；这些是配置持久化、旧入口兼容和多个页面复用必需的接缝，业务执行仍在所属 service/client。
- Cross-module reason: 两条通路必须复用同一套缺失文件筛选、挂载映射、智能追更和后处理。跨盘页面从 main.tsx 迁入 features/cloud；原组件入口保留 re-export，未扩大架构测试的 legacy allowlist。api/config.py 只增加配置导入时调用所属模块的通路校验，未在其中实现新功能。

## Compatibility

- Behavior changed: Yes。OpenList/CD2 单选；CD2 复制受理与完成分开；远端完成且原生 115 精确落盘后才运行 STRM/Emby；待落盘任务每 15 秒续查，不重新提交复制。
- Database changed: No schema migration。复用 transfer_jobs.external_provider_status JSON，新增 transport、copy_receipts、run_pipeline 信息。保留历史 provider='openlist' 和已有 API/步骤键作为兼容标识；实际通路保存在回执中。
- Config or environment variables changed: Yes。新增 CROSS_COPY_TRANSPORT（默认 openlist）、CD2_URL、CD2_TOKEN、CD2_QAS_LIBRARY_PATH、CD2_P115_LIBRARY_PATH。OPENLIST_ENABLED、OPENLIST_AUTO_SYNC 继续作为两条通路共用的总开关和自动补齐开关；旧 OpenList 地址、令牌、挂载配置保留。
- API contract changed: Additive。新增鉴权后的 GET/POST /api/cross-copy/config；读取时只返回令牌是否存在。原 /api/openlist 浏览、连接测试、任务与复制接口调用当前单选通路。
- Backward compatibility: 未配置新字段时完全使用 OpenList。仍只自动从夸克补齐到 115，仍优先原生 115 资源。Token 留空保持已保存值；没有引入另一组可同时开启的复制开关。

## Proof

- Tests run: 提交前完整后端 1138 passed、37 subtests passed（1 个既有 Starlette 弃用警告）；前端 `pnpm --dir frontend build` 通过（既有大分块提示）。新增本机 gRPC 服务测试，验证原生协议、流式目录读取、Bearer 元数据；覆盖未完成/失败/取消状态、旧完成记录、网络受理不明、活动任务复用、回执先于复制提交持久化、重启续查、原生落盘/后处理门禁、配置互斥及导入边界。
- Local browser acceptance: http://127.0.0.1:5174/#cross-cloud。已检查默认 OpenList、选择 CD2 后独立字段展示、未保存时禁止连接测试和目录选择、未配置时禁止复制。未保存测试输入，保留用户本地配置。默认 8000 端口被另一应用使用，因此本次使用后端 8001 / 前端 5174。
- Known risks or follow-ups: 尚未连接用户真实 CD2/115 做真实跨盘验收。CD2 需支持官方原生 gRPC API，代理需支持 HTTP/2；仅提供 gRPC-Web 的代理地址不可用。CD2 回执缺失或无法唯一确认时保持等待，失败或取消进入 needs_review；不会根据 100% 进度猜测成功。请勿在待核验期间从 CD2 外部删除复制记录。API Token 需有浏览、创建目录、复制及复制任务读取权限；清理记录另需对应管理权限。

## 实现边界

复制回执先写入本地任务，再调用 CD2。接收结果不明时保留精确源/目标和提交前记录，不自动重试写请求。重复遇到相同活动任务时复用该任务。旧完成记录不能证明本次覆盖复制完成；上传中的目标条目即使已能列出，也不能提前进入 STRM/Emby。

有本地复制、待落盘或追更 115 待确认任务时，配置切换被拒绝；切换前还检查当前服务远端活动队列。自动追更的原生 115 父任务与复制辅助任务分别核验，复用父任务的入库流程，避免辅助任务再次触发入库。

手动勾选、自动补齐、季度补齐、目录浏览和复制队列共用现有入口。历史整库/旧单次复制接口保留原有“提交复制”的语义；其复制执行会使用当前单选通路，页面常用的勾选复制及自动补齐有持久化落盘与入库闭环。

本次以草稿 PR 交接，保留版本 v0.7.21，不合并 main、不发布版本、不访问或改动 NAS MediaIndex-public。

## 换电脑继续

- 分支：`codex/fix-tracking-delivery-v0721`。拉取该分支后按 `docs/LOCAL_TESTING.md` 启动本机沙箱，安装更新后的 `requirements.lock` 和前端锁定依赖。
- 本机配置、数据库、诊断附件、下载文件、夸克登录状态及临时端口配置不随 Git 同步；不要用真实 NAS 实例作为测试环境。
- 下一步在另一台电脑的本地沙箱配置 CD2 原生 gRPC 地址和 API Token，核对夸克/115 挂载路径，手动验收一份文件的复制完成、原生 115 落盘、STRM 生成和 Emby 回调。还需验收任务等待时拒绝切换通路、重启后继续核验且不重复复制。
- 追更与原始故障证据见 `docs/TRACKING_DELIVERY_FIX_20260912.md`；原始 STRM 失败的具体目录原因仍待新日志或目录配置确认。
- 夸克官方 skill 已在开发电脑安装并完成 `/分享/导航页小尺寸.zip` 实测。在线完整文件记录没有返回 `content_hash`、SHA1 或 MD5。下载副本与用户本地 ZIP 逐字节相同，大小均为 10,863,676 字节；本地计算 SHA1 为 `E47F560B5E2CF1ED647ED4E34C8E7F2B3B48E672`。这不是在线接口返回的哈希，不能据此认定可用于 115 秒传；未做真实秒传。

官方协议与开发说明：

- https://www.clouddrive2.com/api/clouddrive.proto
- https://www.clouddrive2.com/api/CloudDrive2_gRPC_API_Guide.md
