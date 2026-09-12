import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate_manifest  # noqa: E402


def _release(tag: str, assets: list[dict]) -> dict:
    return {"tag_name": tag, "assets": assets}


def _asset(name: str, url: str) -> dict:
    return {"name": name, "browser_download_url": url}


def _fake_response(payload: dict):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_build_manifest_filters_by_exact_show_regex():
    releases = [
        _release(
            "episode-2026-09-08",
            [_asset("episode_2026-09-08.mp3", "http://a"), _asset("transcript_2026-09-08.json", "http://t1")],
        ),
        _release(
            "episode-pm-2026-09-08",
            [_asset("episode_pm_2026-09-08.mp3", "http://b"), _asset("transcript_pm_2026-09-08.json", "http://t2")],
        ),
        _release("app-latest", [_asset("app.apk", "http://c")]),
    ]
    fake_transcript = {
        "date": "2026-09-08",
        "script": "Good morning. Here's today's briefing.\n\nJava shipped a new release.",
        "topics_covered": [{"topic": "Java", "sources": []}],
        "youtube_video_id": "vid1",
    }
    with patch("generate_manifest.requests.get", return_value=_fake_response(fake_transcript)):
        manifest = generate_manifest.build_manifest("tech", releases, token=None)

    assert len(manifest["episodes"]) == 1
    assert manifest["episodes"][0]["date"] == "2026-09-08"
    assert manifest["episodes"][0]["topics"] == ["Java"]
    assert manifest["episodes"][0]["video_id"] == "vid1"
    assert manifest["episodes"][0]["script"] == fake_transcript["script"]
    assert manifest["show_label"] == "Daily Tech Briefing"


def test_build_manifest_does_not_match_other_shows_tag():
    # Regression test for the specific bug this design deliberately avoids: a PM release
    # tag must never satisfy the tech show's filter (or vice versa).
    releases = [
        _release(
            "episode-pm-2026-09-08",
            [_asset("episode_pm_2026-09-08.mp3", "http://b"), _asset("transcript_pm_2026-09-08.json", "http://t2")],
        )
    ]

    manifest = generate_manifest.build_manifest("tech", releases, token=None)

    assert manifest["episodes"] == []


def test_build_episode_handles_missing_video_id():
    release = _release(
        "episode-2026-08-01",
        [_asset("episode_2026-08-01.mp3", "http://a"), _asset("transcript_2026-08-01.json", "http://t1")],
    )
    fake_transcript = {"date": "2026-08-01", "topics_covered": []}  # no youtube_video_id - older episode

    with patch("generate_manifest.requests.get", return_value=_fake_response(fake_transcript)):
        episode = generate_manifest.build_episode(release, token=None)

    assert episode["video_id"] is None


def test_build_episode_skips_release_missing_transcript_asset():
    release = _release("episode-2026-08-01", [_asset("episode_2026-08-01.mp3", "http://a")])

    episode = generate_manifest.build_episode(release, token=None)

    assert episode is None


def test_build_episode_skips_release_missing_audio_asset():
    release = _release("episode-2026-08-01", [_asset("transcript_2026-08-01.json", "http://t1")])

    episode = generate_manifest.build_episode(release, token=None)

    assert episode is None


def test_build_manifest_sorts_newest_first():
    releases = [
        _release(
            "episode-2026-09-01",
            [_asset("episode_2026-09-01.mp3", "http://a1"), _asset("transcript_2026-09-01.json", "http://t1")],
        ),
        _release(
            "episode-2026-09-05",
            [_asset("episode_2026-09-05.mp3", "http://a2"), _asset("transcript_2026-09-05.json", "http://t2")],
        ),
    ]
    responses = {
        "http://t1": {"date": "2026-09-01", "topics_covered": []},
        "http://t2": {"date": "2026-09-05", "topics_covered": []},
    }

    def fake_get(url, **kwargs):
        return _fake_response(responses[url])

    with patch("generate_manifest.requests.get", side_effect=fake_get):
        manifest = generate_manifest.build_manifest("tech", releases, token=None)

    assert [e["date"] for e in manifest["episodes"]] == ["2026-09-05", "2026-09-01"]


def test_find_asset_url_returns_none_when_no_match():
    release = _release("episode-2026-08-01", [_asset("other.txt", "http://x")])

    assert generate_manifest.find_asset_url(release, lambda n: n.endswith(".mp3")) is None
