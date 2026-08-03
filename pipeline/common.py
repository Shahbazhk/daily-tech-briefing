import logging
import os
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PIPELINE_ROOT / "data"
CONFIG_PATH = PIPELINE_ROOT / "config" / "sources.yaml"

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

_LOGGING_CONFIGURED = False


def call_groq(messages: list[dict], max_tokens: int = 1200) -> str:
    from groq import Groq

    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    client = Groq(api_key=api_key)

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
