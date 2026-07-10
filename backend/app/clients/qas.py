import json
import urllib.parse
import urllib.request

from app.core.config import get_settings


class QasClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def configured(self) -> bool:
        return bool(self.settings.qas_base_url and self.settings.qas_token)

    def _url(self, endpoint: str, params: dict | None = None) -> str:
        p = dict(params or {})
        p["token"] = self.settings.qas_token
        return f"{self.settings.qas_base_url.rstrip('/')}{endpoint}?{urllib.parse.urlencode(p)}"

    def get(self, endpoint: str, params: dict | None = None, timeout: int = 15) -> dict:
        with urllib.request.urlopen(self._url(endpoint, params), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, endpoint: str, data: dict | None = None, timeout: int = 60) -> dict:
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(
            self._url(endpoint),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"ok": True, "raw": raw}

    def share_detail(self, share_url: str) -> dict:
        return self.post("/get_share_detail", {"shareurl": share_url, "a": "1"}, timeout=30)

    def savepath_detail(self, path: str) -> dict:
        return self.get("/get_savepath_detail", {"path": path}, timeout=30)

    def task_suggestions(self, keyword: str) -> list[dict]:
        data = self.get("/task_suggestions", {"q": keyword, "d": "1"})
        items = data if isinstance(data, list) else data.get("suggestions", data.get("data", []))
        if isinstance(items, dict):
            items = list(items.values())
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("shareurl") or item.get("url") or ""
            if "pan.quark.cn" not in url:
                continue
            results.append(
                {
                    "share_url": url,
                    "title": item.get("title") or item.get("name") or item.get("note") or "",
                    "source": item.get("source") or "qas",
                }
            )
        return results

    def data(self) -> dict:
        return self.get("/data")

    def task_data(self) -> dict:
        data = self.data()
        return data.get("data", data) if isinstance(data, dict) else {}

    def tasklist(self) -> list[dict]:
        data = self.task_data()
        tasklist = data.get("tasklist", [])
        return tasklist if isinstance(tasklist, list) else []

    def save_tasklist(self, tasklist: list[dict]) -> dict:
        return self.post("/update", {"tasklist": tasklist}, timeout=30)

    def ensure_task(self, task: dict) -> dict:
        tasklist = self.tasklist()
        taskname = task["taskname"]
        existing_index = next((i for i, item in enumerate(tasklist) if item.get("taskname") == taskname), None)
        if existing_index is None:
            tasklist.append(task)
        else:
            current = dict(tasklist[existing_index])
            current.update(task)
            current.pop("shareurl_ban", None)
            tasklist[existing_index] = current
        self.save_tasklist(tasklist)
        return {"ok": True, "taskname": taskname, "created": existing_index is None}

    def set_runweek(self, taskname: str, runweek: list[int]) -> dict:
        tasklist = self.tasklist()
        for task in tasklist:
            if task.get("taskname") == taskname:
                task["runweek"] = runweek
                task.pop("shareurl_ban", None)
                self.save_tasklist(tasklist)
                return {"ok": True}
        return {"ok": False, "error": f"QAS task not found: {taskname}"}

    def run_now(self, taskname: str) -> dict:
        try:
            return self.get("/run_script_now", {"taskname": taskname}, timeout=180)
        except Exception:
            return self.post("/run_script_now", {"taskname": taskname}, timeout=180)

    def run_task(self, task: dict) -> dict:
        """Run exactly one in-memory task without saving the complete QAS config."""
        return self.post("/run_script_now", {"tasklist": [task]}, timeout=180)
