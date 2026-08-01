# MediaIndex 开发流程

## 唯一流程

`GitHub 最新 Release -> 本地开发与验收 -> 用户说“发布 Git” -> GitHub PR / CI / Release -> 用户手动更新 NAS 的 MediaIndex-public`

NAS 不在日常开发循环中。`MediaIndex-public` 是发布后的实际使用版本，不是开发、调试或自动部署目标。

## 日常开发

1. 从当前 GitHub 发布基线开始一个任务分支，只读与需求有关的代码。
2. 在本地修改；普通功能先在 `http://127.0.0.1:5173/` 验收。
3. 只运行与风险相称的测试。小修不构建、不跑全量；跨模块或高风险改动补回归测试。
4. 本地验收通过后停止，等待用户决定是否发布。

本地启动与数据隔离见 `docs/LOCAL_TESTING.md`。本地企业微信模拟器只验证 MediaIndex 的收发入口；真实外部操作必须由用户在本地配置中明确启用。

## 发布 Git

只有用户明确说“发布 Git”后才进入发布：保留已验收代码，运行发布所需检查，更新正式版本，提交、PR、CI、合并 `main`，由 GitHub 构建镜像和 Release。

用户随后自行将 GitHub 公开版本更新到 NAS 的 `MediaIndex-public` 并作为实际使用版本。没有 `-test`、`-dev` 或 `-local` 版本线。

## 完成口径

- `本地已验收`：本地页面/API 和本次聚焦检查通过。
- `GitHub 已发布`：PR/CI/`main`/Release 已完成。
- `NAS 已更新`：仅由用户手动确认；代理不得自行声称或执行。
