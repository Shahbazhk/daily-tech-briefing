"""
One-time asset generator - NOT part of the daily pipeline. Run locally once to
produce pipeline/video/assets/cover.png, then commit the resulting PNG. The
daily video-build stage (build_video.py) reuses this same static image every
day rather than regenerating it.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import argparse

WIDTH, HEIGHT = 1920, 1080
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

COVERS = {
    "tech": {
        "bg_top": (13, 16, 36),
        "bg_bottom": (26, 31, 58),
        "accent": (124, 156, 255),
        "title": "Daily Tech Briefing",
        "subtitle": "Java - Spring Boot - Kubernetes - Cloud - and more",
        "out_name": "cover.png",
    },
    "pm": {
        "bg_top": (23, 21, 15),
        "bg_bottom": (46, 40, 26),
        "accent": (212, 175, 55),
        "title": "Project Manager's Room",
        "subtitle": "Agile - Delivery - Risk - Stakeholders - Leadership",
        "out_name": "cover_pm.png",
    },
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


def build_cover(show: str = "tech") -> None:
    cfg = COVERS[show]
    bg_top, bg_bottom, accent = cfg["bg_top"], cfg["bg_bottom"], cfg["accent"]

    img = Image.new("RGB", (WIDTH, HEIGHT), bg_top)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(int(bg_top[i] + (bg_bottom[i] - bg_top[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    title_font = _load_font(96)
    subtitle_font = _load_font(40)

    title = cfg["title"]
    subtitle = cfg["subtitle"]

    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(((WIDTH - title_w) / 2, HEIGHT / 2 - 100), title, font=title_font, fill=(255, 255, 255))

    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(((WIDTH - subtitle_w) / 2, HEIGHT / 2 + 30), subtitle, font=subtitle_font, fill=accent)

    out_path = ASSETS_DIR / cfg["out_name"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", choices=list(COVERS), default="tech")
    args = parser.parse_args()
    build_cover(args.show)
