import copy
import unittest

from app.domain.media import EpisodeMatch, EpisodeTarget, LinkResolution, MediaTarget, RenamePair, ResourceCandidate, SourceFile
from app.services.qas_executor import disable_compatible_qas_schedules, execute_qas_plan, qas_saved_files_confirmed


class FakeQas:
    def __init__(self, tasks=None, fail_on_run=0):
        self.tasks = copy.deepcopy(tasks or [])
        self.fail_on_run = fail_on_run
        self.run_calls = 0
        self.run_payloads = []

    def tasklist(self):
        return copy.deepcopy(self.tasks)

    def save_tasklist(self, tasklist):
        self.tasks = copy.deepcopy(tasklist)
        return {"ok": True}

    def run_task(self, task):
        self.run_calls += 1
        self.run_payloads.append(copy.deepcopy(task))
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
    def test_tv_pro_keeps_same_numbered_files_isolated_by_season(self):
        qas = FakeQas()
        for season_number in (1, 2):
            target = MediaTarget(123, "tv", "测试动画", series_year="2026", season_number=season_number)
            pairs = tuple(
                RenamePair(
                    f"{number:02d}.mkv",
                    rf"^{number:02d}\.mkv$",
                    f"测试动画.2026.S{season_number:02d}E{number:02d}.mkv",
                    number,
                    episode_numbers=(number,),
                )
                for number in range(1, 4)
            )
            share_url = f"https://pan.quark.cn/s/multi#/list/share/s{season_number}"
            candidate = ResourceCandidate(share_url, files=tuple(pair.source_name for pair in pairs))
            resolution = LinkResolution(
                True,
                "ready",
                "ok",
                share_url,
                "cached_multi_season_folder",
                rename_pairs=pairs,
                reviewed_candidates=(candidate,),
            )

            result = execute_qas_plan(target, resolution, "/strm/tv/测试动画(2026)", qas=qas)

            self.assertTrue(result.ok)

        self.assertEqual(2, qas.run_calls)
        self.assertEqual(
            ["测试动画.2026.S01", "测试动画.2026.S02"],
            [payload["taskname"] for payload in qas.run_payloads],
        )
        self.assertEqual(
            [
                "https://pan.quark.cn/s/multi#/list/share/s1",
                "https://pan.quark.cn/s/multi#/list/share/s2",
            ],
            [payload["shareurl"] for payload in qas.run_payloads],
        )
        self.assertTrue(all(payload["pattern"] == "$TV_PRO" for payload in qas.run_payloads))
        self.assertTrue(all(payload["replace"] == "" for payload in qas.run_payloads))

    def test_simple_complete_numbered_folder_uses_one_tv_pro_run(self):
        target = MediaTarget(123, "tv", "测试动画", series_year="2026", season_number=1)
        pairs = tuple(
            RenamePair(
                f"{number:02d}.mkv",
                rf"^{number:02d}\.mkv$",
                f"测试动画.2026.S01E{number:02d}.mkv",
                number,
                episode_numbers=(number,),
            )
            for number in range(1, 5)
        )
        share_url = "https://pan.quark.cn/s/clean"
        candidate = ResourceCandidate(share_url, files=tuple(pair.source_name for pair in pairs))
        resolution = LinkResolution(
            True,
            "ready",
            "ok",
            share_url,
            "pansou",
            rename_pairs=pairs,
            reviewed_candidates=(candidate,),
        )
        qas = FakeQas()

        result = execute_qas_plan(target, resolution, "/strm/tv/测试动画(2026)", qas=qas)

        self.assertTrue(result.ok)
        self.assertEqual(1, result.executed_pairs)
        self.assertEqual(1, qas.run_calls)
        self.assertEqual("$TV_PRO", qas.run_payloads[0]["pattern"])
        self.assertEqual("", qas.run_payloads[0]["replace"])

    def test_numbered_folder_with_extra_video_keeps_precise_runs(self):
        target = MediaTarget(123, "tv", "测试动画", series_year="2026", season_number=1)
        pairs = tuple(
            RenamePair(
                f"{number:02d}.mkv",
                rf"^{number:02d}\.mkv$",
                f"测试动画.2026.S01E{number:02d}.mkv",
                number,
                episode_numbers=(number,),
            )
            for number in range(1, 4)
        )
        share_url = "https://pan.quark.cn/s/mixed"
        candidate = ResourceCandidate(share_url, files=(*tuple(pair.source_name for pair in pairs), "SP01.mkv"))
        resolution = LinkResolution(True, "ready", "ok", share_url, "pansou", rename_pairs=pairs, reviewed_candidates=(candidate,))
        qas = FakeQas()

        result = execute_qas_plan(target, resolution, "/strm/tv/测试动画(2026)", qas=qas)

        self.assertTrue(result.ok)
        self.assertEqual(3, result.executed_pairs)
        self.assertEqual(3, qas.run_calls)

    def test_target_directory_confirms_expected_renamed_files(self):
        class DirectoryQas:
            def savepath_detail(self, path):
                return {
                    "success": True,
                    "data": {
                        "list": [
                            {"file_name": "测试剧.2026.S01E01.mkv", "dir": False, "size": 1000},
                            {"file_name": "poster.jpg", "dir": False, "size": 10},
                        ]
                    },
                }

        self.assertTrue(qas_saved_files_confirmed(DirectoryQas(), "/tv/test", ["测试剧.2026.S01E01.mkv"]))
        self.assertFalse(qas_saved_files_confirmed(DirectoryQas(), "/tv/test", ["missing.mkv"]))

    def test_executes_each_pair_and_clears_runweek(self):
        target, resolution = plan()
        qas = FakeQas()
        result = execute_qas_plan(target, resolution, "/strm/tv/测试剧", qas=qas)
        self.assertTrue(result.ok)
        self.assertEqual(2, result.executed_pairs)
        self.assertFalse(result.confirmed)
        self.assertEqual(2, qas.run_calls)
        self.assertTrue(qas.run_payloads[0]["runweek"])
        self.assertEqual([], qas.tasks[0]["runweek"])
        self.assertEqual("测试剧.2026.S01E02.mkv", qas.tasks[0]["replace"])

    def test_qas_schedule_skip_is_not_accepted_as_transfer(self):
        from app.services.qas_executor import qas_trigger_accepted

        output = {"ok": True, "raw": "任务不在运行周期内，跳过"}
        self.assertFalse(qas_trigger_accepted(output))

    def test_unknown_empty_qas_response_is_not_accepted(self):
        from app.services.qas_executor import qas_trigger_accepted

        self.assertFalse(qas_trigger_accepted({}))

    def test_no_new_task_is_not_transfer_confirmation(self):
        from app.services.qas_executor import qas_transfer_confirmed

        self.assertFalse(qas_transfer_confirmed({"ok": True, "raw": "没有新的转存任务"}))

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
        result = execute_qas_plan(target, resolution, "/strm/tv/测试剧", qas=qas)
        self.assertFalse(result.ok)
        self.assertEqual("qas_failed_rolled_back", result.stage)
        self.assertEqual([original], qas.tasks)

    def test_success_replaces_compatible_legacy_task_without_duplicate(self):
        target, resolution = plan()
        legacy = {
            "taskname": "测试剧.S1",
            "shareurl": "https://pan.quark.cn/s/old",
            "savepath": "/tv/测试剧",
            "pattern": "old-pattern",
            "replace": "old-replace",
            "runweek": [2],
            "plugin": {"smartstrm": True},
        }
        qas = FakeQas([legacy])
        result = execute_qas_plan(target, resolution, "/strm/tv/测试剧", qas=qas)
        self.assertTrue(result.ok)
        self.assertEqual(1, len(qas.tasks))
        self.assertEqual("测试剧.2026.S01", qas.tasks[0]["taskname"])
        self.assertEqual("/strm/tv/测试剧", qas.tasks[0]["savepath"])
        self.assertEqual([], qas.tasks[0]["runweek"])
        self.assertEqual({"smartstrm": True}, qas.tasks[0]["plugin"])

    def test_legacy_task_is_restored_if_execution_fails(self):
        target, resolution = plan()
        legacy = {
            "taskname": "测试剧.S1",
            "shareurl": "https://pan.quark.cn/s/old",
            "savepath": "/tv/测试剧",
            "pattern": "old-pattern",
            "replace": "old-replace",
            "runweek": [2],
        }
        qas = FakeQas([legacy], fail_on_run=2)
        result = execute_qas_plan(target, resolution, "/strm/tv/测试剧", qas=qas)
        self.assertFalse(result.ok)
        self.assertEqual("qas_failed_rolled_back", result.stage)
        self.assertEqual([legacy], qas.tasks)

    def test_tracking_claim_disables_only_compatible_legacy_schedule(self):
        target, _ = plan()
        compatible = {
            "taskname": "测试剧.S1",
            "savepath": "/tv/测试剧",
            "runweek": [2, 4],
        }
        wrong_season = {
            "taskname": "测试剧.S2",
            "savepath": "/tv/测试剧",
            "runweek": [3],
        }
        wrong_year = {
            "taskname": "测试剧.2025.S1",
            "savepath": "/tv/测试剧",
            "runweek": [5],
        }
        qas = FakeQas([compatible, wrong_season, wrong_year])
        self.assertEqual(1, disable_compatible_qas_schedules(target, qas))
        self.assertEqual([], qas.tasks[0]["runweek"])
        self.assertEqual([3], qas.tasks[1]["runweek"])
        self.assertEqual([5], qas.tasks[2]["runweek"])

    def test_short_title_does_not_claim_longer_unrelated_title(self):
        target = MediaTarget(1, "tv", "三体", series_year="2023", season_number=1)
        qas = FakeQas(
            [
                {"taskname": "三体.S1", "savepath": "/tv/三体", "runweek": [2]},
                {"taskname": "三体动画.S1", "savepath": "/tv/三体动画", "runweek": [3]},
            ]
        )
        self.assertEqual(1, disable_compatible_qas_schedules(target, qas))
        self.assertEqual([], qas.tasks[0]["runweek"])
        self.assertEqual([3], qas.tasks[1]["runweek"])

    def test_non_ready_plan_never_touches_qas(self):
        target, _ = plan()
        qas = FakeQas()
        result = execute_qas_plan(target, LinkResolution(False, "needs_review", "review"), "/tv", qas=qas)
        self.assertFalse(result.ok)
        self.assertEqual(0, qas.run_calls)
        self.assertEqual([], qas.tasks)

    def test_rejects_category_only_path_before_touching_qas(self):
        target, resolution = plan()
        qas = FakeQas()
        result = execute_qas_plan(target, resolution, "/tv/音乐缘计划 (2024)", qas=qas)
        self.assertFalse(result.ok)
        self.assertEqual("invalid_save_path", result.stage)
        self.assertEqual(0, qas.run_calls)
        self.assertEqual([], qas.tasks)

    def test_explicit_qas_success_is_confirmed(self):
        class ConfirmingQas(FakeQas):
            def run_task(self, task):
                self.run_calls += 1
                return {"ok": True, "raw": "data: >>> 任务执行成功"}

            def savepath_detail(self, path):
                return {
                    "success": True,
                    "data": {"list": [
                        {"file_name": "测试剧.2026.S01E01.mkv", "dir": False, "size": 1000},
                        {"file_name": "测试剧.2026.S01E02.mkv", "dir": False, "size": 1000},
                    ]},
                }

        target, resolution = plan()
        result = execute_qas_plan(target, resolution, "/strm/tv/测试剧", qas=ConfirmingQas())
        self.assertTrue(result.ok)
        self.assertTrue(result.confirmed)
        self.assertEqual("qas_completed", result.stage)


if __name__ == "__main__":
    unittest.main()
