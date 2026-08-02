"""
Turns pipeline/data/collected_<date>.json into a single narrated podcast
script (~2,600-3,000 words / ~18-22 min spoken) using an open-weight model
served free by Groq Cloud (https://console.groq.com).

Model IDs on Groq's free tier change over time as they add/retire models —
if GROQ_MODEL 404s, check https://console.groq.com/docs/models and update
the default below or set GROQ_MODEL in the environment.

Design note: we generate ONE topic segment per Groq call, each with its own
explicit word-count budget, rather than asking for the whole ~2800-word
episode in a single prompt. First-round testing showed the single-big-prompt
approach badly undershoots (the model returned ~550, then plateaued around
~1500 words even after being told to expand) — a model asked to hit a small,
concrete per-segment target follows it far more reliably than one asked to
self-pace a long global target. Intro/outro are templated directly (no LLM
call needed — there's nothing creative there, just structure).

On a genuinely thin news day (few topics, few items), the resulting episode
will legitimately run shorter than 18-22 minutes — see the module-level note
above generate_topic_segment(). That's intentional: BRD Section 11 and the
system prompt both say not to pad with invented content just to hit a length.

Output:
  pipeline/data/script_<date>.md        - the narration script (fed to TTS)
  pipeline/data/transcript_<date>.json  - script + per-topic source links (for the app's transcript view)
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("scripting")

DEFAULT_MODEL = "llama-3.3-70b-versatile"

TOTAL_TARGET_WORDS = 2800
MIN_SEGMENT_WORDS = 300
MAX_SEGMENT_WORDS = 600
# If a segment comes back under half its budget, we retry it once with a firmer ask.
SEGMENT_RETRY_THRESHOLD = 0.5

SEGMENT_SYSTEM_PROMPT = """You are the writer for a daily technology news podcast aimed at a
working backend/DevOps engineer. You write ONE segment of the show at a time — not the whole
episode, just the material for a single topic. Another process stitches your segments together
with an intro and outro, so do NOT write any "welcome" or "that's it for today" framing — just
dive straight into the topic's news as if the listener is already mid-episode.

Rules:
- Plain, conversational, simple English. Explain jargon briefly the first time it appears.
- Depth over brevity: for each item, don't just announce it in one sentence — walk through what
  actually changed, background context a listener might not already know, why it matters in
  day-to-day engineering practice, and (when the source material supports it) which
  companies/projects use or are affected by it, and if it's a bug/incident/outage, the issue and
  how it was resolved.
- Do not invent facts, company names, or resolutions that are not supported by the provided
  items. Depth means more explanation of what's given, not invented specifics. If you run out of
  genuine substance before hitting the word target, stop rather than pad with filler/repetition.
- Continuous spoken narration only — no markdown headers, no bullet points, no segment title
  (the topic name will be introduced separately). This text is read aloud by a TTS engine.
"""

INTRO_TEMPLATE = (
    "Good morning. Here's your daily tech briefing for {date}. "
    "Today we're covering {topics}. Let's get into it."
)
OUTRO_TEXT = "And that's your briefing for today. See you tomorrow morning."


def build_segment_prompt(topic_label: str, items: list[dict], target_words: int) -> str:
    lines = [
        f"Topic for this segment: {topic_label}",
        f"Target length for this segment: about {target_words} words.",
        "",
        "Items collected in the last 24 hours for this topic:",
    ]
    for item in items:
        lines.append(f"- [{item['source']}] {item['title']} — {item['snippet']} (source: {item['url']})")
    return "\n".join(lines)


def call_groq(messages: list[dict], max_tokens: int = 1200) -> str:
    from groq import Groq

    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.5,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


def generate_topic_segment(topic_label: str, items: list[dict], target_words: int) -> str:
    messages = [
        {"role": "system", "content": SEGMENT_SYSTEM_PROMPT},
        {"role": "user", "content": build_segment_prompt(topic_label, items, target_words)},
    ]
    segment = call_groq(messages, max_tokens=min(1600, target_words * 3))

    word_count = len(segment.split())
    if word_count < target_words * SEGMENT_RETRY_THRESHOLD:
        log.warning(
            "%s segment came back at %d words (target ~%d) - retrying once with a firmer ask...",
            topic_label, word_count, target_words,
        )
        messages.append({"role": "assistant", "content": segment})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"That was only about {word_count} words. Rewrite it, going deeper on background "
                    f"context and real-world implications for each item, aiming for closer to "
                    f"{target_words} words. If there's genuinely not enough substance in the source "
                    f"items to responsibly reach that, get as close as you honestly can."
                ),
            }
        )
        segment = call_groq(messages, max_tokens=min(1600, target_words * 3))

    return segment


def allocate_word_budgets(topics_with_items: list[tuple[str, list[dict]]]) -> dict[str, int]:
    """Splits TOTAL_TARGET_WORDS across topics proportionally to how many items
    each one has, so a topic with more news gets more airtime, within a
    [MIN_SEGMENT_WORDS, MAX_SEGMENT_WORDS] band per topic."""
    total_items = sum(len(items) for _, items in topics_with_items) or 1
    budgets = {}
    for label, items in topics_with_items:
        share = len(items) / total_items
        budget = round(TOTAL_TARGET_WORDS * share)
        budgets[label] = max(MIN_SEGMENT_WORDS, min(MAX_SEGMENT_WORDS, budget))
    return budgets


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    collected_path = data_dir / f"collected_{date}.json"
    if not collected_path.exists():
        raise SystemExit(f"Missing {collected_path} — run collector/collect.py first.")

    with open(collected_path, "r", encoding="utf-8") as f:
        collected = json.load(f)

    topics_with_items = [
        (t["label"], t["items"]) for t in collected["topics"].values() if t["items"]
    ]

    if not topics_with_items:
        script_text = (
            f"Good morning. This is your daily tech briefing for {date}. "
            "Quiet day — nothing notable came up across the tracked topics in the last "
            "24 hours. We'll be back with more tomorrow."
        )
    else:
        budgets = allocate_word_budgets(topics_with_items)
        topic_names = [label for label, _ in topics_with_items]
        intro = INTRO_TEMPLATE.format(
            date=date,
            topics=", ".join(topic_names[:-1]) + (f", and {topic_names[-1]}" if len(topic_names) > 1 else topic_names[0]),
        )

        segments = []
        for label, items in topics_with_items:
            log.info("Generating segment: %s (target ~%d words, %d items)", label, budgets[label], len(items))
            segments.append(generate_topic_segment(label, items, budgets[label]))

        script_text = "\n\n".join([intro, *segments, OUTRO_TEXT])

    script_path = data_dir / f"script_{date}.md"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_text)
    word_count = len(script_text.split())
    log.info("Wrote %s (%d words, ~%.1f min at 150wpm)", script_path, word_count, word_count / 150)

    topics_covered = [
        {"topic": t["label"], "sources": [{"title": i["title"], "url": i["url"]} for i in t["items"]]}
        for t in collected["topics"].values()
        if t["items"]
    ]
    transcript = {
        "date": date,
        "script": script_text,
        "topics_covered": topics_covered,
    }
    transcript_path = data_dir / f"transcript_{date}.json"
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2)
    log.info("Wrote %s", transcript_path)


if __name__ == "__main__":
    main()
