# 搜索漏资源与愿望单停更修复

Lane：B。Primary module：discover。Changed modules：discover、tracking。
Shared/Core changed：No。跨模块原因：发现端的分享读取失败曾让愿望单永久停在人工确认状态，需要修复重试与旧状态恢复。

开发基线为 GitHub main `7496b4e`（0.8.0），包含 0.7.38-rc.6 已验收的 SunnyUI 设计。本地工作区为 `.worktrees/pansou-search-recall`。原 `strm-rescan-fix` 是 0.7.36，不作为此次验收来源。

## 线上证据

仅通过用户授权的 Web SSH 读取配置、数据库与分享文件，未部署、转存或修改 NAS 数据。

- 《缅北电诈覆灭纪实》TMDB TV 337399，第一季三集。PanSou 返回十条夸克候选，分享可正常读取；实际文件包括 `第一集《利剑出鞘》.mp4`、`第二集《犁庭扫穴》].mp4`、`第三集《共筑天网》.mp4`。旧电视剧匹配只认 E/SxxExx；带“纪录片”的文件还被判定为衍生内容。线上原发现流程返回 no_resource。
- 《挖掘者》TMDB movie 1248832。今天的夸克查询可验真并匹配 `Digger.2026.1080p英语中字.mp4`。夸克愿望单 20 的最新任务 4618 在 2026-10-01 06:43:43 UTC 返回 needs_review，候选证据为 provider_inspection_unavailable（Cookie 过期或风控），之后不再自动巡检。文案错误标为 115。115 愿望单 19 持续重试；当前英文同名 115 结果不足以证明存在目标电影。

## 行为变化与兼容性

- 已知 TMDB 集号允许匹配中文“第 N 集”，包含中文数字；输出 SxxExx 原生重命名计划。错误季度、超出已知集号、多个冲突集号、弱身份与花絮仍拒绝。同集多个版本择优。
- 2026-10-10 补充统一 `episode_markers` 解析器：中文数字/阿拉伯数字的第 N 集、话/話、回，NFKC 全角字符，EP/Episode 加空格或分隔符，1x01；明确的 E01-E02、S01E01-E02、第1至2集、第一集到第二集保留覆盖集号并只生成一个范围重命名计划。最多接受连续四集的单文件范围；大范围合集、冲突标记拒绝自动匹配。
- 纯数字及“剧名 - 01”（可带明确质量后缀）需要已匹配的 PanSou 身份、文件名或父目录身份；后续季度还必须有明确季号。父目录与文件季号冲突时拒绝。复用现有无身份连续数字序列规则，不把 1080/720、编码、年份、日期当集号。
- 上集/下集、上篇/中篇/下篇以 TMDB 单集标题中的唯一篇章标记映射，不按文件排列猜序。不能唯一映射时返回 needs_review，保留候选，不生成自动重命名计划。特别篇/SP/OVA/OAD 不能归到正片季度，明确目标为 TMDB 第零季时才可匹配其季集标记。
- 搜索预演与追更使用同一 matcher；已存集数扫描、115 完成核验、OpenList 与整理入口继续使用 `episode_numbers_from_name`，该公开入口转用相同的明确标记解析器。上下篇和纯数字的上下文推断不会进入仅有文件名的完成核验。验证上下文只参与匹配，转存计划中的真实来源路径、文件 ID 保持原值。
- “纪录片”作为类型标签不再统一降权或排除；电影的“幕后纪录片”等衍生标题仍拒绝。
- 别名成为中文规范名的兜底。其他网盘、错误季号/年份与无关候选不再阻止兜底查询。
- 排除词只匹配标题和内容，英文短词按边界匹配；链接 ID、来源 ID、DTS/TCG 不再因为子串触发 TC/TS 排除。
- PanSou 请求明确传递 res；显式刷新只在首轮传 refresh=true，随后读取同一搜索代缓存，保留实例的频道/插件配置。
- 愿望单只有接口不可读取、没有已验证文件的候选时进入可重试失败。旧同类 needs_review 在至少一小时冷却后恢复巡检；关闭的订阅、有人工决定、真实版本歧义、异常证据或近期失败不自动恢复。
- 接口不可读文案改为所选网盘，避免夸克错误被标为 115。

Behavior changed：Yes。Database schema changed：No。Config/environment contract changed：No。API contract changed：No。Backward compatibility：沿用现有状态、候选证据、路由、参数与配置；未新增迁移。旧任务恢复仅按数据库已有证据执行，不按错误文案猜测。

## 验证

最初搜索修复验证为 182 passed、6 subtests passed。扩展命名规则后执行全后端回归，最终结果见下方。覆盖搜索与候选、PanSou 标准化、电影/电视剧/集数 resolver、资源缓存、磁力发现、愿望单接口与调度、追更交付、已存扫描、OpenList、115 完成和云下载整理合同。

集数解析仍归属 discover 的公开服务接缝，没有修改 Shared/Core、数据库、配置或 API。跨模块影响：tracking 使用相同 matcher；transfer、strm、openlist 通过已有文件名解析合同消费明确集数证据，包含在全后端回归中。新增 `tests/test_episode_marker_variants.py` 验证变体、冲突、错误季号、质量与日期、合并覆盖、待确认和来源路径/ID 保真。

最终代码执行 `PYTHONPATH=backend python -m pytest tests -q`：1470 passed、2 skipped、58 subtests passed（81.11 秒）。两个跳过沿用项目既有条件，未新增 skip；一条既有 Starlette/httpx 弃用提示。新增命名变体文件单独验证 48 passed。`git diff --check` 通过。

本地浏览器 `http://127.0.0.1:5173/` 显示 MediaIndex v0.8.0 与新版 SunnyUI。真实《缅北电诈覆灭纪实》详情显示夸克 3/3 集、E01/E02/E03、三集可转；115 暂无可转资源。截图位于 ignored `.tmp/acceptance/documentary-v080.jpg`。

扩展规则后重启本地后端、重新打开详情并点击“刷新资源”，新代码实际核对仍显示夸克 3/3 集、E01/E02/E03、三集可转。最终截图 `.tmp/acceptance/documentary-episode-variants.jpg`。未点击转存、同步、追更或通知按钮。

验收服务使用既有本地配置，后端以 lifespan off 启动，不启动调度、自动恢复或通知工作线程。未触发真实转存、同步或发布 Git；旧 NAS 任务需在用户更新修复后的版本时恢复。
