import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripting"))
import generate_script  # noqa: E402
import common  # noqa: E402


def test_check_segment_safety_parses_safe_verdict():
    # check_segment_safety is now defined in common.py (Task 2), so its internal call_groq
    # call resolves against common.py's own module globals, not generate_script's - patch it
    # there rather than on generate_script.call_groq.
    with patch("common.call_groq", return_value="SAFE"):
        is_safe, reason = generate_script.check_segment_safety("Java 24 shipped a new GC.")
    assert is_safe is True
    assert reason == ""


def test_check_segment_safety_parses_flagged_verdict():
    with patch("common.call_groq", return_value="FLAGGED: contains profanity"):
        is_safe, reason = generate_script.check_segment_safety("some text")
    assert is_safe is False
    assert reason == "FLAGGED: contains profanity"


def test_generate_topic_segment_retries_once_then_raises_if_still_flagged():
    calls = {"n": 0}

    def fake_call_groq(messages, max_tokens=1200):
        calls["n"] += 1
        return f"segment text {calls['n']} " + "x " * 300

    # generate_topic_segment's own initial call_groq call resolves via generate_script's
    # globals; the safety-retry path calls common.retry_with_safety_reminder, whose internal
    # call_groq resolves via common.py's globals - both need patching to the same fake so the
    # call count below stays accurate.
    with patch("generate_script.call_groq", side_effect=fake_call_groq), \
         patch("common.call_groq", side_effect=fake_call_groq), \
         patch("generate_script.check_segment_safety", return_value=(False, "FLAGGED: unethical example")):
        try:
            generate_script.generate_topic_segment("Java", [], target_words=300)
            assert False, "expected ContentSafetyError"
        except generate_script.ContentSafetyError as e:
            assert e.segment_label == "Java"
            assert "unethical example" in e.reason

    # 1 generation + 1 safety-retry generation = 2 call_groq calls (length-retry not
    # triggered since word count is fine; only the safety path retries here).
    assert calls["n"] == 2


def test_generate_topic_segment_returns_text_when_safe():
    with patch("generate_script.call_groq", return_value="x " * 300), \
         patch("generate_script.check_segment_safety", return_value=(True, "")):
        result = generate_script.generate_topic_segment("Java", [], target_words=300)
    assert result == "x " * 300


def test_allocate_word_budgets_respects_custom_target_and_bounds():
    budgets = generate_script.allocate_word_budgets(
        [("A", [{}, {}]), ("B", [{}])],
        target_words=300,
        min_words=50,
        max_words=250,
    )
    assert budgets["A"] == 200  # 2/3 of 300
    assert budgets["B"] == 100  # 1/3 of 300
