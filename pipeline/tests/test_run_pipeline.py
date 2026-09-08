import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_pipeline  # noqa: E402


@pytest.fixture(autouse=True)
def cleanup_pipeline_show():
    """Ensure PIPELINE_SHOW is cleaned up after each test."""
    yield
    if "PIPELINE_SHOW" in os.environ:
        del os.environ["PIPELINE_SHOW"]


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


def test_main_with_show_pm_sets_env_and_dispatches_pm_script_stage(monkeypatch):
    calls = []

    def fake_run_stage(name, path, required=True):
        calls.append((name, path))
        return True

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--show", "pm", "--skip-publish"])
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)

    run_pipeline.main()

    assert os.environ["PIPELINE_SHOW"] == "pm"
    script_call = next(c for c in calls if c[0] == "generate_script")
    assert script_call[1].endswith("generate_script_pm.py")


def test_main_with_default_show_dispatches_tech_script_stage(monkeypatch):
    calls = []

    def fake_run_stage(name, path, required=True):
        calls.append((name, path))
        return True

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--skip-publish"])
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)

    run_pipeline.main()

    assert os.environ["PIPELINE_SHOW"] == "tech"
    script_call = next(c for c in calls if c[0] == "generate_script")
    assert script_call[1].endswith("generate_script.py") and not script_call[1].endswith("_pm.py")
