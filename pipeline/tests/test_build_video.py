import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video"))
import build_video  # noqa: E402


def test_format_srt_timestamp():
    assert build_video.format_srt_timestamp(0) == "00:00:00,000"
    assert build_video.format_srt_timestamp(1.5) == "00:00:01,500"
    assert build_video.format_srt_timestamp(65.25) == "00:01:05,250"
    assert build_video.format_srt_timestamp(3725.001) == "01:02:05,001"


def test_build_srt_formats_multiple_cues():
    cues = [
        {"text": "Hello there.", "start": 0.0, "end": 1.0},
        {"text": "Second cue.", "start": 1.0, "end": 2.5},
    ]
    srt = build_video.build_srt(cues)
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,000\nHello there.\n\n"
        "2\n00:00:01,000 --> 00:00:02,500\nSecond cue.\n"
    )
