import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_pipeline  # noqa: E402


def test_run_stage_required_reraises_on_failure():
    with patch("run_pipeline.runpy.run_path", side_effect=RuntimeError("boom")):
        try:
            run_pipeline.run_stage("some_stage", "fake/path.py", required=True)
            assert False, "expected RuntimeError to propagate"
        except RuntimeError:
            pass


def test_run_stage_not_required_swallows_failure_and_returns_false():
    with patch("run_pipeline.runpy.run_path", side_effect=RuntimeError("boom")):
        result = run_pipeline.run_stage("some_stage", "fake/path.py", required=False)
    assert result is False


def test_run_stage_not_required_swallows_system_exit_and_returns_false():
    with patch("run_pipeline.runpy.run_path", side_effect=SystemExit("no episode today")):
        result = run_pipeline.run_stage("some_stage", "fake/path.py", required=False)
    assert result is False


def test_run_stage_required_reraises_system_exit():
    with patch("run_pipeline.runpy.run_path", side_effect=SystemExit("missing input")):
        try:
            run_pipeline.run_stage("some_stage", "fake/path.py", required=True)
            assert False, "expected SystemExit to propagate"
        except SystemExit:
            pass


def test_run_stage_success_returns_true():
    with patch("run_pipeline.runpy.run_path", return_value=None):
        result = run_pipeline.run_stage("some_stage", "fake/path.py")
    assert result is True
