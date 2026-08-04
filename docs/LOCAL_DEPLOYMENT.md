# NAS 部署手册（已退役）

本项目不再维护代理自动部署 NAS 的流程。当前唯一开发与发布链路为：

`GitHub 最新 Release → 本地开发与验收 → 用户明确说“发布 Git” → PR / CI / main / GitHub Release → 用户手动更新正式 NAS`

日常开发请使用 [`LOCAL_TESTING.md`](LOCAL_TESTING.md)，发布规则请使用 [`DEVELOPMENT_FLOW.md`](DEVELOPMENT_FLOW.md)。代理不得从本页恢复 SSH、SCP、WebDAV、Docker 远程操作或任何 NAS 自动部署流程。

NAS 主机名、地址、账户、私有反向代理域名、目录布局和访问凭据属于敏感信息，不应保存在 Git 仓库或公开 Issue 中。确需处理 NAS 的独立任务时，由用户在当次会话中明确授权并提供已确认的最小范围信息。
