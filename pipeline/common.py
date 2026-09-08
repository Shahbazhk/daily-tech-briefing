import logging
import os
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PIPELINE_ROOT / "data"
CONFIG_PATH = PIPELINE_ROOT / "config" / "sources.yaml"

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

_LOGGING_CONFIGURED = False


def call_groq(messages: list[dict], max_tokens: int = 1200) -> str:
    from groq import Groq

    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    # The free tier's tokens-per-minute cap means 429s are routine mid-run (a single
    # generate_script.py run makes ~15+ calls in well under a minute) - the SDK's default
    # max_retries=2 (3 attempts) has proven too shallow, exhausting itself and aborting the
    # whole episode while the account was still just seconds from having budget again. The
    # SDK already does exponential backoff honoring Groq's Retry-After, so raising this alone
    # (no custom retry loop needed) gives it enough attempts to wait out a shared-account burst.
    client = Groq(api_key=api_key, max_retries=8)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.5,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


def get_logger(name: str) -> logging.Logger:
    global _LOGGING_CONFIGURED
    if not _LOGGING_CONFIGURED:
        logging.basicConfig(
            level=os.environ.get("LOG_LEVEL", "INFO"),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        _LOGGING_CONFIGURED = True
    return logging.getLogger(name)


def episode_date() -> str:
    """UTC date stamp used to name today's episode artifacts (matches the
    GitHub Actions run date, which is what the schedule is anchored to)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


SHOWS: dict[str, dict] = {
    "tech": {
        "sources_path": CONFIG_PATH,
        "suffix": "",
        "show_label": "Daily Tech Briefing",
        "cover_image": "cover.png",
        "script_module": "scripting.generate_script",
        "firestore_collection": "episodes",
        "storage_prefix": "episodes",
        "push_topic": "daily_episode",
        "youtube_playlist_env": "YOUTUBE_PLAYLIST_ID",
        "youtube_category_id": "28",  # Science & Technology
    },
    "pm": {
        "sources_path": PIPELINE_ROOT / "config" / "sources_pm.yaml",
        "suffix": "_pm",
        "show_label": "Project Manager's Room",
        "cover_image": "cover_pm.png",
        "script_module": "scripting.generate_script_pm",
        "firestore_collection": "episodes_pm",
        "storage_prefix": "episodes_pm",
        "push_topic": "daily_pm_episode",
        "youtube_playlist_env": "YOUTUBE_PM_PLAYLIST_ID",
        "youtube_category_id": "27",  # Education
    },
}


def current_show() -> dict:
    """Resolves the active show from the PIPELINE_SHOW env var (set by
    run_pipeline.py's --show flag), defaulting to "tech" so every existing
    call site and workflow keeps working unchanged."""
    return SHOWS[os.environ.get("PIPELINE_SHOW", "tech")]


def artifact_path(kind: str, ext: str, date: str) -> Path:
    """e.g. artifact_path("episode", "mp3", "2026-09-08") ->
    data/episode_2026-09-08.mp3 for the tech show (unsuffixed - matches every
    already-published filename) or data/episode_pm_2026-09-08.mp3 for pm."""
    suffix = current_show()["suffix"]
    return DATA_DIR / f"{kind}{suffix}_{date}.{ext}"
