"""
Collects the last `lookback_hours` of activity for every topic in
pipeline/config/sources.yaml, from four free sources:
  - RSS/Atom feeds (official blogs/release notes)
  - GitHub Releases API
  - Hacker News (Algolia search API)
  - Reddit (via PRAW, read-only)

Output: pipeline/data/collected_<date>.json — consumed by scripting/generate_script.py.

Design note: every fetch_* function catches its own exceptions and logs+skips
rather than raising, so one broken feed URL or a down API doesn't kill the
whole day's episode.
"""

import calendar
import json
import os
import sys
from pathlib import Path
from typing import Any

import feedparser
import requests
import yaml
from dateutil import parser as dateparser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CONFIG_PATH, episode_date, ensure_data_dir, get_logger  # noqa: E402

log = get_logger("collector")

GITHUB_API = "https://api.github.com"
HN_ALGOLIA_API = "https://hn.algolia.com/api/v1/search_by_date"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_rss(url: str, cutoff_ts: float) -> list[dict]:
    items = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if not published_struct:
                continue
            published_ts = calendar.timegm(published_struct)
            if published_ts < cutoff_ts:
                continue
            items.append(
                {
                    "source": "rss",
                    "source_name": feed.feed.get("title", url),
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "snippet": (entry.get("summary", "") or "")[:600],
                    "published_at": published_ts,
                }
            )
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see module docstring
        log.warning("RSS fetch failed for %s: %s", url, exc)
    return items


def fetch_github_releases(repo: str, cutoff_ts: float, token: str | None) -> list[dict]:
    items = []
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/releases",
            headers=headers,
            params={"per_page": 10},
            timeout=20,
        )
        resp.raise_for_status()
        for release in resp.json():
            published = release.get("published_at")
            if not published:
                continue
            published_ts = dateparser.isoparse(published).timestamp()
            if published_ts < cutoff_ts:
                continue
            items.append(
                {
                    "source": "github_release",
                    "source_name": repo,
                    "title": f"{repo}: {release.get('name') or release.get('tag_name')}",
                    "url": release.get("html_url", ""),
                    "snippet": (release.get("body") or "")[:600],
                    "published_at": published_ts,
                }
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub releases fetch failed for %s: %s", repo, exc)
    return items


def fetch_hn(query: str, cutoff_ts: float) -> list[dict]:
    items = []
    try:
        resp = requests.get(
            HN_ALGOLIA_API,
            params={
                "tags": "story",
                "query": query,
                "numericFilters": f"created_at_i>{int(cutoff_ts)}",
            },
            timeout=20,
        )
        resp.raise_for_status()
        for hit in resp.json().get("hits", [])[:10]:
            items.append(
                {
                    "source": "hackernews",
                    "source_name": "Hacker News",
                    "title": hit.get("title", ""),
                    "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                    "snippet": f"{hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments",
                    "published_at": hit.get("created_at_i", cutoff_ts),
                }
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("HN fetch failed for query '%s': %s", query, exc)
    return items


def fetch_reddit(subs: list[str], cutoff_ts: float) -> list[dict]:
    items = []
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "shahbaz-daily-updates/0.1")
    if not subs or not client_id or not client_secret:
        return items
    try:
        import praw

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        reddit.read_only = True
        for sub in subs:
            for post in reddit.subreddit(sub).new(limit=25):
                if post.created_utc < cutoff_ts:
                    continue
                items.append(
                    {
                        "source": "reddit",
                        "source_name": f"r/{sub}",
                        "title": post.title,
                        "url": f"https://reddit.com{post.permalink}",
                        "snippet": (post.selftext or "")[:600],
                        "published_at": post.created_utc,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("Reddit fetch failed for subs %s: %s", subs, exc)
    return items


def collect_topic(topic_key: str, topic_cfg: dict, cutoff_ts: float, gh_token: str | None) -> list[dict]:
    items: list[dict] = []
    for url in topic_cfg.get("rss", []) or []:
        items.extend(fetch_rss(url, cutoff_ts))
    for repo in topic_cfg.get("github_repos", []) or []:
        items.extend(fetch_github_releases(repo, cutoff_ts, gh_token))
    if topic_cfg.get("hn_query"):
        items.extend(fetch_hn(topic_cfg["hn_query"], cutoff_ts))
    items.extend(fetch_reddit(topic_cfg.get("reddit_subs", []) or [], cutoff_ts))

    deduped: dict[str, dict] = {}
    for item in items:
        if item.get("url"):
            deduped.setdefault(item["url"], item)
    ranked = sorted(deduped.values(), key=lambda i: i["published_at"], reverse=True)
    return ranked


def main() -> None:
    config = load_config()
    lookback_hours = config.get("lookback_hours", 24)
    max_items = config.get("max_items_per_topic", 8)
    gh_token = os.environ.get("GH_API_TOKEN")

    import time

    cutoff_ts = time.time() - lookback_hours * 3600

    result: dict[str, Any] = {"date": episode_date(), "lookback_hours": lookback_hours, "topics": {}}
    for topic_key, topic_cfg in config["topics"].items():
        log.info("Collecting topic: %s", topic_key)
        items = collect_topic(topic_key, topic_cfg, cutoff_ts, gh_token)[:max_items]
        result["topics"][topic_key] = {"label": topic_cfg.get("label", topic_key), "items": items}
        log.info("  -> %d items", len(items))

    out_dir = ensure_data_dir()
    out_path = out_dir / f"collected_{result['date']}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", out_path)


if __name__ == "__main__":
    main()
