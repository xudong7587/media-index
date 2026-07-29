# MediaIndex 开发流程

## 唯一交付链

```text
GitHub 公共 Release
  -> 自用 NAS：开发分支、日常使用、人工验收
  -> 用户明确说“发布 Git”
  -> GitHub：PR、CI、main、镜像、Release
  -> MediaIndex-public：只打开确认正式镜像呈现
```

当前重启基线是公开 `0.5.3`。自用 NAS 是唯一可开发和测试的环境；`MediaIndex-public` 不得修改、调试或测试业务流程。

## 分层

| 档位 | 适用情况 | 不做什么 |
| --- | --- | --- |
| A0 | 文案、小逻辑、窄范围修复 | 不构建、不部署、不全量测试 |
| A1 | 后端自用版修复 | 不构建镜像、不 compose、不 GitHub 发布 |
| A2 | 用户需要查看的前端页面 | 不重建镜像；只在需要时构建前端 |
| B | 转存、追更、路径、数据库、认证、安全、通知、Provider、调度 | 不做全库扫读；只跑相关回归，必要时全量后端测试 |
| C | 用户已人工验收并说“发布 Git” | 不在 NAS 重复构建镜像 |

## 自用版部署

所有当前 NAS 参数和前置状态见 `docs/LOCAL_DEPLOYMENT.md`。

1. 从公开 Release 基线创建任务分支，修改最少必要文件。
2. 运行与风险相称的定向测试。
3. 使用 SCP 上传变更文件到 NAS staging；不用 WebDAV。
4. 后端执行 `reload backend`；前端只在需要展示时 `pnpm --dir frontend build`，上传 `frontend/dist` 后执行 `reload frontend`。
5. 打开自用版人工验收。上传成功不等于部署成功；只有 reload 和页面/API 冒烟成功才算容器已更新。

不要上传完整源码包，不要 base64，不要 rsync 全仓，不要 Docker build，不要 `docker compose up`。

## 版本与发布

自用版不使用 `-test`、`-dev`、`-local` 后缀。需要识别变更时直接递增正式版本；GitHub 发布沿用同一版本。

只有用户说“发布 Git”后才创建 PR。PR 是已验收改动的合并记录；CI 是 GitHub 自动测试/构建。人工验收决定功能是否符合需求，CI 负责自动化防回归，二者不能互相替代。

## 新会话回复

先用一句话说明 A0/A1/A2/B/C。最后只报告：改了什么、测试结果、自用版状态、用户该验收什么、哪些步骤没有做。
