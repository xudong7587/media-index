from unittest.mock import Mock, patch

import pytest

from app.services.cloud_download_organizer import _folder_query, _match_tmdb, _movie_source_identity_is_safe
from app.domain.media import MediaTarget, SourceFile
from app.clients.tmdb import TmdbClient


@pytest.mark.parametrize("filename,title,year", [
    ("[RU]Koloniya.2026.D.WEB-DL.1080p.ELEKTRI4KA.mkv", "Koloniya", "2026"),
    ("[网站][发布组]群体.Koloniya.2026.2160p.HDR.mkv", "群体", "2026"),
    ("[Group]The.Lord.of.the.Rings.2001.1080p.BluRay.x264.mkv", "The Lord of the Rings", "2001"),
    ("2001.A.Space.Odyssey.1968.2160p.REMUX.mkv", "2001 A Space Odyssey", "1968"),
    ("2012.2009.1080p.mkv", "2012", "2009"),
])
def test_filename_identity_discards_site_and_specs_but_preserves_numeric_titles(filename, title, year):
    assert _folder_query(filename) == (title, year)


def test_exact_original_title_and_year_avoids_candidate_detail_fanout():
    tmdb = Mock()
    tmdb.search.return_value = {"results": [
        {"tmdb_id": 42, "media_type": "movie", "title": "群体", "original_title": "Koloniya", "year": "2026"},
        {"tmdb_id": 43, "media_type": "movie", "title": "Other", "year": "2026"},
    ]}
    assert _match_tmdb(tmdb, "Koloniya", "2026", "movie", None) == (42, "movie")
    tmdb.details.assert_not_called()


def test_original_filename_identity_matches_after_release_suffix_cleanup():
    target = MediaTarget(42, "movie", "群体", original_title="Koloniya", series_year="2026")
    assert _movie_source_identity_is_safe(target, SourceFile("[RU]Koloniya.2026.D.WEB-DL.1080p.ELEKTRI4KA.mkv"))
    assert not _movie_source_identity_is_safe(target, SourceFile("Different.2026.1080p.mkv"))


def test_tmdb_filename_query_is_one_cached_phrase_request():
    client = TmdbClient()
    with patch.object(client, "_cached_get", return_value={"results": []}) as get:
        assert client.search_title("The Lord of the Rings", "movie") == {"results": []}
    assert get.call_count == 1
    assert get.call_args.args[1]["query"] == "The Lord of the Rings"


def test_confirmed_discovery_identity_renames_single_obfuscated_movie_without_search():
    from app.core.config import Settings
    from app.providers.cloud_download_organizer import RemoteEntry
    from app.services.cloud_download_organizer import _build_plan

    tmdb = Mock()
    tmdb.details.return_value = {"title": "群体", "original_title": "Koloniya", "year": "2026"}
    settings = Settings(_env_file=None, movie_naming_rule="{title}.{year}")
    with patch("app.services.movie_matcher.get_settings", return_value=settings):
        plan = _build_plan(
            settings, "p115", RemoteEntry("folder", "scope", "download", is_dir=True),
            "/staging/download", "/library/movie", "movie",
            (RemoteEntry("video", "folder", "a8b729.mkv", 5_000_000_000),), tmdb,
            media_title="群体", media_year="2026", media_tmdb_id=42,
        )
    tmdb.search.assert_not_called()
    tmdb.search_title.assert_not_called()
    tmdb.details.assert_called_once_with("movie", 42)
    assert plan.target.tmdb_id == 42
    assert plan.files[0].replacement == "群体.2026.mkv"
