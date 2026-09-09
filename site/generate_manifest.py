"""
Regenerates site/public/data/tech.json and site/public/data/pm.json from this repo's
GitHub Releases, for the episode website - see design spec
docs/superpowers/specs/2026-09-09-episode-website-design.md.

Run by .github/workflows/deploy-site.yml on every new release and on manual dispatch.

Self-contained: only depends on `requests` (see site/requirements.txt) - deliberately
NOT pipeline/requirements.txt, which pulls in torch/kokoro/etc. this script has no use
for and would needlessly slow down its own workflow.
"""

import json
import os
import re
from pathlib import Path
from typing import Callable, Optional

import requests

REPO = "Shahbazhk/daily-tech-briefing"
GITHUB_API = "https://api.github.com"
SITE_ROOT = Path(__file__).resolve().parent
DATA_DIR = SITE_ROOT / "public" / "data"

SHOWS = {
    "tech": {
        "show_label": "Daily Tech Briefing",
        "tag_re": re.compile(r"^episode-\d{4}-\d{2}-\d{2}$"),
        "out_file": "tech.json",
    },
    "pm": {
        "show_label": "Project Manager's Room",
        "tag_re": re.compile(r"^episode-pm-\d{4}-\d{2}-\d{2}$"),
        "out_file": "pm.json",
    },
}


def fetch_all_releases(token: Optional[str]) -> list[dict]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    releases: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            f"{GITHUB_API}/repos/{REPO}/releases",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=20,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        releases.extend(batch)
        page += 1
    return releases


def find_asset_url(release: dict, predicate: Callable[[str], bool]) -> Optional[str]:
    for asset in release.get("assets", []):
        if predicate(asset["name"]):
            return asset["browser_download_url"]
    return None


def build_episode(release: dict, token: Optional[str]) -> Optional[dict]:
    audio_url = find_asset_url(release, lambda n: n.endswith(".mp3"))
    transcript_url = find_asset_url(release, lambda n: n.startswith("transcript_") and n.endswith(".json"))
    if not audio_url or not transcript_url:
        print(f"::warning::Skipping release {release.get('tag_name')} - missing mp3 or transcript asset")
        return None

    # Deliberately unauthenticated, matching the Android app's EpisodeRepository.kt: these
    # are public release-asset URLs, and sending an unexpected auth header to a signed
    # asset-download redirect is an unnecessary risk for no benefit.
    resp = requests.get(transcript_url, timeout=20)
    resp.raise_for_status()
    transcript = resp.json()

    return {
        "date": transcript.get("date", release.get("tag_name", "")),
        "topics": [t["topic"] for t in transcript.get("topics_covered", [])],
        "audio_url": audio_url,
        "video_id": transcript.get("youtube_video_id"),
    }


def build_manifest(show_key: str, releases: list[dict], token: Optional[str]) -> dict:
    show = SHOWS[show_key]
    matching = [r for r in releases if show["tag_re"].match(r.get("tag_name", ""))]
    episodes = []
    for release in matching:
        episode = build_episode(release, token)
        if episode:
            episodes.append(episode)
    episodes.sort(key=lambda e: e["date"], reverse=True)
    return {"show_label": show["show_label"], "episodes": episodes}


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    releases = fetch_all_releases(token)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for show_key, show in SHOWS.items():
        manifest = build_manifest(show_key, releases, token)
        out_path = DATA_DIR / show["out_file"]
        out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Wrote {out_path} ({len(manifest['episodes'])} episodes)")


if __name__ == "__main__":
    main()
