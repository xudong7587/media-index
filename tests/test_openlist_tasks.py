import unittest
from unittest.mock import Mock

from app.clients.openlist import OpenListClient


class OpenListTaskTests(unittest.TestCase):
    def test_copy_tasks_normalizes_undone_done_and_failed_rows(self):
        client = object.__new__(OpenListClient)
        responses = {
            "/api/task/copy/undone": {"code": 200, "data": [
                {"id": "running-1", "name": "copy Show to /115", "state": "running", "progress": 37.5, "total_bytes": 100},
                {"id": "failed-1", "name": "copy Movie", "state": "failed", "progress": 62, "error": "network error"},
            ]},
            "/api/task/copy/done": {"code": 200, "data": [
                {"id": "done-1", "name": "copy Done", "state": "succeeded", "progress": 100},
            ]},
        }
        client._get = Mock(side_effect=lambda path, **_kwargs: responses[path])

        tasks = client.copy_tasks()

        self.assertEqual(["running", "failed", "done"], [task["state"] for task in tasks])
        self.assertEqual(37.5, tasks[0]["progress"])
        self.assertEqual("network error", tasks[1]["error"])
        self.assertEqual(100.0, tasks[2]["progress"])
        client._get.assert_any_call("/api/task/copy/undone", timeout=5)
        client._get.assert_any_call("/api/task/copy/done", timeout=5)

    def test_copy_task_progress_is_bounded(self):
        client = object.__new__(OpenListClient)
        client._get = Mock(side_effect=lambda path, **_kwargs: {"code": 200, "data": [{"id": "a", "progress": 150}, {"id": "b", "progress": "invalid"}]} if path.endswith("undone") else {"code": 200, "data": []})
        tasks = client.copy_tasks()
        self.assertEqual([100.0, 0.0], [task["progress"] for task in tasks])


if __name__ == "__main__":
    unittest.main()
