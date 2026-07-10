# Media Index 0.2.0 核心架构

## 产品目标

Media Index 首先是一个可靠的媒体追更决策器，其次才是海报浏览前端。

每次执行必须重新确认四件事：

1. TMDB 当前应该转存哪一季、哪一集。
2. 上一次分享链接是否仍有效，并且是否已经包含目标集。
3. 如果旧链接不可用或未更新，PanSou 是否能找到更合适的新链接。
4. 候选文件能否一一映射到 TMDB 集数，并生成无冲突的规范文件名。

QAS 只负责执行已经确认的 `share_url + pattern + replace`，不承担媒体识别和状态判断。

## 执行管线

```text
TMDB canonical target
  -> determine due episodes
  -> verify previous share URL
  -> reuse when valid and complete
  -> otherwise search PanSou
  -> cheap candidate ranking
  -> verify top links and read file trees
  -> file-level ranking and episode matching
  -> rename preflight
  -> high confidence: execute QAS
  -> ambiguous: persist review candidate
  -> update episode and next-check state
```

## 自动执行的必要条件

- 后端通过 TMDB ID 解析目标，不信任浏览器提交的标题和年份。
- 分享链接有效且能读取完整文件列表。
- 每个源文件最多映射到一个 TMDB episode。
- 明确集号、唯一中文期数或完整播出日期命中。
- 没有错误年份、错误季、衍生内容或重命名冲突。
- 第一候选达到阈值，并且与第二候选有足够分差。
- QAS 执行前通过 pattern/replace 预演。

## pattern / replace 原则

自动模式默认使用逐文件精确映射：

```text
pattern = ^<escaped source filename>$
replace = <title>.<series year>.S<season>E<episode>.<extension>
```

只有当一个完整资源包的所有目标文件都能预演为一一对应且无冲突时，才允许使用通用 QAS 正则或魔法变量。

## 追更状态

```text
pending -> due -> checking_previous_link -> searching -> matching
        -> transferring -> saved
                     \-> needs_review
        -> retry_wait -> failed
```

所有执行都以 `task + season + episode` 为幂等键。展示页面不得触发调度计算或数据库状态变更。

## 0.2.0 交付指标

- 搜索召回率：已知存在的资源进入 Top 20。
- 候选准确率：正确分享链接排在 Top 1 或进入待确认。
- 自动匹配准确率优先于自动覆盖率，错误自动转存目标为 0。
- 所有自动 replace 在执行前可预演、可解释、无目标文件名冲突。
- QAS 的 HTTP 触发成功与实际转存成功分开记录。
- 追更、愿望单和人工重试使用同一条决策管线。

