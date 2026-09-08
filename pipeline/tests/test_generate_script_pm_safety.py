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
