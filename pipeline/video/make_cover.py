"""
One-time asset generator - NOT part of the daily pipeline. Run locally once to
produce pipeline/video/assets/cover.png, then commit the resulting PNG. The
daily video-build stage (build_video.py) reuses this same static image every
day rather than regenerating it.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
BG_TOP = (13, 16, 36)
BG_BOTTOM = (26, 31, 58)
ACCENT = (124, 156, 255)
OUT_PATH = Path(__file__).resolve().parent / "assets" / "cover.png"


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


def build_cover() -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    title_font = _load_font(96)
    subtitle_font = _load_font(40)

    title = "Daily Tech Briefing"
    subtitle = "Java - Spring Boot - Kubernetes - Cloud - and more"

    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(((WIDTH - title_w) / 2, HEIGHT / 2 - 100), title, font=title_font, fill=(255, 255, 255))

    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(((WIDTH - subtitle_w) / 2, HEIGHT / 2 + 30), subtitle, font=subtitle_font, fill=ACCENT)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build_cover()
