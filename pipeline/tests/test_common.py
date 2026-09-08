import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402


def test_call_groq_uses_env_model_and_returns_stripped_content(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("GROQ_MODEL", "custom-model")

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "  hello world  \n"

    with patch("groq.Groq") as MockGroq:
        MockGroq.return_value.chat.completions.create.return_value = fake_response
        result = common.call_groq([{"role": "user", "content": "hi"}], max_tokens=50)

    assert result == "hello world"
    MockGroq.return_value.chat.completions.create.assert_called_once_with(
        model="custom-model",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        max_tokens=50,
    )


def test_call_groq_falls_back_to_default_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "ok"

    with patch("groq.Groq") as MockGroq:
        MockGroq.return_value.chat.completions.create.return_value = fake_response
        common.call_groq([{"role": "user", "content": "hi"}])

    _, kwargs = MockGroq.return_value.chat.completions.create.call_args
    assert kwargs["model"] == common.DEFAULT_GROQ_MODEL


def test_current_show_defaults_to_tech(monkeypatch):
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)
    assert common.current_show()["show_label"] == "Daily Tech Briefing"


def test_current_show_reads_pipeline_show_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHOW", "pm")
    assert common.current_show()["show_label"] == "Project Manager's Room"


def test_artifact_path_tech_is_unsuffixed(monkeypatch):
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)
    path = common.artifact_path("episode", "mp3", "2026-09-08")
    assert path == common.DATA_DIR / "episode_2026-09-08.mp3"


def test_artifact_path_pm_has_suffix(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHOW", "pm")
    path = common.artifact_path("episode", "mp3", "2026-09-08")
    assert path == common.DATA_DIR / "episode_pm_2026-09-08.mp3"
