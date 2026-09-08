"""
Turns pipeline/data/collected_pm_<date>.json into a single narrated podcast script for
"Project Manager's Room" (~10 min / ~1,500 words) using Groq - see design spec
docs/superpowers/specs/2026-09-08-pm-delivery-show-design.md.

Structure: intro -> latest updates across PM/delivery sub-topics (~5 min) -> deep dive on
today's biggest item (~2 min) -> a fictional/illustrative story segment (~3 min) -> outro.

Unlike generate_script.py, the story segment is explicitly ALLOWED to invent characters,
dialogue, and scenario (never real company/person names) - the one deliberate exception to
this codebase's "never invent facts" rule, scoped to this one segment only. The story segment
runs every day regardless of news volume, since it isn't sourced from collected items - so
even a quiet PM-news day still produces a real (if shorter) episode, consistent with this
codebase's "don't pad with invented content just to hit a length" rule for sourced segments.

Output:
  pipeline/data/script_pm_<date>.md        - the narration script (fed to TTS)
  pipeline/data/transcript_pm_<date>.json  - script + per-topic source links
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ContentSafetyError,
    artifact_path,
    call_groq,
    check_segment_safety,
    episode_date,
    get_logger,
    retry_with_safety_reminder,
)
from generate_script import allocate_word_budgets  # noqa: E402

log = get_logger("scripting_pm")

LATEST_UPDATES_TARGET_WORDS = 750
MIN_SEGMENT_WORDS = 100
MAX_SEGMENT_WORDS = 250
SEGMENT_RETRY_THRESHOLD = 0.5

DEEP_DIVE_TARGET_WORDS = 300
STORY_TARGET_WORDS = 450

STORY_THEMES = [
    "scope creep",
    "stakeholder conflict",
    "vendor and dependency risk",
    "distributed-team friction",
    "burnout and crunch",
    "agile vs. waterfall tension",
    "scope negotiation",
    "communication breakdown",
]

LATEST_UPDATES_SYSTEM_PROMPT = """You are the writer for "Project Manager's Room," a daily
podcast for IT project and delivery managers. You write ONE segment of the show at a time
covering a single PM/delivery sub-topic - not the whole episode. Another process stitches your
segments together with an intro and outro, so do NOT write any "welcome" or "that's it for today"
framing - just dive straight into the sub-topic's news as if the listener is already mid-episode.

Rules:
- Plain, conversational, simple English aimed at a working delivery/project manager.
- For each item, explain what happened, why it matters for someone running delivery day to day,
  and (when the source supports it) which teams/organizations/tools are affected.
- Do not invent facts, company names, or outcomes not supported by the provided items. If you run
  out of genuine substance before hitting the word target, stop rather than pad with filler.
- Continuous spoken narration only - no markdown headers, no bullet points, no segment title (the
  sub-topic name is introduced separately). This text is read aloud by a TTS engine.
- Never include vulgarity, profanity, or sexual content. Never present an unethical practice (e.g.
  manipulating stakeholders, hiding risk from sponsors, exploiting a team through crunch) as
  something to emulate or admire - if a source item is fundamentally about such a practice, report
  it critically or skip it rather than endorsing it.
"""

DEEP_DIVE_SYSTEM_PROMPT = """You are the writer for the "Deep Dive" segment of "Project Manager's
Room," a daily podcast for IT project and delivery managers. You write ONLY this segment - another
process stitches it in, so do NOT write "welcome" or "goodbye" framing, just dive in.

This segment takes the single most significant PM/delivery story collected today and goes deeper
than a news blurb: what happened, the background context a listener might not already know, and
concretely what a working delivery manager should take away from it - a risk to watch for, a
practice to consider, a question to ask on their own project.

Rules:
- Plain, conversational, simple English, but keep the substance real for an experienced audience.
- Do not invent facts, numbers, or outcomes not supported by the provided source material. If the
  source is thin on a detail, speak in the general terms it actually supports.
- Continuous spoken narration only - no markdown headers, no bullet points, no title.
- Never include vulgarity, profanity, or sexual content. Never present an unethical practice as
  something to emulate or admire.
"""


# ponytail: no-real-names rule is prompt-only; add a named-entity check here if this proves
# unreliable in practice.
def build_story_system_prompt(theme: str) -> str:
    return f"""You are the writer for the "Story" segment of "Project Manager's Room," a daily
podcast for IT project and delivery managers. You write ONLY this segment - another process
stitches it in, so do NOT write "welcome" or "goodbye" framing, just dive in.

Unlike every other segment on this show, this one is explicitly FICTIONAL and ILLUSTRATIVE: invent
a short, realistic scenario - with characters, dialogue, and a concrete situation - that brings
today's theme to life for a delivery/project manager audience. This is the one segment where you
are allowed, and expected, to invent details.

Today's theme: {theme}

Rules:
- Invent fictional characters and a fictional company/team - generic, plausible names (e.g. "Maria,
  a delivery manager at a mid-sized logistics company"). NEVER use the name of a real, identifiable
  company, product, or person, and never imply the story is a real reported event.
- Ground the scenario in realistic day-to-day project-management detail (a standup, a steering
  committee, a status call, a hallway conversation) so it reads as plausible, not cartoonish.
- End with a brief, concrete takeaway a real delivery manager could apply.
- Continuous spoken narration only - no markdown headers, no bullet points, no title, no "the
  following is fictional" disclaimer text (a separate templated line already introduces it as a
  story before your text plays).
- Never include vulgarity, profanity, or sexual content. Never depict an unethical practice (e.g.
  retaliating against a whistleblower, falsifying status reports, exploiting a team through crunch)
  as something to emulate or admire - if the scenario involves such a practice, show it going wrong
  or being corrected, not rewarded.
"""


INTRO_TEMPLATE = (
    "Here's today's Project Manager's Room briefing for {date}. Coming up: the latest in "
    "{topics}, a closer look at today's biggest story, and a scenario from the field. "
    "Let's get into it."
)
QUIET_DAY_INTRO_TEMPLATE = (
    "Here's today's Project Manager's Room briefing for {date}. It's a quiet day across the "
    "tracked PM and delivery topics, so we're going straight to today's scenario."
)
DEEP_DIVE_TRANSITION = "Now, let's take a closer look at today's biggest story."
STORY_TRANSITION = (
    "Now, a quick scenario — a fictional situation to bring today's theme to life."
)
OUTRO_TEXT = "And that's Project Manager's Room for today. See you tomorrow."


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


def _generate_with_retry_and_safety(
    system_prompt: str,
    user_prompt: str,
    target_words: int,
    segment_label: str,
    retry_reminder: str,
    max_tokens_cap: int = 1600,
) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    max_tokens = min(max_tokens_cap, target_words * 3)
    segment = call_groq(messages, max_tokens=max_tokens)

    word_count = len(segment.split())
    if word_count < target_words * SEGMENT_RETRY_THRESHOLD:
        log.warning(
            "%s segment came back at %d words (target ~%d) - retrying once...",
            segment_label, word_count, target_words,
        )
        messages.append({"role": "assistant", "content": segment})
        messages.append({"role": "user", "content": f"That was only about {word_count} words. {retry_reminder}"})
        segment = call_groq(messages, max_tokens=max_tokens)

    is_safe, reason = check_segment_safety(segment)
    if not is_safe:
        log.warning("%s segment flagged by safety check (%s) - retrying once...", segment_label, reason)
        segment = retry_with_safety_reminder(messages, segment, reason, max_tokens=max_tokens)
        is_safe, reason = check_segment_safety(segment)
        if not is_safe:
            raise ContentSafetyError(segment_label, reason)

    return segment


def generate_latest_updates_segment(topic_label: str, items: list[dict], target_words: int, description: str = "") -> str:
    return _generate_with_retry_and_safety(
        LATEST_UPDATES_SYSTEM_PROMPT,
        build_segment_prompt(topic_label, items, target_words, description),
        target_words,
        topic_label,
        retry_reminder=(
            "Rewrite it, going deeper on why it matters for a working delivery manager, aiming "
            f"for closer to {target_words} words. If there's genuinely not enough substance, get "
            "as close as you honestly can."
        ),
    )


def pick_deep_dive(topics_with_items: list[tuple[str, list[dict], str]]) -> tuple[str, dict, str]:
    """Returns (topic_label, anchor_item, description) for the sub-topic with the most
    collected items that day, anchored on its longest/most detailed item - no extra LLM
    call needed for selection."""
    label, items, description = max(topics_with_items, key=lambda t: len(t[1]))
    anchor = max(items, key=lambda i: len(i.get("snippet", "")))
    return label, anchor, description


def generate_deep_dive_segment(topic_label: str, anchor_item: dict, target_words: int) -> str:
    user_prompt = (
        f"Topic: {topic_label}\n"
        f"Target length: about {target_words} words.\n\n"
        f"The story: [{anchor_item.get('source', '')}] {anchor_item['title']} — {anchor_item['snippet']} "
        f"(source: {anchor_item['url']})"
    )
    return _generate_with_retry_and_safety(
        DEEP_DIVE_SYSTEM_PROMPT,
        user_prompt,
        target_words,
        "Deep Dive",
        retry_reminder=(
            f"Go deeper on the background and the concrete takeaway for a delivery manager, "
            f"aiming for closer to {target_words} words. If the source is genuinely thin, get "
            "as close as you honestly can without inventing details."
        ),
    )


def story_theme_for_date(date_str: str) -> str:
    day_of_year = datetime.strptime(date_str, "%Y-%m-%d").timetuple().tm_yday
    return STORY_THEMES[day_of_year % len(STORY_THEMES)]


def generate_story_segment(theme: str, target_words: int) -> str:
    return _generate_with_retry_and_safety(
        build_story_system_prompt(theme),
        f"Write today's story segment now, following the rules above. Target length: about {target_words} words.",
        target_words,
        "Story",
        retry_reminder=(
            f"Rewrite it with more concrete scene detail (dialogue, setting, a specific decision "
            f"point), aiming for closer to {target_words} words, while still following all the "
            "rules above."
        ),
    )


def main() -> None:
    date = episode_date()
    collected_path = artifact_path("collected", "json", date)
    if not collected_path.exists():
        raise SystemExit(f"Missing {collected_path} — run collector/collect.py first.")

    with open(collected_path, "r", encoding="utf-8") as f:
        collected = json.load(f)

    topics_with_items = [
        (t["label"], t["items"], t.get("description", ""))
        for t in collected["topics"].values()
        if t["items"]
    ]

    parts: list[str] = []
    topics_covered: list[dict] = []

    try:
        if topics_with_items:
            budgets = allocate_word_budgets(
                [(label, items) for label, items, _ in topics_with_items],
                target_words=LATEST_UPDATES_TARGET_WORDS,
                min_words=MIN_SEGMENT_WORDS,
                max_words=MAX_SEGMENT_WORDS,
            )
            topic_names = [label for label, _, _ in topics_with_items]
            topics_phrase = ", ".join(topic_names[:-1]) + (
                f", and {topic_names[-1]}" if len(topic_names) > 1 else topic_names[0]
            )
            parts.append(INTRO_TEMPLATE.format(date=date, topics=topics_phrase))

            for label, items, description in topics_with_items:
                log.info(
                    "Generating latest-updates segment: %s (target ~%d words, %d items)",
                    label, budgets[label], len(items),
                )
                parts.append(generate_latest_updates_segment(label, items, budgets[label], description))
                topics_covered.append(
                    {"topic": label, "sources": [{"title": i["title"], "url": i["url"]} for i in items]}
                )

            parts.append(DEEP_DIVE_TRANSITION)
            deep_label, anchor_item, _ = pick_deep_dive(topics_with_items)
            log.info("Generating deep dive: %s", deep_label)
            parts.append(generate_deep_dive_segment(deep_label, anchor_item, DEEP_DIVE_TARGET_WORDS))
            topics_covered.append(
                {"topic": f"Deep Dive: {deep_label}", "sources": [{"title": anchor_item["title"], "url": anchor_item["url"]}]}
            )
        else:
            parts.append(QUIET_DAY_INTRO_TEMPLATE.format(date=date))

        parts.append(STORY_TRANSITION)
        theme = story_theme_for_date(date)
        log.info("Generating story segment (theme: %s)", theme)
        parts.append(generate_story_segment(theme, STORY_TARGET_WORDS))
        topics_covered.append({"topic": f"Story: {theme}", "sources": []})

        parts.append(OUTRO_TEXT)
        script_text = "\n\n".join(parts)
    except ContentSafetyError as e:
        log.error(
            "CONTENT SAFETY CHECK BLOCKED PUBLISH for %s (pm): %s segment - %s. No script/transcript "
            "written; today's PM episode will not publish.",
            date, e.segment_label, e.reason,
        )
        raise SystemExit(f"Content safety check blocked publish for {date} (pm): {e}") from e

    script_path = artifact_path("script", "md", date)
    script_path.write_text(script_text, encoding="utf-8")
    word_count = len(script_text.split())
    log.info("Wrote %s (%d words, ~%.1f min at 150wpm)", script_path, word_count, word_count / 150)

    transcript = {"date": date, "script": script_text, "topics_covered": topics_covered}
    transcript_path = artifact_path("transcript", "json", date)
    transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    log.info("Wrote %s", transcript_path)


if __name__ == "__main__":
    main()
