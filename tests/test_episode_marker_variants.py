from dataclasses import replace

import pytest

from app.domain.media import EpisodeTarget, MediaTarget, SourceFile
from app.services.episode_matcher import episode_numbers_from_name, match_episode_files, build_rename_pair
from app.services.standard_resolver import _choose_tv_files, _resolve_inspection
from app.services.share_inspector import ShareInspection
from app.domain.media import ResourceCandidate
from app.services.link_resolver import resolve_episode_source
from app.services.standard_resolver import resolve_standard_tv_source
from types import SimpleNamespace


def target(season=1):
    return MediaTarget(1, "tv", "测试剧", season_number=season,
                       episodes=tuple(EpisodeTarget(season, n) for n in range(1, 4)))


@pytest.mark.parametrize("name", [
    "第一集.mp4", "第０１集.mp4", "Ｓ０１Ｅ０１.mp4", "EP 01.mp4", "EP-01.mp4",
    "Episode 01.mp4", "1x01.mp4", "第01话.mp4", "第一話.mp4", "第一回.mp4", "第1集.ＭＰ４",
    "S01E01 - 1080p.mp4", "E01 - 1080p.mp4",
])
def test_explicit_variants_are_shared_by_preview_tracking_and_saved_scanning(name):
    media = target()
    file = SourceFile(name, path=f"测试剧/第1季/{name}")
    assert episode_numbers_from_name(name, 1) == {1}
    matches, ambiguities = match_episode_files(media, [file])
    assert not ambiguities
    assert [item.episode_numbers for item in matches] == [(1,)]
    assert "S01E01" in build_rename_pair(media, matches[0]).replacement
    assert build_rename_pair(media, matches[0]).replacement.endswith(".mp4")
    assert _choose_tv_files(media, [file], media.title, set()) == (file,)


@pytest.mark.parametrize("name", ["E01-E02.mp4", "S01E01-E02.mp4", "第1至2集.mp4", "第一集到第二集.mp4"])
def test_combined_files_keep_full_coverage_in_both_rename_paths(name):
    media = target()
    file = SourceFile(name)
    assert episode_numbers_from_name(name, 1) == {1, 2}
    matches, _ = match_episode_files(media, [file])
    assert len(matches) == 1 and matches[0].episode_numbers == (1, 2)
    assert "S01E01-E02" in build_rename_pair(media, matches[0]).replacement
    candidate = ResourceCandidate("https://pan.quark.cn/s/test", title=media.title,
                                  reasons=("title_exact_or_contained",))
    resolution = _resolve_inspection(media, ShareInspection(True, candidate.share_url, (file,)), "test", [], candidate)
    assert resolution.ok
    assert resolution.rename_pairs[0].episode_numbers == (1, 2)
    assert "S01E01-E02" in resolution.rename_pairs[0].replacement


@pytest.mark.parametrize("name", ["01.mp4", "测试剧 - 01.mp4", "测试剧 - 01 1080p.mp4"])
def test_bare_number_requires_verified_title_or_directory_context(name):
    media = target()
    file = SourceFile(name, path=f"测试剧/Season 1/{name}")
    matches, _ = match_episode_files(media, [file])
    assert [m.episode_numbers for m in matches] == [(1,)]
    assert matches[0].confidence == "high"
    assert _choose_tv_files(media, [file], "", set()) == (file,)
    if name == "01.mp4":
        assert match_episode_files(media, [SourceFile(name)])[0] == []
        assert _choose_tv_files(media, [SourceFile(name)], "其他剧", set()) == ()


@pytest.mark.parametrize("name", [
    "测试剧 1080P.mp4", "测试剧 2026.mp4", "测试剧 20261010.mp4", "测试剧 全12集.mp4",
    "S02E01.mp4", "1x01 第2集.mp4", "S01E01 第二集.mp4", "第一集第二集.mp4",
    "第十十集.mp4", "E01-E12.mp4", "SP E01.mp4", "特别篇 第1集.mp4", "OVA E01.mp4",
])
def test_non_episode_conflicting_and_bonus_names_never_auto_transfer(name):
    media = target()
    file = SourceFile(name, path=f"测试剧/{name}")
    assert match_episode_files(media, [file])[0] == []
    assert _choose_tv_files(media, [file], media.title, set(), trust_search_identity=True) == ()


@pytest.mark.parametrize("name", ["E01.mp4", "第1至2集.mp4", "01.mp4"])
def test_parent_directory_season_conflicts_block_all_marker_styles(name):
    file = SourceFile(name, path=f"测试剧/Season 2/{name}")
    assert match_episode_files(target(), [file])[0] == []
    assert _choose_tv_files(target(), [file], "测试剧", set()) == ()


def test_named_parts_match_tmdb_titles_instead_of_guessing_episode_order():
    media = replace(target(), episodes=(EpisodeTarget(1, 2, title="故事（上篇）"),
                                        EpisodeTarget(1, 3, title="故事（下篇）")))
    files = [SourceFile("上集.mp4", path="测试剧/上集.mp4"), SourceFile("下篇.mp4", path="测试剧/下篇.mp4")]
    matches, _ = match_episode_files(media, files)
    assert [m.episode_numbers for m in matches] == [(2,), (3,)]
    assert all(m.confidence == "high" for m in matches)
    assert len(_choose_tv_files(media, files, media.title, set())) == 2
    assert match_episode_files(target(), files)[0] == []
    candidate = ResourceCandidate("https://pan.quark.cn/s/parts", title=media.title, reasons=("title_exact_or_contained",))
    unresolved = _resolve_inspection(target(), ShareInspection(True, candidate.share_url, tuple(files)), "test", [], candidate)
    assert not unresolved.ok and unresolved.stage == "needs_review"


def test_bare_numbers_in_later_seasons_require_season_context():
    media = target(2)
    assert match_episode_files(media, [SourceFile("01.mp4", path="测试剧/01.mp4")])[0] == []
    file = SourceFile("01.mp4", path="测试剧/Season 2/01.mp4")
    assert [m.episode_numbers for m in match_episode_files(media, [file])[0]] == [(1,)]
    assert _choose_tv_files(media, [file], media.title, set()) == (file,)


def test_special_is_only_allowed_when_tmdb_explicitly_targets_special_season():
    media = target(0)
    file = SourceFile("测试剧.S00E01.Special.mp4")
    assert [m.episode_numbers for m in match_episode_files(media, [file])[0]] == [(1,)]
    assert episode_numbers_from_name(file.name, 0) == {1}
    assert episode_numbers_from_name("特别篇 E01.mp4", 1) == set()
    assert episode_numbers_from_name("第一集幕后.mp4", 1) == set()


@pytest.mark.parametrize("name", ["1080.mp4", "720.mp4", "2026.mp4", "2026-10-10.mp4"])
def test_quality_and_date_numbers_do_not_match_even_if_tmdb_has_that_episode(name):
    number = int(name.split(".")[0].split("-")[0])
    media = replace(target(), episodes=(EpisodeTarget(1, number),))
    assert match_episode_files(media, [SourceFile(name, path=f"测试剧/{name}")])[0] == []


@pytest.mark.parametrize("resolver", [resolve_episode_source, resolve_standard_tv_source])
@pytest.mark.parametrize("season", [1, 2])
def test_verified_search_identity_supplies_context_and_preserves_source_paths(resolver, season):
    media = target(season)
    files = tuple(SourceFile(f"{n:02d}.mp4", path=f"opaque/{n:02d}.mp4", provider_file_id=str(n)) for n in range(1, 4))

    class Provider:
        key = "quark"
        def inspect_share(self, url):
            return ShareInspection(True, url, files)

    class Search:
        def search_detailed(self, *args, **kwargs):
            return SimpleNamespace(items=[{"title": f"测试剧 第{season}季", "share_url": "https://pan.quark.cn/s/numbers"}], error="")

    result = resolver(media, qas=Provider(), pansou=Search(), provider_filter="quark")
    assert result.ok and result.stage == "ready"
    assert [pair.episode_numbers for pair in result.rename_pairs] == [(1,), (2,), (3,)]
    assert [pair.source_path for pair in result.rename_pairs] == [file.path for file in files]
    assert [pair.source_id for pair in result.rename_pairs] == [file.provider_file_id for file in files]


def test_unmapped_parts_are_reviewed_by_tracking_without_creating_rename_pairs():
    media = target()

    class Provider:
        key = "quark"
        def inspect_share(self, url):
            return ShareInspection(True, url, (SourceFile("上篇.mp4"), SourceFile("下篇.mp4")))

    class Search:
        def search_detailed(self, *args, **kwargs):
            return SimpleNamespace(items=[{"title": media.title, "share_url": "https://pan.quark.cn/s/parts"}], error="")

    result = resolve_episode_source(media, qas=Provider(), pansou=Search(), provider_filter="quark")
    assert not result.ok and result.stage == "needs_review"
    assert not result.rename_pairs
