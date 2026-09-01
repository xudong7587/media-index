import unittest
from unittest.mock import Mock, patch

from app.api.openlist import clear_finished_openlist_copy_tasks
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
                {"id": "done-1", "name": "copy Done", "state": "succeeded", "status": "uploading", "progress": 50},
            ]},
        }
        client._get = Mock(side_effect=lambda path, **_kwargs: responses[path])

        tasks = client.copy_tasks()

        self.assertEqual(["running", "failed", "done"], [task["state"] for task in tasks])
        self.assertEqual(37.5, tasks[0]["progress"])
        self.assertEqual("network error", tasks[1]["error"])
        self.assertEqual(100.0, tasks[2]["progress"])
        self.assertEqual("completed", tasks[2]["status"])
        client._get.assert_any_call("/api/task/copy/undone", timeout=5)
        client._get.assert_any_call("/api/task/copy/done", timeout=5)

    def test_copy_task_progress_is_bounded(self):
        client = object.__new__(OpenListClient)
        client._get = Mock(side_effect=lambda path, **_kwargs: {"code": 200, "data": [{"id": "a", "progress": 150}, {"id": "b", "progress": "invalid"}]} if path.endswith("undone") else {"code": 200, "data": []})
        tasks = client.copy_tasks()
        self.assertEqual([100.0, 0.0], [task["progress"] for task in tasks])

    def test_clear_finished_copy_tasks_uses_openlist_clear_done_endpoint(self):
        client = object.__new__(OpenListClient)
        client._post = Mock(return_value={"code": 200})
        client.clear_finished_copy_tasks()
        client._post.assert_called_once_with("/api/task/copy/clear_done", {})

    @patch("app.api.openlist.OpenListClient")
    @patch("app.api.openlist.get_settings")
    def test_clear_finished_copy_tasks_api_delegates_to_openlist(self, settings, client_class):
        settings.return_value.openlist_enabled = True
        settings.return_value.openlist_token = "token"
        result = clear_finished_openlist_copy_tasks()
        self.assertTrue(result["ok"])
        client_class.return_value.clear_finished_copy_tasks.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
