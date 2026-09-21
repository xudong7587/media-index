from __future__ import annotations

import pytest

from app.core import env_file
from app.core.env_file import atomic_write_env, read_env_file


def test_atomic_write_env_round_trips_values_that_the_reader_would_otherwise_change(tmp_path):
    path = tmp_path / ".env"
    values = {
        "P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret",
        "PANSOU_EXCLUDE_KEYWORDS": "抢先版 #tag",
        "P115_Root_Spaced": "  /媒体库  ",
        "QUOTED_START": '"abc" trailing',
        "MULTILINE": "line1\nline2",
    }

    atomic_write_env(path, values)

    assert read_env_file(path) == values


def test_atomic_write_env_keeps_plain_and_json_values_readable(tmp_path):
    path = tmp_path / ".env"
    atomic_write_env(
        path,
        {
            "P115_ROOT_PATH": "/strm",
            "P115_STRM_INCLUDED_DIRECTORIES_JSON": '["/媒体库/115/电影","/媒体库/115/电视剧"]',
        },
    )

    content = path.read_text(encoding="utf-8")

    assert "P115_ROOT_PATH=/strm\n" in content
    assert 'P115_STRM_INCLUDED_DIRECTORIES_JSON=["/媒体库/115/电影","/媒体库/115/电视剧"]\n' in content


def test_atomic_write_env_keeps_a_backup_of_the_previous_file(tmp_path):
    path = tmp_path / ".env"
    atomic_write_env(path, {"P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=old"})

    atomic_write_env(path, {"P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=new"})

    backup = tmp_path / ".env.bak"
    assert read_env_file(path) == {"P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=new"}
    assert read_env_file(backup) == {"P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=old"}


def test_atomic_write_env_fails_when_the_written_file_does_not_read_back(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(env_file, "read_env_file", lambda _path: {"P115_COOKIE": ""})

    with pytest.raises(RuntimeError, match="校验失败"):
        atomic_write_env(path, {"P115_COOKIE": "UID=1_A1_1; CID=abc; SEID=secret"})


def test_read_env_file_skips_comments_and_blank_lines_and_decodes_quotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\n"
        "\n"
        "P115_COOKIE=\"  UID=1_A1_1; CID=abc; SEID=secret  \"\n"
        "P115_ROOT_PATH=/strm\n"
        "NOT_A_PAIR\n",
        encoding="utf-8",
    )

    assert read_env_file(path) == {
        "P115_COOKIE": "  UID=1_A1_1; CID=abc; SEID=secret  ",
        "P115_ROOT_PATH": "/strm",
    }
