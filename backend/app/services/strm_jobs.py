from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from app.db.database import db
from app.services.cloud_inventory import scan_p115_inventory, scan_quark_inventory
from app.services.strm_reconciler import reconcile_strm
from app.services.emby_library_refresh import refresh_emby_library_after_strm


def create_strm_job(*, provider: Literal["p115", "quark"], mode: Literal["incremental", "full"], root_path: str, output_root: str, playback_base_url: str = "") -> int:
    label = "115" if provider == "p115" else "夸克"
    with db() as conn:
        cursor = conn.execute(
            """INSERT INTO transfer_jobs(target,provider,status,stage,message,display_title,save_path,source_file,renamed_file,execution_key)
               VALUES ('local','strm','ready','strm_queued',?,'STRM 生成',?,?,?,?)""",
            (f"{label} {('全量扫描并' if mode == 'full' else '')}生成已排队", output_root, root_path, mode, f"strm:{provider}:{mode}"),
        )
        return int(cursor.lastrowid)


def run_strm_job(job_id: int, *, provider: Literal["p115", "quark"], mode: Literal["incremental", "full"], root_path: str, output_root: str, playback_base_url: str = "") -> None:
    try:
        _update(job_id, "running", "strm_generating", "正在生成 STRM 文件")
        scan_note = ""
        if mode == "full":
            _update(job_id, "running", "strm_scanning", "正在只读扫描网盘目录")
            scan = scan_p115_inventory(root_path) if provider == "p115" else scan_quark_inventory(root_path)
            scan_note = f"扫描 {scan.files_indexed} 个文件；"
            _update(job_id, "running", "strm_generating", "扫描完成，正在生成 STRM 文件")
        result = reconcile_strm(output_root=output_root, playback_base_url=playback_base_url, provider=provider)
        data = asdict(result)
        emby_message = refresh_emby_library_after_strm() if data["created"] or data["replaced"] else ""
        message = f"{scan_note}新增 {data['created']}，替换 {data['replaced']}，保持 {data['unchanged']}，过滤 {data['filtered']}，冲突 {data['conflicts']}，清理 {data['removed']}。{emby_message}"
        _update(job_id, "done", "strm_completed", message, finished=True)
    except Exception as exc:
        _update(job_id, "failed", "strm_failed", f"STRM 生成失败（{type(exc).__name__}）", finished=True)


def _update(job_id: int, status: str, stage: str, message: str, *, finished: bool = False) -> None:
    with db() as conn:
        if finished:
            conn.execute("UPDATE transfer_jobs SET status=?,stage=?,message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?", (status, stage, message, job_id))
        else:
            conn.execute("UPDATE transfer_jobs SET status=?,stage=?,message=? WHERE id=?", (status, stage, message, job_id))
