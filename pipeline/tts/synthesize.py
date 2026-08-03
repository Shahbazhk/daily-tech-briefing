"""
Renders pipeline/data/script_<date>.md to an MP3 episode using Kokoro
(https://huggingface.co/hexgrad/Kokoro-82M) — an open-weight (Apache-2.0),
self-hosted neural TTS model that sounds substantially more natural than
Piper. Runs entirely inside the GitHub Actions job (or locally); makes no
external network calls beyond the one-time model download baked into the
`kokoro` package's first run (cached by pip/HF as part of the install step).

Requires (installed by the CI workflow, see .github/workflows/daily-episode.yml):
  - the `kokoro` and `soundfile` Python packages, plus a CPU build of `torch`
  - the `espeak-ng` system package (used by Kokoro's phonemizer as an
    out-of-vocabulary word fallback)
  - ffmpeg on PATH (preinstalled on GitHub-hosted ubuntu runners), used to
    convert Kokoro's WAV output to a much smaller MP3 for app delivery.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("tts")

SAMPLE_RATE = 24_000
# lang_code "a" = American English. Voice "af_heart" is Kokoro's flagship
# American-English voice - consistently rated as its most natural-sounding.
# Full voice list: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
DEFAULT_LANG_CODE = "a"
DEFAULT_VOICE = "af_heart"


def build_caption_cues(chunks: list[tuple[str, np.ndarray]], sample_rate: int) -> list[dict]:
    cues = []
    cursor = 0.0
    for text, audio in chunks:
        duration = len(audio) / sample_rate
        cues.append({"text": text.strip(), "start": round(cursor, 3), "end": round(cursor + duration, 3)})
        cursor += duration
    return cues


def run_kokoro(text: str, lang_code: str, voice: str, wav_out: Path, captions_out: Path) -> None:
    from kokoro import KPipeline

    log.info("Running Kokoro (lang_code=%s, voice=%s)", lang_code, voice)
    pipeline = KPipeline(lang_code=lang_code)
    chunks = [(graphemes, audio) for graphemes, _, audio in pipeline(text, voice=voice)]
    if not chunks:
        raise RuntimeError("Kokoro produced no audio for this script")

    cues = build_caption_cues(chunks, SAMPLE_RATE)
    captions_out.write_text(json.dumps(cues, indent=2), encoding="utf-8")

    audio = np.concatenate([np.asarray(chunk) for _, chunk in chunks])
    sf.write(str(wav_out), audio, SAMPLE_RATE)


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
    lang_code = os.environ.get("KOKORO_LANG_CODE", DEFAULT_LANG_CODE)
    voice = os.environ.get("KOKORO_VOICE", DEFAULT_VOICE)

    wav_path = data_dir / f"episode_{date}.wav"
    mp3_path = data_dir / f"episode_{date}.mp3"
    captions_path = data_dir / f"captions_{date}.json"

    run_kokoro(text, lang_code, voice, wav_path, captions_path)
    convert_to_mp3(wav_path, mp3_path)
    wav_path.unlink(missing_ok=True)

    log.info("Wrote %s (%.1f MB)", mp3_path, mp3_path.stat().st_size / 1_000_000)
    log.info("Wrote %s", captions_path)


if __name__ == "__main__":
    main()
