import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video"))
import thumbnail  # noqa: E402


def test_topic_accent_color_known_topic():
    assert thumbnail.topic_accent_color("Java") == (247, 152, 29)


def test_topic_accent_color_unknown_topic_falls_back_to_default():
    assert thumbnail.topic_accent_color("Some New Topic") == thumbnail.DEFAULT_ACCENT


def test_generate_thumbnail_writes_correct_size_png(tmp_path):
    out_path = tmp_path / "thumb.png"
    thumbnail.generate_thumbnail("2026-08-03", ["Java", "The Architect's Corner"], out_path)

    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == (thumbnail.WIDTH, thumbnail.HEIGHT)
        assert img.mode == "RGB"


def test_generate_thumbnail_handles_empty_topics(tmp_path):
    out_path = tmp_path / "thumb.png"
    thumbnail.generate_thumbnail("2026-08-03", [], out_path)
    assert out_path.exists()
