"""
Publishes today's episode (audio + transcript) so the Android app can fetch
it, and sends the "your briefing is ready" push notification.

Primary path (see BRD Section 14.5): Firebase Spark (free plan) —
  - MP3 uploaded to Cloud Storage, with a permanent public download URL
    generated the same way the Firebase console/SDKs do (a firebaseStorageDownloadTokens
    metadata token), so no signed-URL expiry to worry about.
  - Episode metadata + transcript written to Firestore (collection "episodes", doc id = date).
  - FCM push sent to the "daily_episode" topic, which the app subscribes to.

Fallback: if FIREBASE_SERVICE_ACCOUNT is not set (e.g. you're avoiding Google
services per BRD Section 14.5's fallback), this script no-ops and simply
leaves the files in pipeline/data/ — the GitHub Actions workflow then
attaches them to a GitHub Release instead (see .github/workflows/daily-episode.yml).
Push notifications are not available in that fallback mode.
"""

import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("publish")


def firebase_configured() -> bool:
    return bool(os.environ.get("FIREBASE_SERVICE_ACCOUNT"))


def init_firebase():
    import firebase_admin
    from firebase_admin import credentials

    raw = os.environ["FIREBASE_SERVICE_ACCOUNT"]
    bucket_name = os.environ["FIREBASE_STORAGE_BUCKET"]

    # Accept either a path to a JSON file or the raw JSON contents (the latter
    # is how it's typically stored as a GitHub Actions secret).
    if os.path.isfile(raw):
        cred = credentials.Certificate(raw)
    else:
        cred = credentials.Certificate(json.loads(raw))

    return firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})


def upload_audio(mp3_path: Path, date: str) -> str:
    """Uploads the MP3 and returns a permanent public Firebase download URL."""
    from firebase_admin import storage

    bucket = storage.bucket()
    blob_path = f"episodes/episode_{date}.mp3"
    blob = bucket.blob(blob_path)

    token = str(uuid.uuid4())
    blob.metadata = {"firebaseStorageDownloadTokens": token}
    blob.upload_from_filename(str(mp3_path), content_type="audio/mpeg")

    return (
        f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/"
        f"{quote(blob_path, safe='')}?alt=media&token={token}"
    )


def write_episode_doc(date: str, audio_url: str, transcript: dict) -> None:
    from firebase_admin import firestore

    db = firestore.client()
    db.collection("episodes").document(date).set(
        {
            "date": date,
            "audio_url": audio_url,
            "topics_covered": [t["topic"] for t in transcript["topics_covered"]],
            "sources": transcript["topics_covered"],
            "script": transcript["script"],
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )


def send_notification(date: str, audio_url: str, topics: list[str]) -> None:
    from firebase_admin import messaging

    topics_preview = ", ".join(topics[:4]) if topics else "today's tech world"
    message = messaging.Message(
        topic="daily_episode",
        notification=messaging.Notification(
            title="Your daily tech briefing is ready",
            body=f"Covering: {topics_preview}",
        ),
        data={"date": date, "audio_url": audio_url},
    )
    messaging.send(message)


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    mp3_path = data_dir / f"episode_{date}.mp3"
    transcript_path = data_dir / f"transcript_{date}.json"

    if not mp3_path.exists() or not transcript_path.exists():
        raise SystemExit(f"Missing episode artifacts for {date} — run the earlier pipeline steps first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    if not firebase_configured():
        log.warning(
            "FIREBASE_SERVICE_ACCOUNT not set — skipping Firebase publish. "
            "Files remain in pipeline/data/ for the GitHub Release fallback step."
        )
        return

    init_firebase()
    log.info("Uploading %s to Firebase Storage...", mp3_path.name)
    audio_url = upload_audio(mp3_path, date)

    log.info("Writing Firestore episode doc...")
    write_episode_doc(date, audio_url, transcript)

    log.info("Sending push notification...")
    topics = [t["topic"] for t in transcript["topics_covered"]]
    send_notification(date, audio_url, topics)

    log.info("Published episode %s -> %s", date, audio_url)


if __name__ == "__main__":
    main()
