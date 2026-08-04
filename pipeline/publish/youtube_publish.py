"""
Uploads today's video + thumbnail to YouTube and adds it to the configured
playlist. Independent, additive pipeline stage: failures here must never
block the app's audio delivery (already completed by publish/publish.py
before this stage runs - see design spec Section 9).

One-time setup: see pipeline/auth/youtube_oauth_setup.py and the README's
YouTube setup section for how to obtain YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN
and YOUTUBE_PLAYLIST_ID.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402
from video.metadata import generate_metadata  # noqa: E402
from video.thumbnail import generate_thumbnail  # noqa: E402

log = get_logger("youtube_publish")

SCOPES = ["https://www.googleapis.com/auth/youtube"]
CATEGORY_SCIENCE_AND_TECHNOLOGY = "28"


class YouTubeAuthError(Exception):
    """Raised when the stored OAuth refresh token is missing/expired/revoked."""


def youtube_configured() -> bool:
    return all(
        os.environ.get(var)
        for var in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_PLAYLIST_ID")
    )


def build_youtube_client():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise YouTubeAuthError(
            f"Failed to refresh the YouTube OAuth token - it may have expired (7-day limit "
            f"on unverified apps) or been revoked. Re-run pipeline/auth/youtube_oauth_setup.py "
            f"and update the YOUTUBE_REFRESH_TOKEN secret. Original error: {e}"
        ) from e

    return build("youtube", "v3", credentials=creds)


def _episode_date_marker(date: str) -> str:
    # A marker the code controls directly, rather than relying on the LLM-generated
    # title/description to happen to contain the ISO date - confirmed via a live
    # workflow run that they don't (e.g. "Aug 4: Java, Kafka, Docker" contains no
    # trace of "2026-08-04"), which silently defeated the idempotency check below.
    return f"[Episode date: {date}]"


def video_already_uploaded(youtube, playlist_id: str, date: str) -> bool:
    marker = _episode_date_marker(date)
    page_token = None
    while True:
        response = youtube.playlistItems().list(
            part="snippet", playlistId=playlist_id, maxResults=50, pageToken=page_token
        ).execute(num_retries=3)
        if any(marker in item["snippet"].get("description", "") for item in response.get("items", [])):
            return True
        page_token = response.get("nextPageToken")
        if not page_token:
            return False


def upload_video(youtube, video_path: Path, metadata: dict, date: str) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": f"{metadata['description']}\n\n{_episode_date_marker(date)}",
            "tags": metadata["tags"],
            "categoryId": CATEGORY_SCIENCE_AND_TECHNOLOGY,
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=5)
    return response["id"]


def set_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    youtube.thumbnails().set(
        videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))
    ).execute(num_retries=3)


def add_to_playlist(youtube, playlist_id: str, video_id: str) -> None:
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute(num_retries=3)


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()

    if not youtube_configured():
        log.warning(
            "YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN/PLAYLIST_ID not fully set - skipping YouTube publish."
        )
        return

    video_path = data_dir / f"video_{date}.mp4"
    transcript_path = data_dir / f"transcript_{date}.json"
    if not video_path.exists() or not transcript_path.exists():
        raise SystemExit(f"Missing video/transcript for {date} — run video/build_video.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]
    playlist_id = os.environ["YOUTUBE_PLAYLIST_ID"]

    try:
        youtube = build_youtube_client()
    except YouTubeAuthError as e:
        # This is caught and handled *inside* this stage's own main(), so it never
        # raises back out to run_pipeline.run_stage() - without this annotation, a
        # GitHub Actions run with an expired/revoked token would report the whole
        # job as green with the only trace being a log line nobody is watching.
        log.error("YOUTUBE AUTH FAILURE (action needed): %s", e)
        print(f"::error::YouTube auth failure (action needed): {e}")
        return

    if video_already_uploaded(youtube, playlist_id, date):
        log.info("A video for %s is already in the playlist - skipping (idempotent re-run).", date)
        return

    thumbnail_path = data_dir / f"thumbnail_{date}.png"
    generate_thumbnail(date, topics, thumbnail_path)

    result = generate_metadata(date, topics, transcript["script"])
    (data_dir / f"youtube_metadata_{date}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    log.info("Uploading %s to YouTube...", video_path.name)
    video_id = upload_video(youtube, video_path, result, date)
    log.info("Uploaded video id %s, adding to playlist %s...", video_id, playlist_id)
    # Add to the playlist immediately after the video exists - this is what makes the
    # video discoverable by video_already_uploaded()'s marker check. Setting the
    # thumbnail is comparatively low-stakes, so it runs after and is isolated: if it
    # fails, the video is still correctly published and idempotency still holds,
    # rather than a thumbnail hiccup leaving a live, playlist-less video that the
    # next run can't detect and re-uploads.
    add_to_playlist(youtube, playlist_id, video_id)

    try:
        set_thumbnail(youtube, video_id, thumbnail_path)
    except Exception:
        log.exception("Failed to set thumbnail for video %s - video is still published, continuing.", video_id)

    log.info("Published YouTube video %s: %s", video_id, result["title"])


if __name__ == "__main__":
    main()
