"""
Turns pipeline/data/collected_<date>.json into a single narrated podcast script (~2,800
words / ~18-22 min spoken on a normal news day) using an open-weight model served free by
Groq Cloud (https://console.groq.com).

Model IDs on Groq's free tier change over time as they add/retire models —
if GROQ_MODEL 404s, check https://console.groq.com/docs/models and update
the default below or set GROQ_MODEL in the environment.

Structure: intro -> one segment per tracked topic (Java, Spring Boot, Liferay DXP, ...,
Angular, Cloud) -> a transition -> "The Architect's Corner" (a fixed ~5-minute segment on a
real enterprise system-design/architecture case study, sourced from real engineering blogs
with its own wider lookback since those post far less often than daily — see
architecture_corner in sources.yaml) -> outro.

Design note: we generate ONE segment per Groq call, each with its own explicit word-count
budget, rather than asking for the whole episode in a single prompt. First-round testing
showed the single-big-prompt approach badly undershoots (the model returned ~550, then
plateaued around ~1500 words even after being told to expand) — a model asked to hit a
small, concrete per-segment target follows it far more reliably than one asked to self-pace
a long global target. Intro/outro/transition are templated directly (no LLM call needed —
there's nothing creative there, just structure).

On a genuinely thin news day (few topics, few items), the resulting episode will
legitimately run shorter than 18-22 minutes. That's intentional: BRD Section 11 and the
system prompts both say not to pad with invented content just to hit a length.

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

# Main tracked-topic pool. The Architect's Corner (see below) has its own separate ~720-word
# budget on top of this, so the two together still land near the ~2800-word / ~20 min episode
# target on a normal day — see BRD Section 11.
TOPIC_TARGET_WORDS = 2000
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

ARCHITECTURE_SYSTEM_PROMPT = """You are the writer for "The Architect's Corner" — a ~5-minute
recurring segment on a daily technology podcast, aimed at a working software architect on
enterprise projects. You write ONLY this segment, not the whole episode — another process
stitches it in, so do NOT write "welcome" or "goodbye" framing, just dive in.

This segment covers ONE real problem an engineering team faced and the solution they built,
told the way a system-design case study or architecture deep-dive is told:
1. The problem: what situation/constraint/scale challenge the team was facing, in concrete terms.
2. The solution: what they actually built or changed — the architecture/design decisions involved.
3. Why it matters: what a listener working on enterprise systems should take away from it —
   trade-offs, when this pattern applies elsewhere, what could go wrong if misapplied.

Rules:
- Plain, conversational, simple English, but keep the technical substance real — this is for an
  experienced audience, so don't over-simplify the architecture itself, just the delivery.
- Do not invent facts, numbers, or outcomes not supported by the provided source material. If the
  source is thin on a detail (e.g. exact scale numbers), speak in the general terms the source
  actually supports rather than inventing specifics.
- If two items are provided, pick the single most substantial one and go deep on it rather than
  splitting shallowly across both — depth over coverage for this segment specifically.
- Continuous spoken narration only — no markdown headers, no bullet points, no title (the segment
  is introduced separately). This text is read aloud by a TTS engine.
"""

INTRO_TEMPLATE = (
    "Good morning. Here's your daily tech briefing for {date}. "
    "Today we're covering {topics}. Let's get into it."
)
ARCHITECTURE_TRANSITION = (
    "Now, let's shift gears for the Architect's Corner — five minutes on real enterprise "
    "software architecture and system design."
)
OUTRO_TEXT = "And that's your briefing for today. See you tomorrow morning."


def build_segment_prompt(topic_label: str, items: list[dict], target_words: int, description: str = "") -> str:
    lines = [f"Topic for this segment: {topic_label}"]
    if description:
        lines.append(f"Context on this topic: {description.strip()}")
    lines.append(f"Target length for this segment: about {target_words} words.")
    lines.append("")
    lines.append("Items collected in the last 24 hours for this topic:")
    for item in items:
        lines.append(f"- [{item['source']}] {item['title']} — {item['snippet']} (source: {item['url']})")
    return "\n".join(lines)


def build_architecture_prompt(items: list[dict], target_words: int, description: str = "") -> str:
    lines = []
    if description:
        lines.append(f"Segment context: {description.strip()}")
    lines.append(f"Target length: about {target_words} words.")
    lines.append("")
    lines.append("Candidate source article(s) from real engineering blogs (pick the best one):")
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


def generate_topic_segment(topic_label: str, items: list[dict], target_words: int, description: str = "") -> str:
    messages = [
        {"role": "system", "content": SEGMENT_SYSTEM_PROMPT},
        {"role": "user", "content": build_segment_prompt(topic_label, items, target_words, description)},
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


def generate_architecture_segment(items: list[dict], target_words: int, description: str = "") -> str:
    messages = [
        {"role": "system", "content": ARCHITECTURE_SYSTEM_PROMPT},
        {"role": "user", "content": build_architecture_prompt(items, target_words, description)},
    ]
    segment = call_groq(messages, max_tokens=min(1800, target_words * 3))

    word_count = len(segment.split())
    if word_count < target_words * SEGMENT_RETRY_THRESHOLD:
        log.warning(
            "Architect's Corner came back at %d words (target ~%d) - retrying once with a firmer ask...",
            word_count, target_words,
        )
        messages.append({"role": "assistant", "content": segment})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"That was only about {word_count} words. Go deeper on the problem, the solution's "
                    f"design details, and the trade-offs/takeaways, aiming for closer to {target_words} "
                    f"words. If the source material is genuinely thin, get as close as you honestly can "
                    f"without inventing details."
                ),
            }
        )
        segment = call_groq(messages, max_tokens=min(1800, target_words * 3))

    return segment


def allocate_word_budgets(topics_with_items: list[tuple[str, list[dict]]]) -> dict[str, int]:
    """Splits TOPIC_TARGET_WORDS across topics proportionally to how many items
    each one has, so a topic with more news gets more airtime, within a
    [MIN_SEGMENT_WORDS, MAX_SEGMENT_WORDS] band per topic."""
    total_items = sum(len(items) for _, items in topics_with_items) or 1
    budgets = {}
    for label, items in topics_with_items:
        share = len(items) / total_items
        budget = round(TOPIC_TARGET_WORDS * share)
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
        (t["label"], t["items"], t.get("description", ""))
        for t in collected["topics"].values()
        if t["items"]
    ]
    arch = collected.get("architecture_corner")
    arch_has_items = bool(arch and arch["items"])

    if not topics_with_items and not arch_has_items:
        script_text = (
            f"Good morning. This is your daily tech briefing for {date}. "
            "Quiet day — nothing notable came up across the tracked topics in the last "
            "24 hours. We'll be back with more tomorrow."
        )
    else:
        parts: list[str] = []

        if topics_with_items:
            budgets = allocate_word_budgets([(label, items) for label, items, _ in topics_with_items])
            topic_names = [label for label, _, _ in topics_with_items]
            topics_phrase = ", ".join(topic_names[:-1]) + (
                f", and {topic_names[-1]}" if len(topic_names) > 1 else topic_names[0]
            )
            if arch_has_items:
                topics_phrase += ", plus the Architect's Corner"
            parts.append(INTRO_TEMPLATE.format(date=date, topics=topics_phrase))

            for label, items, description in topics_with_items:
                log.info(
                    "Generating segment: %s (target ~%d words, %d items)", label, budgets[label], len(items)
                )
                parts.append(generate_topic_segment(label, items, budgets[label], description))
        else:
            # Tracked topics were quiet, but the Architect's Corner has something — still
            # worth an episode rather than skipping the day entirely.
            parts.append(
                f"Good morning. Here's your daily tech briefing for {date}. "
                "The tracked topics were quiet today, but we've got a good one for the "
                "Architect's Corner. Let's get into it."
            )

        if arch_has_items:
            arch_target = arch.get("target_words", 720)
            log.info(
                "Generating Architect's Corner (target ~%d words, %d items)", arch_target, len(arch["items"])
            )
            if topics_with_items:
                parts.append(ARCHITECTURE_TRANSITION)
            parts.append(generate_architecture_segment(arch["items"], arch_target, arch.get("description", "")))

        parts.append(OUTRO_TEXT)
        script_text = "\n\n".join(parts)

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
    if arch_has_items:
        topics_covered.append(
            {"topic": arch["label"], "sources": [{"title": i["title"], "url": i["url"]} for i in arch["items"]]}
        )
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
