from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def main() -> int:
    playback_port = _playback_port()
    commands = [
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        [sys.executable, "-m", "uvicorn", "app.playback_main:app", "--host", "0.0.0.0", "--port", str(playback_port)],
    ]
    processes = [subprocess.Popen(command) for command in commands]

    def stop(_signum: int | None = None, _frame: object | None = None) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            for process in processes:
                status = process.poll()
                if status is not None:
                    stop()
                    return int(status)
            time.sleep(0.25)
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def _playback_port() -> int:
    raw = os.getenv("MEDIA_PLAYBACK_INTERNAL_PORT", "8097").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit("MEDIA_PLAYBACK_INTERNAL_PORT must be an integer") from exc
    if port < 1024 or port > 65535 or port == 8000:
        raise SystemExit("MEDIA_PLAYBACK_INTERNAL_PORT must be between 1024 and 65535 and cannot be 8000")
    return port


if __name__ == "__main__":
    raise SystemExit(main())
