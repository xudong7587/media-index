"""Regressions from NAS searches for Digger and the Myanmar documentary."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.clients.pansou import PansouClient, _excluded_search_text
from app.domain.media import EpisodeTarget, MediaTarget, SourceFile
from app.services.candidate_ranker import score_resource_candidate
from app.services.link_resolver import resolve_episode_source
from app.services.movie_resolver import resolve_movie_source
from app.services.standard_resolver import resolve_standard_tv_source, _choose_tv_files
from app.services.share_inspector import ShareInspection


class Search:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def search_detailed(self, keyword, **kwargs):
        self.calls.append(keyword)
        return SimpleNamespace(items=self.responses.get(keyword, []), error="")


class Quark:
    key = "quark"

    def __init__(self, names):
        self.files = tuple(SourceFile(name, 5_000_000_000) for name in names)

    def inspect_share(self, url):
        return ShareInspection(True, url, self.files)


def documentary():
    return MediaTarget(337399, "tv", "缅北电诈覆灭纪实", series_year="2026",
                       season_number=1, episodes=tuple(EpisodeTarget(1, n) for n in (1, 2, 3)))


@pytest.mark.parametrize("names", [
    ("第一集《利剑出鞘》.mp4", "第二集《犁庭扫穴》].mp4", "第三集《共筑天网》.mp4"),
    ("【纪录片《缅北电诈覆灭纪实》第一集：利剑出鞘】_1080P.mp4",
     "【纪录片《缅北电诈覆灭纪实》第二集：犁庭扫穴】_1080P.mp4",
     "纪录片《缅北电诈覆灭纪实》第三集：共筑天网.mp4"),
    ("缅北电诈覆灭纪实 第1集.mp4", "缅北电诈覆灭纪实 第2集.mp4", "缅北电诈覆灭纪实 第3集.mp4"),
])
def test_documentary_real_filenames_match_known_tmdb_episodes(names):
    url = "https://pan.quark.cn/s/documentary"
    search = Search({documentary().title: [{"title": "纪录片 缅北电诈覆灭纪实 2026 全3集", "share_url": url}]})
    result = resolve_standard_tv_source(documentary(), qas=Quark(names), pansou=search, provider_filter="quark")
    assert result.ok
    assert sorted(pair.episode_number for pair in result.rename_pairs) == [1, 2, 3]
    assert all(f"S01E{pair.episode_number:02d}" in pair.replacement for pair in result.rename_pairs)


@pytest.mark.parametrize("name", ["第四集.mp4", "第十十集.mp4", "第一集第二集.mp4", "第2季第一集.mp4", "第一集幕后.mp4", "S01E01 第二集.mp4"])
def test_chinese_episode_does_not_guess_out_of_range_ambiguous_or_bonus(name):
    assert not _choose_tv_files(documentary(), [SourceFile(name, 1000)], documentary().title,
                                set(), trust_search_identity=True)


def test_generic_chinese_episode_cannot_borrow_an_unrelated_search_identity():
    url = "https://pan.quark.cn/s/other"
    search = Search({documentary().title: [{"title": "其他剧 全3集", "share_url": url}]})
    result = resolve_standard_tv_source(documentary(), qas=Quark(["第一集.mp4"]), pansou=search)
    assert not result.ok


def test_same_chinese_episode_editions_are_deduplicated():
    names = [SourceFile("第一集.720p.mp4", 1000), SourceFile("第一集.1080p.mp4", 5000)]
    selected = _choose_tv_files(documentary(), names, documentary().title, set(), trust_search_identity=True)
    assert len(selected) == 1
    assert selected[0].name == "第一集.1080p.mp4"


def test_documentary_label_is_genre_evidence_but_movie_making_of_stays_rejected():
    doc = score_resource_candidate(documentary(), {"title": "纪录片 缅北电诈覆灭纪实"})
    assert "derivative_content" not in doc.reasons
    bonus = score_resource_candidate(MediaTarget(1, "movie", "测试电影"), {"title": "测试电影 幕后纪录片"})
    assert bonus.rejected


@pytest.mark.parametrize("resolver,kind", [(resolve_movie_source, "movie"), (resolve_standard_tv_source, "tv"), (resolve_episode_source, "tv")])
@pytest.mark.parametrize("first", [
    {"title": "测试剧 S01E01 2026", "share_url": "https://115.com/s/other-provider"},
    {"title": "测试剧 S02E01 2025", "share_url": "https://pan.quark.cn/s/rejected"},
    {"title": "完全无关的资源", "share_url": "https://pan.quark.cn/s/unrelated"},
])
def test_wrong_provider_rejected_or_unrelated_hits_do_not_stop_alias_fallback(resolver, kind, first):
    target = MediaTarget(1, kind, "测试剧", aliases=("验证别名",), series_year="2026",
                         season_number=1 if kind == "tv" else None,
                         episodes=(EpisodeTarget(1, 1),) if kind == "tv" else ())
    if kind == "movie" and "rejected" in first["share_url"]:
        first = {**first, "title": "测试剧 2025"}
    url = "https://pan.quark.cn/s/alias"
    search = Search({"测试剧": [first], "验证别名": [{"title": "验证别名 2026 S01E01", "share_url": url}]})
    result = resolver(target, qas=Quark(["验证别名.2026.S01E01.mp4" if kind == "tv" else "验证别名.2026.mp4"]),
                      pansou=search, provider_filter="quark")
    assert result.ok
    assert search.calls == ["测试剧", "验证别名"]


def test_search_exclusions_ignore_link_ids_source_and_embedded_latin_words():
    blocked = ("tc", "ts", "cam", "part")
    assert not _excluded_search_text({"title": "Digger DTS 1080p", "share_url": "https://pan.quark.cn/s/TCPart",
                                      "source": "plugin:netsearch"}, blocked)
    assert not _excluded_search_text({"title": "Arctic Digger TCG Collection"}, blocked)
    assert _excluded_search_text({"title": "Digger [TC超清版]"}, blocked)
    assert _excluded_search_text({"content": "测试电影 CAM 版"}, blocked)


def test_explicit_refresh_reaches_pansou_once_then_polls_same_generation():
    client = PansouClient()
    client.settings = SimpleNamespace(pansou_url="http://refresh-regression", pansou_token="",
                                      pansou_result_poll_attempts=4, pansou_result_poll_seconds=0,
                                      pansou_exclude_keywords="")
    response = {"data": {"merged_by_type": {"quark": [{"url": "https://pan.quark.cn/s/fresh", "note": "新结果"}]}}}
    with patch.object(client, "_search_native_get", return_value=(response, "")) as request:
        result = client.search_detailed("新结果", refresh=True)
    assert result.items
    assert request.call_args_list[0].args[1] == {"kw": "新结果", "res": "all", "refresh": True}
    assert request.call_args_list[1].args[1] == {"kw": "新结果", "res": "all"}
