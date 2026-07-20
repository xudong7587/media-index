# MediaIndex 项目指引

MediaIndex 是面向个人 NAS 的媒体发现、转存、愿望单和智能追更控制台。

## 运行与验证

- 整仓镜像：`docker build -t media-index:local .`
- 后端测试：先将 `backend` 加入 `PYTHONPATH`，再运行 `python -m unittest discover -s tests`。
- 前端开发：`cd frontend && pnpm install && pnpm dev`
- 前端构建：`cd frontend && pnpm build`
- Vite 默认使用 `http://localhost:5173`，并将 `/api` 代理到 `http://127.0.0.1:8000`。

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

## 交付流程

- 禁止直接向 `main` 提交或推送；所有改动必须使用独立分支并通过 Pull Request 交付。
- PR 必须通过 GitHub Actions 中所有必需 CI 检查后才允许合并；禁止绕过、禁用或降低检查门槛。
- CI 失败时先查明原因、修复并重新验证，不得在失败状态下合并。
- 创建 PR 不代表获准合并；除非用户明确授权，Agent 在 CI 通过后只汇报状态，不自动合并。
- 合并不等于已部署；发布和线上验证需要单独确认。
