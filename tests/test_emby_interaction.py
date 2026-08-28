import json
from unittest.mock import patch

from app.services.emby_interaction import emby_status_reply


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return json.dumps(self.payload).encode("utf-8")


def test_emby_status_reports_media_counts_and_distinct_active_users():
    responses = iter(
        [
            {"MovieCount": 12, "SeriesCount": 3, "EpisodeCount": 45},
            [
                {"Id": "s1", "UserId": "u1", "UserName": "Sunny", "NowPlayingItem": {"Id": "m1"}},
                {"Id": "s2", "UserId": "u1", "UserName": "Sunny"},
                {"Id": "s3", "UserId": "u2", "UserName": "Tom"},
                {"Id": "scheduled-task-without-user", "NowPlayingItem": {"Id": "m2"}},
            ],
        ]
    )
    settings = type("Settings", (), {"emby_base_url": "http://emby:8096", "emby_api_key": "secret"})()
    with (
        patch("app.services.emby_interaction.get_settings", return_value=settings),
        patch("app.services.emby_interaction.open_url", side_effect=lambda *_args, **_kwargs: FakeResponse(next(responses))),
    ):
        reply = emby_status_reply()

    assert "媒体条目：60" in reply
    assert "电影：12 · 剧集：3 · 单集：45" in reply
    assert "活跃用户：2（Sunny、Tom）" in reply
    assert "正在播放：1" in reply


def test_emby_status_guides_unconfigured_installations():
    settings = type("Settings", (), {"emby_base_url": "", "emby_api_key": ""})()
    with patch("app.services.emby_interaction.get_settings", return_value=settings):
        assert "尚未配置 Emby" in emby_status_reply()
