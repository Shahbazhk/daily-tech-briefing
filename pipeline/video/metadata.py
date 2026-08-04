"""
Generates the YouTube title/description/tags for today's episode via one
additional Groq call (same free API already used for the script), fed the
already safety-approved script + topic list - see design spec Section 3.4:
no separate safety check needed here since the source script has already
passed the guardrail in scripting/generate_script.py.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import call_groq, ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("metadata")

# YouTube's own limits (title: 100 chars, no <>; tags: 500 chars combined) - enforced
# here rather than trusted from the LLM, since an out-of-spec value costs the day's
# upload with a bare HTTP 400 and no automatic retry.
MAX_TITLE_LEN = 100
MAX_TAGS_CHARS = 500
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

METADATA_SYSTEM_PROMPT = """You write YouTube metadata for a daily technology news podcast video.
Given the date, topic list, and full narration script for today's episode, produce a JSON object
with exactly these keys:
- "title": a short, specific, compelling title (under 100 characters), mentioning the date and the
  most notable topic(s) - not a generic template.
- "description": 2-4 sentences summarizing what's covered, followed by a line listing the topics.
- "tags": a JSON array of 5-10 relevant lowercase tags (e.g. "java", "spring boot", "kubernetes").

Respond with ONLY the JSON object, no other text, no markdown code fences.
"""

DISCLOSURE_LINE = (
    "\n\nThis episode is narrated by an AI voice (Kokoro TTS) and its news content is "
    "aggregated and summarized from public sources."
)


def build_metadata_prompt(date: str, topics: list[str], script: str) -> str:
    return f"Date: {date}\nTopics covered: {', '.join(topics)}\n\nFull script:\n{script}"


def _strip_fences(raw: str) -> str:
    return _FENCE_RE.sub("", raw.strip())


def _parse_json(raw: str) -> dict:
    return json.loads(_strip_fences(raw))


def _normalize(data: dict, date: str) -> dict:
    # Never trust the LLM's output shape/length against YouTube's own limits - a
    # missing key, an oversized title, or a non-list tags field costs the day's
    # upload with a bare HTTP 400 and no automatic retry.
    title = str(data.get("title") or f"Daily Tech Briefing — {date}")
    title = title.replace("<", "").replace(">", "")[:MAX_TITLE_LEN]

    description = str(data.get("description") or "")

    raw_tags = data.get("tags")
    if not isinstance(raw_tags, list):
        raw_tags = []
    tags: list[str] = []
    total_len = 0
    for tag in raw_tags:
        if not isinstance(tag, str) or not tag:
            continue
        total_len += len(tag) + 1  # +1 for YouTube's implied separator
        if total_len > MAX_TAGS_CHARS:
            break
        tags.append(tag)

    return {"title": title, "description": description, "tags": tags}


def generate_metadata(date: str, topics: list[str], script: str) -> dict:
    messages = [
        {"role": "system", "content": METADATA_SYSTEM_PROMPT},
        {"role": "user", "content": build_metadata_prompt(date, topics, script)},
    ]
    raw = call_groq(messages, max_tokens=500)
    try:
        data = _parse_json(raw)
    except json.JSONDecodeError:
        log.warning("Metadata response wasn't valid JSON - retrying once...")
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": "That wasn't valid JSON. Respond with ONLY the JSON object, no other text."}
        )
        raw = call_groq(messages, max_tokens=500)
        data = _parse_json(raw)

    result = _normalize(data, date)
    result["description"] = result["description"].rstrip() + DISCLOSURE_LINE
    return result


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    transcript_path = data_dir / f"transcript_{date}.json"
    if not transcript_path.exists():
        raise SystemExit(f"Missing {transcript_path} — run scripting/generate_script.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]

    result = generate_metadata(date, topics, transcript["script"])

    out_path = data_dir / f"youtube_metadata_{date}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("Wrote %s: %s", out_path, result["title"])


if __name__ == "__main__":
    main()
