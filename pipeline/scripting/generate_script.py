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

SYSTEM_PROMPT = f"""You are the writer for a daily technology news podcast aimed at a working
backend/DevOps engineer. You turn a list of raw news items (blog posts, GitHub releases,
Hacker News threads, Reddit discussions) into ONE cohesive narration script for a single
narrator to read aloud.

Rules:
- Plain, conversational, simple English. Explain jargon briefly the first time it appears.
- Target length: {TARGET_WORDS} words total (about 18-22 minutes spoken).
- Structure: a short intro naming what's covered today, then one segment per topic that has
  real news (skip topics with nothing notable), a "quick hits" round-up for minor items, then
  a short outro.
- For each notable item, where the information supports it, mention: what changed, why it
  matters, which companies/projects are known to use or be affected by this technology, and if
  the story is about a bug/incident/outage, explain the issue and how it was resolved.
- Do not invent facts, company names, or resolutions that are not supported by the provided
  items. If a detail isn't in the source material, don't state it as fact.
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


def call_groq(system_prompt: str, user_prompt: str) -> str:
    from groq import Groq

    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=4096,
    )
    return response.choices[0].message.content.strip()


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
    script_text = call_groq(SYSTEM_PROMPT, user_prompt)

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
