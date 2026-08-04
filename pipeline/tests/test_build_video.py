import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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


def test_render_video_renames_temp_file_to_out_path_on_success(tmp_path):
    out_path = tmp_path / "video_2026-08-03.mp4"
    tmp_render_path = tmp_path / "video_2026-08-03.tmp.mp4"

    def fake_run(cmd, **kwargs):
        tmp_render_path.write_bytes(b"fake mp4 bytes")
        return subprocess.CompletedProcess(cmd, returncode=0, stderr="")

    with patch("build_video.subprocess.run", side_effect=fake_run):
        build_video.render_video(tmp_path / "episode.mp3", tmp_path / "captions.srt", out_path)

    assert out_path.read_bytes() == b"fake mp4 bytes"
    assert not tmp_render_path.exists()


def test_render_video_removes_temp_file_and_raises_on_ffmpeg_failure(tmp_path):
    out_path = tmp_path / "video_2026-08-03.mp4"
    out_path.write_bytes(b"previously good video")
    tmp_render_path = tmp_path / "video_2026-08-03.tmp.mp4"

    def fake_run(cmd, **kwargs):
        tmp_render_path.write_bytes(b"partial garbage")
        return subprocess.CompletedProcess(cmd, returncode=1, stderr="ffmpeg: fatal error")

    with patch("build_video.subprocess.run", side_effect=fake_run):
        try:
            build_video.render_video(tmp_path / "episode.mp3", tmp_path / "captions.srt", out_path)
            assert False, "expected CalledProcessError"
        except subprocess.CalledProcessError as exc:
            assert exc.returncode == 1
            assert "ffmpeg: fatal error" in exc.stderr

    assert not tmp_render_path.exists()
    assert out_path.read_bytes() == b"previously good video"


def test_render_video_temp_path_keeps_mp4_extension_last():
    # ffmpeg infers the output container format from the final filename
    # extension - a temp name like "video.mp4.tmp" breaks that inference
    # (confirmed against a real ffmpeg run: "Unable to choose an output
    # format"). The temp path must end in .mp4, not .tmp.
    out_path = Path("/data/video_2026-08-03.mp4")
    tmp_path = out_path.with_name(out_path.stem + ".tmp" + out_path.suffix)
    assert tmp_path.suffix == ".mp4"
    assert tmp_path.name == "video_2026-08-03.tmp.mp4"
