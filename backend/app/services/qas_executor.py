from __future__ import annotations

import copy
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.clients.qas import QasClient
from app.core.config import get_settings
from app.domain.media import LinkResolution, MediaTarget, QasExecutionResult
from app.services.candidate_ranker import compact, extract_seasons
from app.services.episode_matcher import sanitize_filename_component
from app.services.paths import is_allowed_save_path


def execute_qas_plan(
    target: MediaTarget,
    resolution: LinkResolution,
    save_path: str,
    *,
    qas: QasClient | None = None,
    allow_review_confirmed: bool = False,
) -> QasExecutionResult:
    if not resolution.ok or resolution.stage != "ready":
        return QasExecutionResult(False, "plan_not_ready", "候选资源尚未达到自动执行条件")
    if not resolution.rename_pairs:
        return QasExecutionResult(False, "empty_plan", "没有可执行的文件重命名映射")
    if not is_allowed_save_path(target.media_type, save_path):
        return QasExecutionResult(
            False,
            "invalid_save_path",
            "保存路径不在配置的根路径和分类目录内，已拒绝执行 QAS",
        )
    if not allow_review_confirmed and any(pair.confidence != "high" for pair in resolution.rename_pairs):
        return QasExecutionResult(False, "needs_review", "重命名计划包含非高置信匹配")

    client = qas or QasClient()
    taskname = build_qas_taskname(target)
    tasklist = client.tasklist()
    original = _find_task(tasklist, taskname)
    if original is None:
        original = _find_legacy_task(tasklist, target, resolution.share_url)
    original_taskname = str(original.get("taskname") or "") if original else ""
    base = copy.deepcopy(original) if original else {"taskname": taskname, "extract_code": ""}
    base.update(
        {
            "taskname": taskname,
            "shareurl": resolution.share_url,
            "savepath": save_path,
            "runweek": [],
        }
    )
    base.pop("shareurl_ban", None)
    outputs: list[dict] = []
    executed = 0
    execution_weekday = datetime.now(ZoneInfo(get_settings().tracking_timezone)).isoweekday()

    try:
        for pair in resolution.rename_pairs:
            current = copy.deepcopy(base)
            current["pattern"] = pair.pattern
            current["replace"] = pair.replacement
            current["runweek"] = [execution_weekday]
            current.pop("shareurl_ban", None)
            output = client.run_task(current)
            if not qas_trigger_accepted(output):
                raise RuntimeError(_qas_error(output))
            outputs.append(output if isinstance(output, dict) else {"raw": str(output)})
            executed += 1
            base = current

        base["runweek"] = []
        _save_one_task(client, base, previous_taskname=original_taskname)
    except Exception as exc:
        try:
            _restore_task(client, taskname, original, original_taskname)
        except Exception as rollback_exc:
            return QasExecutionResult(
                False,
                "qas_failed_rollback_failed",
                f"QAS 执行失败且任务恢复失败：{exc}; rollback={rollback_exc}",
                taskname,
                executed,
                False,
                tuple(outputs),
            )
        return QasExecutionResult(
            False,
            "qas_failed_rolled_back",
            f"QAS 单任务执行失败，原配置未被改变：{exc}",
            taskname,
            executed,
            False,
            tuple(outputs),
        )

    output_confirmed = all(qas_transfer_confirmed(output) for output in outputs)
    files_confirmed = qas_saved_files_confirmed(client, save_path, [pair.replacement for pair in resolution.rename_pairs])
    confirmed = output_confirmed and files_confirmed
    return QasExecutionResult(
        True,
        "qas_completed" if confirmed else "qas_triggered",
        "QAS 已确认全部精确转存任务完成" if confirmed else "QAS 已接受全部精确转存任务，等待结果确认",
        taskname,
        executed,
        confirmed,
        tuple(outputs),
    )


def build_qas_taskname(target: MediaTarget) -> str:
    title = sanitize_filename_component(target.title)
    year = target.series_year or target.season_year
    parts = [title]
    if year:
        parts.append(year)
    if target.season_number is not None:
        parts.append(f"S{target.season_number:02d}")
    return ".".join(parts)


def qas_trigger_accepted(output: object) -> bool:
    if not isinstance(output, dict):
        return False
    if output.get("success") is False or output.get("ok") is False or output.get("error"):
        return False
    raw = str(output.get("raw") or "").casefold()
    if any(marker in raw for marker in ("traceback", "exception", "执行失败", "转存失败", "任务不在运行周期内", "跳过")):
        return False
    if output.get("success") is True or output.get("ok") is True or output.get("accepted") is True:
        return True
    accepted_markers = ("任务执行成功", "转存成功", "没有新的转存任务", "任务执行完成")
    return any(marker.casefold() in raw for marker in accepted_markers)


def qas_transfer_confirmed(output: object) -> bool:
    if not qas_trigger_accepted(output) or not isinstance(output, dict):
        return False
    if output.get("confirmed") is True:
        return True
    raw = str(output.get("raw") or output.get("message") or "")
    failure_markers = ("任务执行失败", "转存失败", "执行异常", "traceback", "exception")
    if any(marker.casefold() in raw.casefold() for marker in failure_markers):
        return False
    success_markers = ("任务执行成功", "转存成功")
    return any(marker in raw for marker in success_markers)


def qas_saved_files_confirmed(client, save_path: str, expected_names: list[str]) -> bool:
    if not expected_names or not hasattr(client, "savepath_detail"):
        return False
    try:
        response = client.savepath_detail(save_path)
    except Exception:
        return False
    if not isinstance(response, dict) or response.get("success") is False:
        return False
    payload = response.get("data", response)
    if isinstance(payload, dict):
        files = payload.get("list") or payload.get("files") or []
    else:
        files = []
    found = {
        str(item.get("file_name") or item.get("name") or "")
        for item in files
        if isinstance(item, dict) and not item.get("dir") and int(item.get("size") or 0) > 0
    }
    return all(name in found for name in expected_names)


def _qas_error(output: object) -> str:
    if isinstance(output, dict):
        return str(output.get("error") or output.get("message") or output.get("raw") or "unknown QAS error")
    return str(output)


def _find_task(tasklist: list[dict], taskname: str) -> dict | None:
    item = next((task for task in tasklist if task.get("taskname") == taskname), None)
    return copy.deepcopy(item) if item else None


def _find_legacy_task(tasklist: list[dict], target: MediaTarget, share_url: str) -> dict | None:
    candidates: list[tuple[int, int, dict]] = []
    for score, index, task in compatible_qas_tasks(tasklist, target):
        if share_url and str(task.get("shareurl") or "") == share_url:
            score += 50
        candidates.append((score, index, task))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return copy.deepcopy(candidates[0][2])


def compatible_qas_tasks(tasklist: list[dict], target: MediaTarget) -> list[tuple[int, int, dict]]:
    aliases = [compact(value) for value in target.search_titles if len(compact(value)) >= 2]
    accepted_years = {value for value in (target.series_year, target.season_year) if value}
    candidates: list[tuple[int, int, dict]] = []
    for index, task in enumerate(tasklist):
        if not isinstance(task, dict):
            continue
        evidence_text = " ".join(str(task.get(key) or "") for key in ("taskname", "savepath", "savename"))
        if not any(_task_title_matches(task, alias) for alias in aliases):
            continue
        seasons = extract_seasons(evidence_text.casefold())
        if target.season_number is not None and seasons and target.season_number not in seasons:
            continue
        found_years = set(re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", evidence_text))
        if found_years and accepted_years and not found_years & accepted_years:
            continue
        score = 100
        if target.season_number is not None and target.season_number in seasons:
            score += 30
        if found_years & accepted_years:
            score += 20
        candidates.append((score, index, task))
    return candidates


def _task_title_matches(task: dict, alias: str) -> bool:
    taskname = compact(str(task.get("taskname") or ""))
    if not taskname or alias not in taskname:
        return False
    if len(alias) >= 4:
        return True
    if not taskname.startswith(alias):
        return False
    suffix = taskname[len(alias) :]
    return not suffix or bool(re.match(r"(?:(?:19|20)\d{2}|s\d{1,2}|第[一二三四五六七八九十\d]+季)", suffix))


def disable_compatible_qas_schedules(target: MediaTarget, client: QasClient) -> int:
    tasklist = client.tasklist()
    changed = 0
    for _, index, _ in compatible_qas_tasks(tasklist, target):
        if tasklist[index].get("runweek"):
            tasklist[index]["runweek"] = []
            changed += 1
    if not changed:
        return 0
    result = client.save_tasklist(tasklist)
    if isinstance(result, dict) and (result.get("success") is False or result.get("ok") is False or result.get("error")):
        raise RuntimeError(_qas_error(result))
    return changed


def _save_one_task(client: QasClient, task: dict, previous_taskname: str = "") -> None:
    tasklist = client.tasklist()
    if previous_taskname and previous_taskname != task["taskname"]:
        tasklist = [item for item in tasklist if item.get("taskname") != previous_taskname]
    index = next((i for i, item in enumerate(tasklist) if item.get("taskname") == task["taskname"]), None)
    if index is None:
        tasklist.append(copy.deepcopy(task))
    else:
        tasklist[index] = copy.deepcopy(task)
    result = client.save_tasklist(tasklist)
    if isinstance(result, dict) and (result.get("success") is False or result.get("ok") is False or result.get("error")):
        raise RuntimeError(_qas_error(result))


def _restore_task(
    client: QasClient,
    taskname: str,
    original: dict | None,
    original_taskname: str = "",
) -> None:
    tasklist = client.tasklist()
    if original_taskname and original_taskname != taskname:
        tasklist = [item for item in tasklist if item.get("taskname") != taskname]
    lookup_name = original_taskname or taskname
    index = next((i for i, item in enumerate(tasklist) if item.get("taskname") == lookup_name), None)
    if original is None:
        if index is not None:
            tasklist.pop(index)
    elif index is None:
        tasklist.append(copy.deepcopy(original))
    else:
        tasklist[index] = copy.deepcopy(original)
    result = client.save_tasklist(tasklist)
    if isinstance(result, dict) and (result.get("success") is False or result.get("ok") is False or result.get("error")):
        raise RuntimeError(_qas_error(result))
