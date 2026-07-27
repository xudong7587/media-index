# MediaIndex 项目指引

MediaIndex 是面向个人 NAS 的媒体发现、转存、愿望单和智能追更控制台。

## 新会话硬性入口

- 任何新对话开始开发、测试、部署或合并前，必须先读取并遵守 `docs/DEVELOPMENT_FLOW.md`；不要只看本文件里的摘要。
- 用户提出大致功能方向时，默认先整理 `leader` 风格任务书，再一次性完成主要实现、针对性验证、NAS 部署和线上冒烟；不要把同一功能拆成多轮碎片手测。
- 日常验收的完成标准是“已同步当前源码到自用 NAS、远端本地构建镜像、重建 `media-index` 容器、页面和本次功能入口冒烟通过”。只改本地代码、只改版本号、只跑测试或只跑 `pnpm build`，都不能说已部署。
- 自用 NAS 版本标记可以使用类似 `0.5.1-test1` 的临时后缀帮助用户识别，但它只是识别标记，不是部署证据；最终汇报必须包含 NAS 容器镜像/版本、页面可打开和本次功能入口验证结果。

## 运行与验证

- 整仓镜像：`docker build -t media-index:local .`
- 后端测试：先将 `backend` 加入 `PYTHONPATH`，再运行 `python -m unittest discover -s tests`。
- 前端开发：`cd frontend && pnpm install && pnpm dev`
- 前端构建：`cd frontend && pnpm build`
- Vite 默认使用 `http://localhost:5173`，并将 `/api` 代理到 `http://127.0.0.1:8000`。
- 日常开发按 `docs/DEVELOPMENT_FLOW.md` 分 A/B/C 三档验证：快速功能分支做针对性验证和 NAS 冒烟；风险功能分支追加全量后端测试、前端构建和必要 Docker 构建；正式发布才走 PR/CI/GHCR/Release 全链路。
- 本地小功能开发、远端调试和自用 NAS 部署默认不要等待 GitHub/GHCR；优先改源码、跑最小有效验证、同步到 NAS 后由 NAS 使用当前源码构建并做线上冒烟。
- 只有用户明确要求提交 Git、合并 `main`、发布版本或验证发布产物时，才执行提交、PR、等待 GitHub Actions、镜像发布和 Release。

## 本地版部署速查

- 本机仓库路径：`D:\Documents\MediaIndex前端\media-index`；上层目录可放部署临时包和 `.deploy` 记录。
- 用户自用 NAS 版访问地址：`https://media.dunn.fun:666/`；远端部署目录：`/volume2/docker/media-index`；容器名：`media-index`。
- NAS SSH：连接 `Sunnydunn@dunn.fun`，端口 `12580`，必须显式使用本机密钥 `~/.ssh/codex_media_index_nas_ed25519` 和 `IdentitiesOnly=yes`，例如 `ssh -o BatchMode=yes -o IdentitiesOnly=yes -i "$HOME/.ssh/codex_media_index_nas_ed25519" -p 12580 Sunnydunn@dunn.fun "echo ok"`；不要依赖 SSH 自动选钥匙。常规 Docker/Compose 重建优先执行免密白名单脚本 `sudo -n /usr/local/sbin/media-index-deploy`，不要默认向用户索取 sudo 密码。只有脚本不存在、失效或不覆盖当前任务时，才说明原因并询问是否临时提供 sudo 密码，且不要在回复或文件中记录。
- 部署自用版时使用当前源码生成完整构建上下文，在 NAS 独立临时目录构建新镜像标签，构建和预检成功后再切换正式容器；不要只增量上传少数文件，避免 NAS 镜像与本地代码不一致。
- 自用 NAS 的远端 `docker-compose.yaml` 是运行配置，不要用仓库公共模板覆盖。正式服务必须使用本地构建镜像 `media-index:<VERSION>`，且 `pull_policy` 不能是 `always`；部署流程应为“同步源码 -> `docker build -t media-index:<VERSION>` -> compose 直接重建本地镜像”，不要拉 GHCR。
- 不要先更新镜像再用 compose 拉取。自用 NAS 版不是等 GHCR 的线上发布流程；它应当先把已修改源码同步到远端，再在远端根据这些文件构建本地镜像，最后用现有 compose 重建容器。
- 如果只是远端调试，不需要推送 Git，也不要为了“本地版部署”额外等待 GitHub 构建镜像；GitHub Actions/GHCR 只属于发布流程。
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
- 用户说“推送到 Git”“更新到 Git”“合并入 main”并且语境是版本发布时，完成标准不是只 push 分支：必须更新版本号、README、使用手册和 CHANGELOG，保留 README 免责声明，创建 PR，通过 CI，合并到 `main`，确认 Docker/GHCR workflow 成功，并按版本创建 tag 与 GitHub Release。
- 发布完成后要分别核对并汇报：PR/merge commit、GitHub Release 链接、`latest` 镜像是否由 `main` workflow 成功发布、版本 tag 是否存在、文档是否已更新。本地 NAS 自用部署仍然单独汇报。

## 新分支任务书规范

- 以后需要开发新分支、把想法拆给 agent 执行、或并行分派任务时，先按 `leader` 规范把一句话需求整理成可独立执行的任务书，再开工或交给目标模式。
- 写任务书前先调研：能从仓库、命令、测试、文档或联网查到的信息不要问用户；关键命令要亲手跑，记录基线数字和日期。摸不到的环境写成“任务 0：先核验环境和基线”。
- 只问会改变任务书的问题，一轮不超过 5 个；用户不在场时可以按默认值推进，但必须在任务书的“我替领导拍的板”里明说默认选择和猜错代价。
- 每份任务书只对应一个目标、一次粘贴，控制在 4000 字符以内；内容包括意图、让步顺序、改动白名单、冻结区、现状与任务 0、具体任务、规矩和完成条件。
- 验收必须可复跑：列出实际命令、机器可判标准、测试数或覆盖率基线、防作弊约束，以及必要的反向验证。禁止通过 skip/todo、放宽断言、mock 被测对象、删测试、改阈值、改验收脚本或 `|| true` 让检查假绿。
- 执行者必须维护 `PROGRESS.md`；受阻但还能继续时写 `BLOCKED.md`，不要停下来等人。换新会话先读 `PROGRESS.md` 接着做。
- 同一验收连续失败 3 次要换项或止损；结果比基线更差要回滚并如实报告。“没做成但说清楚证据”可以接受，“做了但更糟还说完成”不合格。
- 多 agent 并行必须先得到用户同意；每份任务书写清全局目标、各自地界、共享文件唯一归属和接缝验收。建设和删除不要交给同一个 agent。
