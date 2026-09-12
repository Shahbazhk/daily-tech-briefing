import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tts"))
import synthesize  # noqa: E402


def test_build_caption_cues_computes_cumulative_timestamps():
    sample_rate = 1000
    chunks = [
        ("Hello there.", np.zeros(1000)),   # 1.0s
        ("Java shipped a new release.", np.zeros(2500)),  # 2.5s
        ("That's all.", np.zeros(500)),  # 0.5s
    ]

    cues = synthesize.build_caption_cues(chunks, sample_rate)

    assert cues == [
        {"text": "Hello there.", "start": 0.0, "end": 1.0},
        {"text": "Java shipped a new release.", "start": 1.0, "end": 3.5},
        {"text": "That's all.", "start": 3.5, "end": 4.0},
    ]


def test_build_caption_cues_strips_whitespace_from_text():
    cues = synthesize.build_caption_cues([("  padded text  \n", np.zeros(1000))], 1000)
    assert cues[0]["text"] == "padded text"


def test_build_caption_cues_empty_list():
    assert synthesize.build_caption_cues([], 1000) == []


def test_normalize_audio_scales_quiet_audio_up_to_target_peak():
    # Kokoro's raw output measured ~0.40-0.43 peak (~-7 to -8 dBFS) for both af_heart and
    # am_michael - well below the target, confirming this isn't voice-specific.
    audio = np.array([0.1, -0.2, 0.15, -0.05], dtype=np.float32)

    result = synthesize.normalize_audio(audio, target_peak_db=-1.0)

    target_peak = 10 ** (-1.0 / 20)
    assert abs(float(np.max(np.abs(result))) - target_peak) < 1e-6


def test_normalize_audio_scales_loud_audio_down_to_target_peak():
    audio = np.array([0.99, -1.0, 0.5], dtype=np.float32)

    result = synthesize.normalize_audio(audio, target_peak_db=-1.0)

    target_peak = 10 ** (-1.0 / 20)
    assert abs(float(np.max(np.abs(result))) - target_peak) < 1e-6


def test_normalize_audio_preserves_relative_levels_between_samples():
    audio = np.array([0.1, -0.2, 0.05], dtype=np.float32)

    result = synthesize.normalize_audio(audio, target_peak_db=-1.0)

    # Scaling is linear, so the ratio between any two samples is unchanged.
    assert abs(result[1] / result[0] - audio[1] / audio[0]) < 1e-6


def test_normalize_audio_handles_silence_without_dividing_by_zero():
    audio = np.zeros(100, dtype=np.float32)

    result = synthesize.normalize_audio(audio)

    assert np.all(result == 0)
