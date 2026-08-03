import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video"))
import metadata  # noqa: E402


def test_build_metadata_prompt_includes_date_topics_and_script():
    prompt = metadata.build_metadata_prompt("2026-08-03", ["Java", "Kubernetes"], "the script text")
    assert "2026-08-03" in prompt
    assert "Java, Kubernetes" in prompt
    assert "the script text" in prompt


def test_generate_metadata_parses_json_and_appends_disclosure():
    fake_json = '{"title": "Java 24 and more", "description": "Today we cover Java.", "tags": ["java"]}'
    with patch("metadata.call_groq", return_value=fake_json):
        result = metadata.generate_metadata("2026-08-03", ["Java"], "script text")

    assert result["title"] == "Java 24 and more"
    assert result["tags"] == ["java"]
    assert result["description"].startswith("Today we cover Java.")
    assert "AI voice (Kokoro TTS)" in result["description"]


def test_generate_metadata_retries_once_on_invalid_json_then_succeeds():
    responses = iter(["not json", '{"title": "T", "description": "D", "tags": []}'])
    with patch("metadata.call_groq", side_effect=lambda *a, **k: next(responses)):
        result = metadata.generate_metadata("2026-08-03", ["Java"], "script")
    assert result["title"] == "T"
