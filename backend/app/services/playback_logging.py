"""Redact credentials in public cloud playback access logs."""
import logging
import re


def redact_playback_path(path):
    return re.sub(r"(/api/cloud-video/source/)[^/? ]+", r"\1[redacted]", path)


class PlaybackAccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            target = record.args[2]
            if target.startswith('/api/cloud-video/'):
                target = redact_playback_path(target)
                target = re.sub(r"([?&]st=)[^& ]+", r"\1[redacted]", target)
                record.args = (*record.args[:2], target, *record.args[3:])
        return True


def configure_access_log_redaction():
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(f, PlaybackAccessLogFilter) for f in logger.filters):
        logger.addFilter(PlaybackAccessLogFilter())
