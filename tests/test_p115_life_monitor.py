from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.p115_life_monitor import poll_p115_life_events, reset_life_monitor_state


def _settings():
    return SimpleNamespace(
        p115_strm_life_monitor_enabled=True,
        p115_strm_life_monitor_path="/媒体库/外部整理",
        p115_strm_enabled=True,
        strm_output_root="/strm",
        strm_playback_base_url="http://media-index:8097",
    )


def test_life_monitor_baselines_then_scans_only_watched_subdirectory_on_change():
    reset_life_monitor_state()
    client = Mock()
    client.recent_life_operations.side_effect = [
        {"state": True, "data": [{"id": "event-1"}]},
        {"state": True, "data": [{"id": "event-2"}]},
    ]
    with (
        patch("app.services.p115_life_monitor.get_settings", return_value=_settings()),
        patch("app.services.p115_life_monitor.create_strm_job", return_value=81) as create,
        patch("app.services.p115_life_monitor.run_strm_job") as run,
        patch("app.services.p115_life_monitor.add_notification"),
    ):
        assert poll_p115_life_events(client=client)["reason"] == "baseline"
        result = poll_p115_life_events(client=client)

    assert result == {"triggered": True, "job_id": 81, "path": "/媒体库/外部整理"}
    create.assert_called_once_with(provider="p115", mode="incremental", root_path="/媒体库/外部整理", output_root="/strm", playback_base_url="http://media-index:8097")
    run.assert_called_once()


def test_life_monitor_does_not_scan_when_feed_is_unchanged():
    reset_life_monitor_state()
    client = Mock()
    client.recent_life_operations.return_value = {"state": True, "data": [{"id": "same"}]}
    with patch("app.services.p115_life_monitor.get_settings", return_value=_settings()), patch("app.services.p115_life_monitor.run_strm_job") as run:
        poll_p115_life_events(client=client)
        assert poll_p115_life_events(client=client)["reason"] == "unchanged"
    run.assert_not_called()
