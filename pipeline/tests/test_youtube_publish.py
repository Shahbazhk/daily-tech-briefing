import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "publish"))
import youtube_publish  # noqa: E402


def test_youtube_configured_true_when_all_vars_set(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "a")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "b")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "c")
    monkeypatch.setenv("YOUTUBE_PLAYLIST_ID", "d")
    assert youtube_publish.youtube_configured() is True


def test_youtube_configured_false_when_one_missing(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "a")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "b")
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("YOUTUBE_PLAYLIST_ID", "d")
    assert youtube_publish.youtube_configured() is False


def test_video_already_uploaded_true_when_date_in_a_title():
    fake_youtube = MagicMock()
    fake_youtube.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [
            {"snippet": {"title": "Daily Tech Briefing - Aug 2, 2026"}},
            {"snippet": {"title": "Daily Tech Briefing - 2026-08-03"}},
        ]
    }
    assert youtube_publish.video_already_uploaded(fake_youtube, "PL123", "2026-08-03") is True


def test_video_already_uploaded_false_when_no_match():
    fake_youtube = MagicMock()
    fake_youtube.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [{"snippet": {"title": "Daily Tech Briefing - 2026-08-02"}}]
    }
    assert youtube_publish.video_already_uploaded(fake_youtube, "PL123", "2026-08-03") is False
