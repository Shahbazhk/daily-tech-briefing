"""
Renders pipeline/data/video_<date>.mp4: the static cover-art image
(pipeline/video/assets/cover.png) with the episode's actual narration
captioned on top in sync with the audio, using the timing cues
tts/synthesize.py already records for free from Kokoro's own synthesis
chunks (pipeline/data/captions_<date>.json) - no forced-alignment/ASR tool
needed. Uses ffmpeg's `subtitles` filter (burned-in captions via a generated
SRT file), which needs ffmpeg built with libass - already true of the
GitHub-hosted ubuntu runner's packaged ffmpeg.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("build_video")

COVER_IMAGE = Path(__file__).resolve().parent / "assets" / "cover.png"


def format_srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(cues: list[dict]) -> str:
    lines = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{format_srt_timestamp(cue['start'])} --> {format_srt_timestamp(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    return "\n".join(lines)


def render_video(mp3_path: Path, srt_path: Path, out_path: Path) -> None:
    # ffmpeg's subtitles filter argument needs colons escaped (it uses ':' as its
    # own option separator) - this always runs on the Linux GitHub Actions runner.
    srt_arg = str(srt_path).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(COVER_IMAGE),
        "-i", str(mp3_path),
        "-vf",
        f"subtitles='{srt_arg}':force_style="
        f"'FontSize=28,PrimaryColour=&H00FFFFFF,BorderStyle=3,BackColour=&H80000000,"
        f"Alignment=2,MarginV=60'",
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    log.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    mp3_path = data_dir / f"episode_{date}.mp3"
    captions_path = data_dir / f"captions_{date}.json"
    if not mp3_path.exists() or not captions_path.exists():
        raise SystemExit(f"Missing episode audio/captions for {date} — run tts/synthesize.py first.")
    if not COVER_IMAGE.exists():
        raise SystemExit(f"Missing {COVER_IMAGE} — run video/make_cover.py once and commit the result.")

    cues = json.loads(captions_path.read_text(encoding="utf-8"))
    srt_path = data_dir / f"captions_{date}.srt"
    srt_path.write_text(build_srt(cues), encoding="utf-8")

    video_path = data_dir / f"video_{date}.mp4"
    render_video(mp3_path, srt_path, video_path)
    log.info("Wrote %s (%.1f MB)", video_path, video_path.stat().st_size / 1_000_000)


if __name__ == "__main__":
    main()
