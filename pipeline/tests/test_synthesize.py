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
