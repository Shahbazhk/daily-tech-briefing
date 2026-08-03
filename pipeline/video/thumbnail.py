"""
Generates pipeline/data/thumbnail_<date>.png - a templated (not AI-generated)
YouTube thumbnail, colored by that day's dominant topic. Deterministic,
instant, zero external calls - appropriate for a fully unattended daily job
(see design spec Section 6 for why templated over AI-generated).
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("thumbnail")

WIDTH, HEIGHT = 1280, 720
DEFAULT_ACCENT = (124, 156, 255)

# Matches the topic labels in pipeline/config/sources.yaml plus the Architect's Corner.
TOPIC_ACCENT_COLORS = {
    "Java": (247, 152, 29),
    "Spring Boot": (109, 179, 63),
    "Liferay DXP": (0, 107, 143),
    "Hibernate": (191, 55, 50),
    "Apache Kafka": (35, 35, 35),
    "Redis": (220, 56, 45),
    "Docker": (13, 136, 214),
    "Microservices": (108, 92, 231),
    "Kubernetes": (50, 108, 229),
    "Jenkins": (240, 86, 34),
    "Git": (240, 80, 51),
    "Angular": (200, 30, 45),
    "Cloud (AWS / Azure / GCP)": (0, 153, 204),
    "The Architect's Corner": (255, 159, 67),
}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def topic_accent_color(topic_label: str) -> tuple[int, int, int]:
    return TOPIC_ACCENT_COLORS.get(topic_label, DEFAULT_ACCENT)


def generate_thumbnail(date: str, topics: list[str], out_path: Path) -> None:
    accent = topic_accent_color(topics[0]) if topics else DEFAULT_ACCENT
    bg = tuple(max(0, c - 180) for c in accent)

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, HEIGHT - 220), (WIDTH, HEIGHT)], fill=accent)

    date_font = _load_font(48)
    topics_font = _load_font(64)

    draw.text((60, 50), date, font=date_font, fill=(255, 255, 255))

    topics_text = " - ".join(topics[:3]) if topics else "Daily Tech Briefing"
    draw.text((60, HEIGHT - 180), topics_text, font=topics_font, fill=(20, 20, 20))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    transcript_path = data_dir / f"transcript_{date}.json"
    if not transcript_path.exists():
        raise SystemExit(f"Missing {transcript_path} — run scripting/generate_script.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]

    out_path = data_dir / f"thumbnail_{date}.png"
    generate_thumbnail(date, topics, out_path)
    log.info("Wrote %s", out_path)


if __name__ == "__main__":
    main()
