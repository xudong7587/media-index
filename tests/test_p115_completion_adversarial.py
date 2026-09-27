from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.domain.media import EpisodeTarget, LinkResolution, MediaTarget, ProviderExecutionResult, RenamePair, SourceFile
from app.services.p115_completion import _remaining_after_native, _resolve_confirmed_tv_p115_source, complete_quark_to_p115
from app.services.share_inspector import ShareInspection


def test_planned_episode_without_receipt_remains_missing():
    pairs = tuple(RenamePair(f"{n}.mkv", "", f"Show.S01E0{n}.mkv", episode_number=n, episode_numbers=(n,)) for n in (1, 2))
    remaining = _remaining_after_native(
        ("Show.S01E01.mp4", "Show.S01E02.mp4"), pairs,
        ({"file_id": "one", "file_name": "Show.S01E01.mkv"},), 1, "tv",
    )
    assert remaining == ("Show.S01E02.mp4",)


def test_receipt_for_another_season_cannot_confirm_planned_episode():
    pair = RenamePair("1.mkv", "", "Show.S01E01.mkv", episode_number=1)
    assert _remaining_after_native(("Show.S01E01.mp4",), (pair,),
                                   ({"file_id": "wrong", "file_name": "Show.S02E01.mkv"},), 1, "tv") == ("Show.S01E01.mp4",)


@pytest.fixture
def completion():
    provider = Mock()
    provider.configured.return_value = True
    provider.reconcile.return_value = False
    settings = SimpleNamespace(openlist_enabled=True, openlist_auto_sync=True, openlist_auto_sync_direction="qas_to_p115",
                               provider_save_root=lambda provider: "/quark" if provider == "quark" else "/115")
    target = MediaTarget(1, "tv", "Show", season_number=1, episodes=(EpisodeTarget(1, 1), EpisodeTarget(1, 2)))
    with (patch("app.services.p115_completion.get_settings", return_value=settings),
          patch("app.services.p115_completion.get_transfer_provider", return_value=provider),
          patch("app.services.p115_completion._native_search_target", return_value=target),
          patch("app.services.p115_completion.resolve_episode_source", return_value=LinkResolution(False, "no_resource", "none")) as resolve,
          patch("app.services.p115_completion.sync_transfer_outputs") as copy):
        yield provider, resolve, copy


def run_completion():
    return complete_quark_to_p115(job_id=0, save_path="/quark/tv/Show/Season 1", filenames=["Show.S01E01.mkv", "Show.S01E02.mkv"],
                                 tmdb_id=1, media_type="tv", season_number=1, title="Show")


def test_destination_read_failure_stops_native_and_copy(completion):
    provider, resolve, copy = completion
    provider.reconcile.side_effect = RuntimeError("read failed")
    result = run_completion()
    assert result.workflow_status == "failed"
    resolve.assert_not_called()
    provider.execute.assert_not_called()
    copy.assert_not_called()


@pytest.mark.parametrize("landed", [0, 1])
def test_incomplete_copy_receipt_never_reports_done(completion, landed):
    _, _, copy = completion
    copy.return_value = [{"ok": True, "job_id": 12, "landed": landed}]
    assert run_completion().workflow_status == "failed"


def test_unconfirmed_native_submission_does_not_start_second_copy(completion):
    provider, resolve, copy = completion
    resolve.return_value = LinkResolution(True, "ready", "matched", share_url="https://115.com/s/demo")
    provider.execute.return_value = ProviderExecutionResult(True, "provider_submitted", "waiting", external_job_id="task-1")
    result = run_completion()
    assert result.workflow_status != "done"
    copy.assert_not_called()


def test_native_execute_exception_does_not_start_second_copy(completion):
    provider, resolve, copy = completion
    resolve.return_value = LinkResolution(True, "ready", "matched", share_url="https://115.com/s/demo")
    provider.execute.side_effect = TimeoutError("response lost after submission")
    assert run_completion().workflow_status == "review"
    copy.assert_not_called()


def test_provider_label_cannot_override_quark_url():
    provider = Mock()
    provider.inspect_share.return_value = ShareInspection(True, "https://pan.quark.cn/s/wrong", (SourceFile("Show.S01E01.mkv", 100, "/Show.S01E01.mkv", "one", "0"),))
    pansou = Mock()
    pansou.search_detailed.return_value = SimpleNamespace(items=[{"title": "Show", "share_url": "https://pan.quark.cn/s/wrong", "provider": "p115"}], error="")
    target = MediaTarget(1, "tv", "Show", season_number=1, episodes=(EpisodeTarget(1, 1),))
    with (patch("app.services.p115_completion.PansouClient", return_value=pansou),
          patch("app.services.p115_completion.get_settings", return_value=SimpleNamespace(pansou_search_timeout_seconds=45))):
        assert not _resolve_confirmed_tv_p115_source(target, provider).ok
    provider.inspect_share.assert_not_called()


def test_bad_candidate_does_not_hide_later_verified_share():
    provider = Mock()
    provider.inspect_share.side_effect = [TimeoutError("share unavailable"), ShareInspection(
        True, "https://115.com/s/good", (SourceFile("Release.S01E01.mkv", 100, "/Release.S01E01.mkv", "one", "0"),))]
    pansou = Mock()
    pansou.search_detailed.return_value = SimpleNamespace(items=[
        {"title": "Show S01", "share_url": "https://115.com/s/bad"},
        {"title": "Show S01", "share_url": "https://115.com/s/good"},
    ], error="")
    target = MediaTarget(1, "tv", "Show", season_number=1, episodes=(EpisodeTarget(1, 1),))
    with (patch("app.services.p115_completion.PansouClient", return_value=pansou),
          patch("app.services.p115_completion.get_settings", return_value=SimpleNamespace(pansou_search_timeout_seconds=45))):
        result = _resolve_confirmed_tv_p115_source(target, provider)
    assert result.ok
    assert result.share_url == "https://115.com/s/good"
    assert result.rename_pairs[0].replacement == "Show.S01E01.mkv"
    assert provider.inspect_share.call_count == 2


def test_native_post_processing_failure_is_not_completion(completion):
    provider, resolve, copy = completion
    resolve.return_value = LinkResolution(True, "ready", "matched", share_url="https://115.com/s/demo")
    provider.execute.return_value = ProviderExecutionResult(True, "provider_completed", "done", confirmed=True,
        outputs=({"file_id": "one", "file_name": "Show.S01E01.mkv"}, {"file_id": "two", "file_name": "Show.S01E02.mkv"}))
    with patch("app.services.p115_completion.run_confirmed_native_transfer_post_processing", return_value=False):
        result = complete_quark_to_p115(job_id=8, save_path="/quark/tv/Show/Season 1", filenames=["Show.S01E01.mkv", "Show.S01E02.mkv"], tmdb_id=1, media_type="tv", season_number=1, title="Show")
    assert result.native_completed
    assert result.workflow_status == "failed"
    copy.assert_not_called()


def test_single_movie_receipt_does_not_cover_multiple_movie_parts():
    assert _remaining_after_native(("Movie.CD1.mkv", "Movie.CD2.mkv"), (),
        ({"file_id": "one", "file_name": "Movie.CD1.mkv"},), None, "movie") == ("Movie.CD2.mkv",)


@pytest.mark.parametrize("filename", ["Show.S01E01.srt", "Show.S01E01-E02.mp4"])
def test_episode_receipt_does_not_cover_subtitle_or_combined_file(filename):
    pair = RenamePair("1.mkv", "", "Show.S01E01.mkv", episode_number=1)
    assert _remaining_after_native((filename,), (pair,),
        ({"file_id": "one", "file_name": "Show.S01E01.mkv"},), 1, "tv") == (filename,)
