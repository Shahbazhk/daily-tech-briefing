"""
Renders pipeline/data/script_<date>.md to an MP3 episode using Piper
(https://github.com/rhasspy/piper) — a fully open-source, self-hosted neural
TTS engine. Runs entirely inside the GitHub Actions job (or locally); makes
no external network calls.

Requires (installed by the CI workflow, see .github/workflows/daily-episode.yml):
  - the `piper` binary on PATH (or PIPER_BIN pointing at it)
  - a downloaded voice model: PIPER_VOICE_MODEL (.onnx) + its .onnx.json config
  - ffmpeg on PATH (preinstalled on GitHub-hosted ubuntu runners), used to
    convert Piper's WAV output to a much smaller MP3 for app delivery.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("tts")

DEFAULT_VOICE_MODEL = str(Path(__file__).resolve().parent / "piper" / "voice.onnx")


def run_piper(text: str, voice_model: str, wav_out: Path) -> None:
    piper_bin = os.environ.get("PIPER_BIN", "piper")
    cmd = [piper_bin, "--model", voice_model, "--output_file", str(wav_out)]
    log.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, input=text.encode("utf-8"), check=True)


def convert_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame",
        "-qscale:a", "4",
        str(mp3_path),
    ]
    log.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    script_path = data_dir / f"script_{date}.md"
    if not script_path.exists():
        raise SystemExit(f"Missing {script_path} — run scripting/generate_script.py first.")

    text = script_path.read_text(encoding="utf-8")
    voice_model = os.environ.get("PIPER_VOICE_MODEL", DEFAULT_VOICE_MODEL)

    wav_path = data_dir / f"episode_{date}.wav"
    mp3_path = data_dir / f"episode_{date}.mp3"

    run_piper(text, voice_model, wav_path)
    convert_to_mp3(wav_path, mp3_path)
    wav_path.unlink(missing_ok=True)

    log.info("Wrote %s (%.1f MB)", mp3_path, mp3_path.stat().st_size / 1_000_000)


if __name__ == "__main__":
    main()
