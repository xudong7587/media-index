import copy
import unittest

from app.domain.media import EpisodeMatch, EpisodeTarget, LinkResolution, MediaTarget, RenamePair, SourceFile
from app.services.qas_executor import execute_qas_plan


class FakeQas:
    def __init__(self, tasks=None, fail_on_run=0):
        self.tasks = copy.deepcopy(tasks or [])
        self.fail_on_run = fail_on_run
        self.run_calls = 0

    def tasklist(self):
        return copy.deepcopy(self.tasks)

    def save_tasklist(self, tasklist):
        self.tasks = copy.deepcopy(tasklist)
        return {"ok": True}

    def run_task(self, task):
        self.run_calls += 1
        if self.fail_on_run == self.run_calls:
            return {"success": False, "message": "simulated failure"}
        return {"ok": True, "raw": "data: accepted"}


def plan():
    target = MediaTarget(123, "tv", "测试剧", series_year="2026", season_number=1)
    pairs = (
        RenamePair("ep1.mkv", r"^ep1\.mkv$", "测试剧.2026.S01E01.mkv", 1),
        RenamePair("ep2.mkv", r"^ep2\.mkv$", "测试剧.2026.S01E02.mkv", 2),
    )
    resolution = LinkResolution(True, "ready", "ok", "https://pan.quark.cn/s/new", "pansou", rename_pairs=pairs)
    return target, resolution


class QasExecutorTests(unittest.TestCase):
    def test_executes_each_pair_and_clears_runweek(self):
        target, resolution = plan()
        qas = FakeQas()
        result = execute_qas_plan(target, resolution, "/tv/测试剧", qas=qas)
        self.assertTrue(result.ok)
        self.assertEqual(2, result.executed_pairs)
        self.assertFalse(result.confirmed)
        self.assertEqual(2, qas.run_calls)
        self.assertEqual([], qas.tasks[0]["runweek"])
        self.assertEqual("测试剧.2026.S01E02.mkv", qas.tasks[0]["replace"])

    def test_failure_restores_existing_task_exactly(self):
        target, resolution = plan()
        original = {
            "taskname": "测试剧.2026.S01",
            "shareurl": "https://pan.quark.cn/s/old",
            "savepath": "/old",
            "pattern": "old-pattern",
            "replace": "old-replace",
            "runweek": [7],
            "plugin": {"smartstrm": True},
        }
        qas = FakeQas([original], fail_on_run=2)
        result = execute_qas_plan(target, resolution, "/tv/测试剧", qas=qas)
        self.assertFalse(result.ok)
        self.assertEqual("qas_failed_rolled_back", result.stage)
        self.assertEqual([original], qas.tasks)

    def test_non_ready_plan_never_touches_qas(self):
        target, _ = plan()
        qas = FakeQas()
        result = execute_qas_plan(target, LinkResolution(False, "needs_review", "review"), "/tv", qas=qas)
        self.assertFalse(result.ok)
        self.assertEqual(0, qas.run_calls)
        self.assertEqual([], qas.tasks)

    def test_explicit_qas_success_is_confirmed(self):
        class ConfirmingQas(FakeQas):
            def run_task(self, task):
                self.run_calls += 1
                return {"ok": True, "raw": "data: >>> 任务执行成功"}

        target, resolution = plan()
        result = execute_qas_plan(target, resolution, "/tv/测试剧", qas=ConfirmingQas())
        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)
        self.assertEqual("qas_completed", result.stage)


if __name__ == "__main__":
    unittest.main()
