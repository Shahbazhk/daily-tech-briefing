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


def test_video_already_uploaded_true_when_marker_in_a_description():
    # Real Groq-generated titles (e.g. "Aug 4: Java, Kafka, Docker") never contain
    # the ISO date, so the check must match against the description marker that
    # upload_video() itself controls, not the LLM-generated title text.
    fake_youtube = MagicMock()
    fake_youtube.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [
            {"snippet": {"title": "Aug 2: Java updates", "description": "Some text. [Episode date: 2026-08-02]"}},
            {"snippet": {"title": "Aug 3: Kafka updates", "description": "Some text. [Episode date: 2026-08-03]"}},
        ]
    }
    assert youtube_publish.video_already_uploaded(fake_youtube, "PL123", "2026-08-03") is True


def test_video_already_uploaded_false_when_no_match():
    fake_youtube = MagicMock()
    fake_youtube.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [{"snippet": {"title": "Aug 2: Java updates", "description": "[Episode date: 2026-08-02]"}}]
    }
    assert youtube_publish.video_already_uploaded(fake_youtube, "PL123", "2026-08-03") is False


def test_video_already_uploaded_pages_through_playlist_until_match_found():
    fake_youtube = MagicMock()
    fake_youtube.playlistItems.return_value.list.return_value.execute.side_effect = [
        {
            "items": [{"snippet": {"title": "Aug 1: updates", "description": "[Episode date: 2026-08-01]"}}],
            "nextPageToken": "abc",
        },
        {
            "items": [{"snippet": {"title": "Aug 3: updates", "description": "[Episode date: 2026-08-03]"}}],
        },
    ]
    assert youtube_publish.video_already_uploaded(fake_youtube, "PL123", "2026-08-03") is True
    assert fake_youtube.playlistItems.return_value.list.return_value.execute.call_count == 2


def test_upload_video_appends_episode_date_marker_to_description(tmp_path):
    fake_video_path = tmp_path / "video.mp4"
    fake_video_path.write_bytes(b"fake mp4 bytes")

    fake_youtube = MagicMock()
    fake_youtube.videos.return_value.insert.return_value.next_chunk.return_value = (None, {"id": "abc123"})
    metadata = {"title": "Aug 4: Java updates", "description": "Today we cover Java.", "tags": ["java"]}

    video_id = youtube_publish.upload_video(fake_youtube, fake_video_path, metadata, "2026-08-04")

    assert video_id == "abc123"
    body = fake_youtube.videos.return_value.insert.call_args.kwargs["body"]
    assert body["snippet"]["description"] == "Today we cover Java.\n\n[Episode date: 2026-08-04]"
