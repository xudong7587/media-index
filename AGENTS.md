# MediaIndex 项目指引

MediaIndex 是面向个人 NAS 的媒体发现、转存、愿望单和智能追更控制台。

## 运行与验证

- 整仓镜像：`docker build -t media-index:local .`
- 后端测试：先将 `backend` 加入 `PYTHONPATH`，再运行 `python -m unittest discover -s tests`。
- 前端开发：`cd frontend && pnpm install && pnpm dev`
- 前端构建：`cd frontend && pnpm build`
- Vite 默认使用 `http://localhost:5173`，并将 `/api` 代理到 `http://127.0.0.1:8000`。

## 本地版部署速查

- 本机仓库路径：`D:\Documents\MediaIndex前端\media-index`；上层目录可放部署临时包和 `.deploy` 记录。
- 用户自用 NAS 版访问地址：`https://media.dunn.fun:666/`；远端部署目录：`/volume2/docker/media-index`；容器名：`media-index`。
- NAS SSH：连接 `Sunnydunn@dunn.fun`，端口 `12580`，优先使用本机已有 SSH 密钥；Docker/Compose 操作通常需要远端 `sudo`，缺密码时向用户索取，不要在回复或文件中记录。
- 部署自用版时使用当前源码生成完整构建上下文，在 NAS 独立临时目录构建新镜像标签，构建和预检成功后再切换正式容器；不要只增量上传少数文件，避免 NAS 镜像与本地代码不一致。
- 自用 NAS 的远端 `docker-compose.yaml` 是运行配置，不要用仓库公共模板覆盖。正式服务必须使用本地构建镜像 `media-index:<VERSION>`，且 `pull_policy` 不能是 `always`；部署流程应为“同步源码 -> `docker build -t media-index:<VERSION>` -> compose 直接重建本地镜像”，不要拉 GHCR。
- 远端 compose 不要写入会覆盖 `data/.env` 的应用配置默认值，尤其 `MEDIA_USER`、`MEDIA_PASS`、`QAS_BASE_URL`、`QAS_TOKEN`、`PANSOU_URL`；这些以远端 `data/.env` 为准。
- 传输优先用 `.tar.gz` 源码包或可复现的完整 staging 目录；排除 `.git`、`.env*`、`data/`、数据库、缓存、`.venv/`、`frontend/node_modules/`、`frontend/dist/`、临时文件和真实密钥。
- 本地版数据挂载以远端 Compose 为准，关键持久目录是 `/app/data` 和 `/downloads`；更新容器不得删除或覆盖远端 `data`。
- 部署前后都要确认容器健康、页面可打开、版本标签正确；合并 GitHub、发布 GHCR 和部署本地 NAS 是三件事，必须分别汇报。
- 详细流程见 `docs/LOCAL_DEPLOYMENT.md`。

## 技术栈与目录

- `backend/`：Python 后端 API、任务与第三方服务集成。
- `frontend/`：React 19 + TypeScript + Vite 7；接口封装位于 `src/lib/api.ts`。
- `tests/`：后端单元和回归测试。
- `docs/ARCHITECTURE.md`：系统边界和核心流程的权威说明。

## 约定与当前状态

- 最终保存路径必须由后端生成；前端只展示、选择和确认。
- 密钥、Token、数据库、缓存、`.tmp/` 和前端构建产物不得提交。
- 版本以根目录 `VERSION` 为准；发布时同步 `frontend/package.json`、README 和 CHANGELOG。
- 当前前端入口集中在 `src/main.tsx`；新功能优先拆分可复用组件，避免继续扩大单文件。
- 修改前先查看 `git status`，保留用户已有的未提交改动。
- 115 的现役设计和迁移边界见 `docs/115_PROVIDER_PRD.md`；未实现的 Bark、Emby 和 115
  扫码/OAuth 规划只维护在 `docs/ROADMAP.md`，不得把规划描述成已上线能力。
- MoviePilot 不是 115 核心转存依赖，只允许作为 Cookie 导入源或用户自行配置的 STRM 后处理器。
- 多网盘任务必须保持 provider 身份：一个 provider 的失败不能回滚或遮蔽另一个 provider 的成功。
- 智能追更自动执行时只从对应网盘目录已存最后一集的下一集开始；只有目录一集都没有时才按初始全量资源处理。历史缺集只能由用户手动补集触发，不得自动回头补。

## 交付流程

- 禁止直接向 `main` 提交或推送；所有改动必须使用独立分支并通过 Pull Request 交付。
- PR 必须通过 GitHub Actions 中所有必需 CI 检查后才允许合并；禁止绕过、禁用或降低检查门槛。
- CI 失败时先查明原因、修复并重新验证，不得在失败状态下合并。
- 创建 PR 不代表获准合并；除非用户明确授权，Agent 在 CI 通过后只汇报状态，不自动合并。
- 合并不等于已部署；发布和线上验证需要单独确认。
