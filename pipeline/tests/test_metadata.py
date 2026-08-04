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


def test_generate_metadata_strips_markdown_json_fence():
    # Groq models frequently wrap JSON in ```json fences despite being told not to -
    # this is the realistic failure mode, unlike a literal "not json" string.
    fenced = '```json\n{"title": "T", "description": "D", "tags": ["java"]}\n```'
    with patch("metadata.call_groq", return_value=fenced):
        result = metadata.generate_metadata("2026-08-03", ["Java"], "script")
    assert result["title"] == "T"
    assert result["tags"] == ["java"]


def test_generate_metadata_truncates_oversized_title_and_strips_angle_brackets():
    long_title = "<script>" + ("A" * 150)
    fake_json = f'{{"title": "{long_title}", "description": "D", "tags": []}}'
    with patch("metadata.call_groq", return_value=fake_json):
        result = metadata.generate_metadata("2026-08-03", ["Java"], "script")
    assert len(result["title"]) <= metadata.MAX_TITLE_LEN
    assert "<" not in result["title"]
    assert ">" not in result["title"]


def test_generate_metadata_defaults_missing_title_and_filters_bad_tags():
    fake_json = '{"description": "D", "tags": ["java", 42, null, "kubernetes"]}'
    with patch("metadata.call_groq", return_value=fake_json):
        result = metadata.generate_metadata("2026-08-04", ["Java"], "script")
    assert "2026-08-04" in result["title"]
    assert result["tags"] == ["java", "kubernetes"]


def test_generate_metadata_caps_total_tags_length_under_500_chars():
    long_tags = [f"tag-{i}-" + "x" * 40 for i in range(20)]
    fake_json = '{"title": "T", "description": "D", "tags": ' + str(long_tags).replace("'", '"') + "}"
    with patch("metadata.call_groq", return_value=fake_json):
        result = metadata.generate_metadata("2026-08-03", ["Java"], "script")
    assert sum(len(t) + 1 for t in result["tags"]) <= metadata.MAX_TAGS_CHARS
