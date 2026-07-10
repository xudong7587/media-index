from __future__ import annotations

import copy

from app.clients.qas import QasClient
from app.domain.media import LinkResolution, MediaTarget, QasExecutionResult
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
    original = _find_task(client.tasklist(), taskname)
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

    try:
        for pair in resolution.rename_pairs:
            current = copy.deepcopy(base)
            current["pattern"] = pair.pattern
            current["replace"] = pair.replacement
            current["runweek"] = []
            current.pop("shareurl_ban", None)
            output = client.run_task(current)
            if not qas_trigger_accepted(output):
                raise RuntimeError(_qas_error(output))
            outputs.append(output if isinstance(output, dict) else {"raw": str(output)})
            executed += 1
            base = current

        base["runweek"] = []
        _save_one_task(client, base)
    except Exception as exc:
        try:
            _restore_task(client, taskname, original)
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

    confirmed = all(qas_transfer_confirmed(output) for output in outputs)
    if not confirmed:
        confirmed = qas_saved_files_confirmed(client, save_path, [pair.replacement for pair in resolution.rename_pairs])
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
    if any(marker in raw for marker in ("traceback", "exception", "执行失败", "转存失败")):
        return False
    return True


def qas_transfer_confirmed(output: object) -> bool:
    if not qas_trigger_accepted(output) or not isinstance(output, dict):
        return False
    if output.get("confirmed") is True:
        return True
    raw = str(output.get("raw") or output.get("message") or "")
    failure_markers = ("任务执行失败", "转存失败", "执行异常", "traceback", "exception")
    if any(marker.casefold() in raw.casefold() for marker in failure_markers):
        return False
    success_markers = ("任务执行成功", "转存成功", "没有新的转存任务")
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
        if isinstance(item, dict) and not item.get("dir")
    }
    return all(name in found for name in expected_names)


def _qas_error(output: object) -> str:
    if isinstance(output, dict):
        return str(output.get("error") or output.get("message") or output.get("raw") or "unknown QAS error")
    return str(output)


def _find_task(tasklist: list[dict], taskname: str) -> dict | None:
    item = next((task for task in tasklist if task.get("taskname") == taskname), None)
    return copy.deepcopy(item) if item else None


def _save_one_task(client: QasClient, task: dict) -> None:
    tasklist = client.tasklist()
    index = next((i for i, item in enumerate(tasklist) if item.get("taskname") == task["taskname"]), None)
    if index is None:
        tasklist.append(copy.deepcopy(task))
    else:
        tasklist[index] = copy.deepcopy(task)
    result = client.save_tasklist(tasklist)
    if isinstance(result, dict) and (result.get("success") is False or result.get("ok") is False or result.get("error")):
        raise RuntimeError(_qas_error(result))


def _restore_task(client: QasClient, taskname: str, original: dict | None) -> None:
    tasklist = client.tasklist()
    index = next((i for i, item in enumerate(tasklist) if item.get("taskname") == taskname), None)
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
