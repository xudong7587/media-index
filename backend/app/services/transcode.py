"""Optional worker transport; disabled unless explicitly configured."""
import logging
import os
import re

import httpx


def redact_transcode_path(path):
    return re.sub(r"(/api/transcode/(?:buffer/)?source/)[^/? ]+", r"\1[redacted]", path)


class TranscodeError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class TranscodeAccessLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn logs the raw request target separately from diagnostic events.
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            target = record.args[2]
            if target.startswith("/api/transcode/"):
                target = re.sub(r"(/source/)[^? ]+", r"\1[redacted]", target)
                target = re.sub(r"([?&]st=)[^& ]+", r"\1[redacted]", target)
                record.args = (*record.args[:2], target, *record.args[3:])
        return True


def configure_access_log_redaction():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, TranscodeAccessLogFilter) for f in logger.filters):
        logger.addFilter(TranscodeAccessLogFilter())


def worker_config():
    url = os.environ.get("TRANSCODE_WORKER_URL", "").rstrip("/")
    key = os.environ.get("TRANSCODE_WORKER_KEY", "")
    if not url or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key):
        raise TranscodeError(503, "转码服务未配置")
    return url, key


def call_worker(method, path, *, payload=None, session_token=""):
    url, key = worker_config()
    try:
        with httpx.Client(timeout=35, trust_env=False) as client:
            response = client.request(method, url + path, json=payload,
                headers={"Authorization": "Bearer " + key, "X-Session-Token": session_token})
    except httpx.HTTPError:
        raise TranscodeError(503, "转码服务暂时不可用") from None
    if response.status_code >= 400:
        raise TranscodeError(response.status_code if response.status_code in {400, 403, 404, 409, 429, 503, 504} else 502,
                            "转码请求未完成")
    return response
