import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripting"))
import generate_script_pm  # noqa: E402
import common  # noqa: E402


def test_story_theme_for_date_is_deterministic_and_cycles():
    theme_a = generate_script_pm.story_theme_for_date("2026-01-01")
    theme_b = generate_script_pm.story_theme_for_date("2026-01-01")
    assert theme_a == theme_b
    assert theme_a in generate_script_pm.STORY_THEMES


def test_pick_deep_dive_selects_topic_with_most_items_and_longest_item_as_anchor():
    topics_with_items = [
        ("Agile & Scrum Delivery", [{"title": "A", "snippet": "short"}], ""),
        (
            "Risk & Stakeholder Management",
            [
                {"title": "B", "snippet": "short"},
                {"title": "C", "snippet": "a much longer and more detailed snippet here"},
            ],
            "",
        ),
    ]
    label, anchor, description = generate_script_pm.pick_deep_dive(topics_with_items)
    assert label == "Risk & Stakeholder Management"
    assert anchor["title"] == "C"


def test_generate_story_segment_retries_once_then_raises_if_still_flagged():
    calls = {"n": 0}

    def fake_call_groq(messages, max_tokens=1200):
        calls["n"] += 1
        return f"segment text {calls['n']} " + "x " * 300

    # generate_story_segment's own initial call_groq call resolves via generate_script_pm's
    # globals; the safety-retry path calls common.retry_with_safety_reminder, whose internal
    # call_groq resolves via common.py's globals - both need patching to the same fake so the
    # call count below stays accurate (see the equivalent comment in
    # test_generate_script_safety.py::test_generate_topic_segment_retries_once_then_raises_if_still_flagged).
    with patch("generate_script_pm.call_groq", side_effect=fake_call_groq), \
         patch("common.call_groq", side_effect=fake_call_groq), \
         patch("generate_script_pm.check_segment_safety", return_value=(False, "FLAGGED: unethical example")):
        try:
            generate_script_pm.generate_story_segment("scope creep", target_words=300)
            assert False, "expected ContentSafetyError"
        except generate_script_pm.ContentSafetyError as e:
            assert e.segment_label == "Story"
            assert "unethical example" in e.reason

    assert calls["n"] == 2


def test_generate_deep_dive_segment_returns_text_when_safe():
    with patch("generate_script_pm.call_groq", return_value="x " * 300), \
         patch("generate_script_pm.check_segment_safety", return_value=(True, "")):
        result = generate_script_pm.generate_deep_dive_segment(
            "Agile & Scrum Delivery", {"title": "T", "snippet": "s", "url": "http://x"}, target_words=300
        )
    assert result == "x " * 300


def test_pm_script_stage_runs_under_runpy_without_manual_syspath(monkeypatch, tmp_path):
    """Guards the real run_pipeline.py path: runpy.run_path does NOT add the script's own
    directory to sys.path (unlike `python script.py`), so a bare `from generate_script import
    ...` only works if the file inserts its own directory too. This test module's own
    top-of-file sys.path.insert for the scripting dir (line 6 above) would normally mask that
    bug, so we strip it from sys.path (and clear the relevant sys.modules cache) before
    invoking runpy, to genuinely reproduce what run_pipeline.py's run_stage() sees."""
    monkeypatch.setenv("PIPELINE_SHOW", "pm")
    monkeypatch.setattr(common, "DATA_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    pipeline_root = Path(__file__).resolve().parents[1]
    script_path = pipeline_root / "scripting" / "generate_script_pm.py"

    # Simulate exactly what run_pipeline.py's run_stage() does: NOT pre-inserting the
    # scripting directory (only the pipeline root is on sys.path, matching run_pipeline.py's
    # own line 18 sys.path.insert - not this test file's separate scripting-dir insert).
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    try:
        sys.path = [p for p in sys.path if not p.endswith("scripting")]
        for mod_name in list(sys.modules):
            if mod_name in ("generate_script_pm", "generate_script"):
                del sys.modules[mod_name]
        try:
            runpy.run_path(str(script_path), run_name="__main__")
            assert False, "expected SystemExit for missing collected_pm_*.json"
        except SystemExit as e:
            # Reaching this (not ModuleNotFoundError) proves the import worked.
            assert "collected" in str(e) or "Missing" in str(e)
    finally:
        sys.path = saved_path
        sys.modules.clear()
        sys.modules.update(saved_modules)


def test_main_on_quiet_day_uses_quiet_intro_and_still_writes_story_only_episode(monkeypatch, tmp_path):
    """No PM topics collected today (a "quiet day") - main() must skip straight to the
    QUIET_DAY_INTRO_TEMPLATE (not INTRO_TEMPLATE, which references topics that don't exist)
    while still generating and writing a real, if shorter, episode built solely from the story
    segment - per this file's module docstring, the story segment always runs regardless of
    news volume."""
    monkeypatch.setenv("PIPELINE_SHOW", "pm")
    monkeypatch.setattr(common, "DATA_DIR", tmp_path)

    date = common.episode_date()
    collected_path = tmp_path / f"collected_pm_{date}.json"
    collected_path.write_text(json.dumps({"date": date, "topics": {}}), encoding="utf-8")

    with patch("generate_script_pm.call_groq", return_value="x " * 300), \
         patch("generate_script_pm.check_segment_safety", return_value=(True, "")):
        generate_script_pm.main()

    script_path = tmp_path / f"script_pm_{date}.md"
    transcript_path = tmp_path / f"transcript_pm_{date}.json"
    assert script_path.exists()
    assert transcript_path.exists()

    script_text = script_path.read_text(encoding="utf-8")
    expected_quiet_intro = generate_script_pm.QUIET_DAY_INTRO_TEMPLATE.format(date=date)
    assert expected_quiet_intro in script_text
    # The topics-driven intro references sub-topics that don't exist on a quiet day - it must
    # not appear.
    assert "Coming up:" not in script_text
    assert generate_script_pm.STORY_TRANSITION in script_text
    assert generate_script_pm.OUTRO_TEXT in script_text

    theme = generate_script_pm.story_theme_for_date(date)
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert transcript["topics_covered"] == [{"topic": f"Story: {theme}", "sources": []}]
