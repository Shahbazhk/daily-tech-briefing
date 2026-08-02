"""
Turns pipeline/data/collected_<date>.json into a single narrated podcast
script (~2,600-3,000 words / ~18-22 min spoken) using an open-weight model
served free by Groq Cloud (https://console.groq.com).

Model IDs on Groq's free tier change over time as they add/retire models —
if GROQ_MODEL 404s, check https://console.groq.com/docs/models and update
the default below or set GROQ_MODEL in the environment.

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
TARGET_WORDS = "2600-3000"
# Below this, we ask the model to rewrite deeper rather than ship a too-short episode.
# (Real failure seen in testing: the model returned a technically-correct but only
# ~550-word script — well short of a 20-minute episode.)
MIN_WORDS = 2200
MAX_EXPAND_ATTEMPTS = 2

SYSTEM_PROMPT = f"""You are the writer for a daily technology news podcast aimed at a working
backend/DevOps engineer. You turn a list of raw news items (blog posts, GitHub releases,
Hacker News threads, Reddit discussions) into ONE cohesive narration script for a single
narrator to read aloud.

Rules:
- Plain, conversational, simple English. Explain jargon briefly the first time it appears.
- Target length: {TARGET_WORDS} words total (about 18-22 minutes spoken). This is a real
  requirement, not a rough suggestion — a short script means a short, unsatisfying episode.
- Depth over brevity: for each notable item, spend roughly 150-300 words on it. Don't just
  announce it in one or two sentences — walk through what actually changed, background context
  a listener might not already know, why it matters in day-to-day engineering practice, and
  (when the source material supports it) which companies/projects use or are affected by it,
  and if it's a bug/incident/outage, the issue and how it was resolved.
- If today's collected items are thin (few topics, few items each), do NOT pad with filler or
  repetition — instead go deeper on the topics you do have: more background, more real-world
  framing, more explanation of consequences, until the length target is met honestly.
- Structure: a short intro naming what's covered today, then one segment per topic that has
  real news (skip topics with nothing notable), a "quick hits" round-up for minor items, then
  a short outro.
- Do not invent facts, company names, or resolutions that are not supported by the provided
  items. Depth means more explanation of what's given, not invented specifics.
- Write it as continuous spoken narration (no markdown headers, no bullet points) — this text
  will be read aloud by a text-to-speech engine.
- End with a one-line sign-off.
"""


def build_user_prompt(collected: dict) -> str:
    lines = [f"Today's date (UTC): {collected['date']}", ""]
    any_items = False
    for topic_key, topic in collected["topics"].items():
        items = topic["items"]
        if not items:
            continue
        any_items = True
        lines.append(f"## Topic: {topic['label']}")
        for item in items:
            lines.append(
                f"- [{item['source']}] {item['title']} — {item['snippet']} (source: {item['url']})"
            )
        lines.append("")
    if not any_items:
        lines.append("(No notable items collected in the last 24 hours for any tracked topic.)")
    return "\n".join(lines)


def call_groq(messages: list[dict]) -> str:
    from groq import Groq

    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.5,
        max_tokens=4096,
    )
    return response.choices[0].message.content.strip()


def generate_script(system_prompt: str, user_prompt: str) -> str:
    """Calls Groq, and if the model shortchanges the length target, asks it to
    rewrite the full script deeper (rather than just append) so the narration
    stays coherent. Caps at MAX_EXPAND_ATTEMPTS retries to bound cost/time."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    script = call_groq(messages)

    for attempt in range(1, MAX_EXPAND_ATTEMPTS + 1):
        word_count = len(script.split())
        if word_count >= MIN_WORDS:
            break
        log.warning(
            "Script came back at %d words (need >= %d) - asking for a deeper rewrite (attempt %d/%d)...",
            word_count, MIN_WORDS, attempt, MAX_EXPAND_ATTEMPTS,
        )
        messages.append({"role": "assistant", "content": script})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"That draft was only about {word_count} words — too short. Rewrite the ENTIRE "
                    f"script again from the top (don't just add more, rewrite the whole thing), "
                    f"keeping the same facts and structure, but go noticeably deeper on each item: "
                    f"more background context, more concrete explanation of why it matters, more "
                    f"real-world framing. Target {TARGET_WORDS} words total this time."
                ),
            }
        )
        script = call_groq(messages)

    final_count = len(script.split())
    if final_count < MIN_WORDS:
        log.warning(
            "Script still only %d words after %d expand attempt(s) — shipping it anyway "
            "(today's news was likely thin). Episode will run shorter than 18-22 min.",
            final_count, MAX_EXPAND_ATTEMPTS,
        )
    return script


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    collected_path = data_dir / f"collected_{date}.json"
    if not collected_path.exists():
        raise SystemExit(f"Missing {collected_path} — run collector/collect.py first.")

    with open(collected_path, "r", encoding="utf-8") as f:
        collected = json.load(f)

    user_prompt = build_user_prompt(collected)
    log.info("Calling Groq to write today's script...")
    script_text = generate_script(SYSTEM_PROMPT, user_prompt)

    script_path = data_dir / f"script_{date}.md"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_text)
    log.info("Wrote %s (%d words)", script_path, len(script_text.split()))

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
