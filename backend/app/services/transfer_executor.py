import os
import re
import time
from dataclasses import dataclass

from app.clients.pansou import PansouClient
from app.clients.qas import QasClient


VIDEO_EXTS = (".mkv", ".mp4", ".ts", ".m2ts", ".mov", ".avi", ".wmv", ".flv")


@dataclass
class TransferPlan:
    taskname: str
    share_url: str
    pattern: str
    replace: str
    message: str


def execute_cloud_transfer(title: str, year: str, media_type: str, save_path: str, season_number: int | None = None) -> dict:
    qas = QasClient()
    if not qas.configured():
        return {"ok": False, "stage": "qas_not_configured", "message": "QAS 尚未配置，无法执行网盘转存"}

    plan_result = build_transfer_plan(title, year, media_type, season_number)
    if not plan_result.get("ok"):
        return plan_result
    plan: TransferPlan = plan_result["plan"]

    weekday = time.localtime().tm_wday + 1
    task = {
        "taskname": plan.taskname,
        "shareurl": plan.share_url,
        "savepath": save_path,
        "pattern": plan.pattern,
        "replace": plan.replace,
        "runweek": [],
        "extract_code": "",
    }

    try:
        qas.ensure_task(task)
        qas.set_runweek(plan.taskname, [weekday])
        run_result = qas.run_now(plan.taskname)
        qas.set_runweek(plan.taskname, [])
    except Exception as exc:
        try:
            qas.set_runweek(plan.taskname, [])
        except Exception:
            pass
        return {"ok": False, "stage": "qas_failed", "message": f"QAS 执行失败：{exc}"}

    return {
        "ok": True,
        "stage": "qas_triggered",
        "message": plan.message,
        "taskname": plan.taskname,
        "share_url": plan.share_url,
        "pattern": plan.pattern,
        "replace": plan.replace,
        "qas_result": run_result,
    }


def build_transfer_plan(title: str, year: str, media_type: str, season_number: int | None = None) -> dict:
    candidates = verified_candidates(title, year, season_number)
    if not candidates:
        return {"ok": False, "stage": "no_resource", "message": "PanSou 未找到可用的夸克资源，稍后可以重试"}

    best = candidates[0]
    share_url = best["share_url"]
    files = best.get("files", [])
    source = choose_best_video(files)
    taskname = f"{title}.{year}" if year else title

    if source and media_type == "movie":
        if not movie_file_matches(title, year, source["name"], best.get("title", "")):
            return {"ok": False, "stage": "needs_review", "message": "??????????????????????????"}
        ext = os.path.splitext(source["name"])[1] or ".mp4"
        return {
            "ok": True,
            "plan": TransferPlan(
                taskname=taskname,
                share_url=share_url,
                pattern=source["name"],
                replace=f"{taskname}{ext}",
                message=f"已找到资源并触发 QAS：{source['name']} → {taskname}{ext}",
            ),
        }

    if source and media_type in ("tv", "variety") and season_number:
        return {"ok": False, "stage": "needs_review", "message": "已找到候选资源，但剧集/综艺需要完成集号匹配后才能转存，已转入待确认"}

    return {"ok": False, "stage": "needs_review", "message": "已找到候选资源，但没有匹配到可安全转存的具体视频文件，已转入待确认"}


def search_resource_availability(title: str, year: str, season_number: int | None = None) -> dict:
    pansou = PansouClient()
    if not pansou.configured():
        return {"ok": True, "found": False, "message": "暂无资源"}
    results = pansou.search(title, limit=1, timeout=4)
    if not results:
        return {"ok": True, "found": False, "message": "暂无资源"}
    first = results[0]
    return {
        "ok": True,
        "found": True,
        "message": "已找到资源",
        "title": first.get("title", ""),
        "share_url": first.get("share_url", ""),
        "file_count": 0,
    }


def verified_candidates(title: str, year: str, season_number: int | None) -> list[dict]:
    pansou = PansouClient()
    qas = QasClient()
    if not pansou.configured():
        return []
    queries = resource_queries(title, year, season_number)
    results = []
    for query in queries:
        results = pansou.search(query, limit=8)
        if results:
            break
    if not results:
        try:
            for query in queries:
                results = qas.task_suggestions(query)[:8]
                if results:
                    break
        except Exception:
            results = []
    verified = []
    seen = set()
    for item in results:
        share_url = item.get("share_url", "")
        if not share_url or share_url in seen:
            continue
        seen.add(share_url)
        try:
            detail = qas.share_detail(share_url)
        except Exception:
            continue
        files, child_url = extract_share_files(detail, share_url)
        if files:
            verified.append({"share_url": child_url, "title": item.get("title", ""), "files": files})
    return verified


def resource_queries(title: str, year: str, season_number: int | None) -> list[str]:
    queries = []
    if season_number:
        queries.append(f"{title} 第{season_number}季")
    queries.append(title)
    if year:
        queries.append(f"{title} {year}")
    return queries


def extract_share_files(detail: dict, share_url: str) -> tuple[list[dict], str]:
    payload = detail.get("data", detail) if isinstance(detail, dict) else {}
    if isinstance(payload, dict) and payload.get("success") is False:
        return [], share_url
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    share = data.get("share", {}) if isinstance(data, dict) else {}
    first_file = data.get("first_file") or share.get("first_file") or {}
    files = data.get("files") or data.get("list") or []
    if not files and first_file:
        files = [first_file]
    normalized = []
    for file in files:
        name = file.get("file_name") or file.get("name") or ""
        if not name:
            continue
        size = file.get("size") or file.get("file_size") or 0
        try:
            size = int(size)
        except Exception:
            size = 0
        normalized.append({"name": name, "size": size, "is_dir": bool(file.get("dir"))})
    fid = data.get("first_fid") or share.get("first_fid") or first_file.get("fid") or ""
    is_dir = bool(first_file.get("dir")) if isinstance(first_file, dict) else any(file.get("is_dir") for file in normalized)
    child_url = share_url
    if is_dir and fid:
        child_url = share_url.split("#")[0] + f"#/list/share/{fid}"
    return normalized, child_url


def movie_file_matches(title: str, year: str, filename: str, source_title: str = "") -> bool:
    haystack = normalize_text(f"{filename} {source_title}")
    tokens = title_tokens(title)
    if tokens and not any(token in haystack for token in tokens):
        return False
    if year and re.search(r"(19|20)\d{2}", haystack) and year not in haystack:
        return False
    return True


def title_tokens(title: str) -> list[str]:
    normalized = normalize_text(title)
    tokens = [normalized] if normalized else []
    ascii_parts = [part for part in re.split(r"[^a-z0-9]+", normalized) if len(part) >= 3]
    tokens.extend(ascii_parts)
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", title))
    if len(cjk) >= 2:
        tokens.append(cjk.lower())
    return list(dict.fromkeys(tokens))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())


def choose_best_video(files: list[dict]) -> dict | None:
    videos = [file for file in files if file.get("name", "").lower().endswith(VIDEO_EXTS)]
    if not videos:
        return None
    return max(videos, key=lambda item: item.get("size", 0))
