# Design: Episode website (GitHub Pages)

Date: 2026-09-09

## Overview

A static website, hosted on GitHub Pages, listing every published episode of both shows
("Daily Tech Briefing" and "Project Manager's Room") with an audio player, an embedded
YouTube video, and the topics covered — mirroring what the Android app does, but
browser-accessible with no install. Plain HTML/CSS/vanilla JS, no framework, no build
tooling for the page itself; a small Python script regenerates the episode data whenever
a new release is published.

## Goals

- One site, two sections/tabs (Tech Briefing / Project Manager's Room), each a
  newest-first list of episode cards: date, topics covered, an `<audio>` player pointing
  at the release's mp3, and an embedded YouTube `<iframe>` for that specific episode's
  video.
- Fully static: no backend server, no client-side GitHub API calls (avoids exposing every
  visitor to GitHub's unauthenticated rate limit) — data is pre-built at deploy time.
- Auto-redeploys whenever either show publishes a new episode (GitHub Release), with no
  changes to the two existing daily workflows.

## Non-goals

- No change to the Android app.
- No coverage of episodes published *before* this feature ships — their release assets
  have no YouTube video ID recorded (see "Known gap" below), so the manifest script
  represents them as audio-only (video block omitted), not an error.
- No support for the Firebase-primary publish path's data (Firestore) — the site reads
  GitHub Releases only, matching this project's actual configuration (Firebase isn't set
  up; see README). A Firebase-based site would need a different data source and is out of
  scope.
- No search, filtering, or pagination — a personal daily/near-daily show's episode list
  stays small enough that a single scrollable list per section is fine. Revisit if the
  list grows large enough to matter.

## Known gap this design accepts

`publish.py` (Firestore path) runs *before* `youtube_publish.py` in `run_pipeline.py`'s
stage order, so if Firebase were ever configured, the Firestore document would never
carry the YouTube video ID (written after Firestore's write already happened). Since this
project uses the GitHub Release fallback path exclusively today, this doesn't block
anything here — noted so a future Firebase migration doesn't silently inherit this gap
unnoticed.

## Component 1: recording the video ID (small pipeline change)

`pipeline/publish/youtube_publish.py`'s `main()` already loads `transcript` (from
`transcript_<date>.json`, already a GitHub Release asset) and later obtains `video_id`
from `upload_video(...)`. After that call, add the id into the same dict and rewrite the
file:

```python
video_id = upload_video(youtube, video_path, result, date)
transcript["youtube_video_id"] = video_id
transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
log.info("Uploaded video id %s, adding to playlist %s...", video_id, playlist_id)
```

This runs before the workflow's later "attach to GitHub Release" step, so the updated
file (now carrying `youtube_video_id`) is what actually gets attached — no workflow
change needed. Existing/older releases' `transcript_*.json` files predate this field and
simply won't have it; the manifest script (Component 2) treats that as "no video for this
episode" rather than an error.

## Component 2: manifest generation script

New `site/generate_manifest.py` (self-contained, its own tiny `site/requirements.txt`
with just `requests` — deliberately NOT reusing `pipeline/requirements.txt`, which pulls
in torch/kokoro/etc. that this script has no use for and would needlessly slow down its
workflow).

For each show, list GitHub Releases via the REST API (authenticated with the workflow's
own `GITHUB_TOKEN` for the 5,000/hour limit, same pattern `collector/collect.py` already
uses for `GH_API_TOKEN`), filtering by an **exact-date regex per show** —
`^episode-\d{4}-\d{2}-\d{2}$` for tech, `^episode-pm-\d{4}-\d{2}-\d{2}$` for PM. This is
deliberately NOT the `startsWith("episode-")` prefix-match `EpisodeRepository.kt` still
uses (a known, separately-tracked bug in the Android app: a PM release would match a
tech-prefixed check) — this script gets the exact-match fix from the start rather than
inheriting that mistake.

For each matching release: download its `transcript_*.json` asset, extract `date`,
`topics_covered` (just the topic names), and `youtube_video_id` (`None` if absent — older
releases). Find the `.mp3` asset's `browser_download_url` for `audio_url`. Sort
newest-first. Write `site/data/tech.json` and `site/data/pm.json`:

```json
{
  "show_label": "Daily Tech Briefing",
  "episodes": [
    {
      "date": "2026-09-08",
      "topics": ["Java", "Kubernetes", "The Architect's Corner"],
      "audio_url": "https://github.com/.../episode_2026-09-08.mp3",
      "video_id": "JfR9_ajz4c8"
    }
  ]
}
```

A release missing its `.mp3` or `transcript_*.json` asset (shouldn't happen given how
the workflow attaches them, but defensively) is skipped with a log line, not a hard
failure — matching this codebase's existing "one broken thing shouldn't kill the whole
run" convention.

## Component 3: the static site

`site/index.html` + `site/style.css` + `site/app.js`. Two tab buttons at the top ("Tech
Briefing" / "Project Manager's Room") toggling which section is visible (plain
`el.hidden`, no routing/framework) — mirrors the Android app's two-button toggle. On
load, `app.js` fetches `data/tech.json` and `data/pm.json` (same-origin, so no CORS/API
concerns — these are static files served alongside the page) and renders one card per
episode: date heading, topics as a comma-separated line, an `<audio controls src=...>`
element, and — only when `video_id` is present — an
`<iframe src="https://www.youtube.com/embed/{video_id}">`; when absent, the card shows
just the audio player with no broken embed. A fetch failure (e.g. a stale/missing JSON
file) shows a simple "couldn't load episodes" message per section rather than a blank
page.

Styling: minimal, plain CSS, mobile-responsive (single-column card list, works at phone
width), no external CSS/JS dependencies — keeps the site fast and dependency-free, matching
the "plain HTML/CSS/JS, no build step" decision.

## Component 4: deployment workflow

New `.github/workflows/deploy-site.yml`:
- Triggers: `release: [published]` (fires automatically after either show's daily run
  creates a release) and `workflow_dispatch` (manual redeploy/testing).
- Steps: checkout, set up Python, `pip install -r site/requirements.txt`, run
  `site/generate_manifest.py`, then deploy via the official GitHub Pages Actions
  (`actions/upload-pages-artifact` on the `site/` directory, then
  `actions/deploy-pages`) — the modern Actions-based Pages deployment, not a `gh-pages`
  branch, so no generated-data commits land in git history.
- Deliberately a separate workflow, not a step added to `daily-episode.yml` or
  `daily-pm-episode.yml` — decouples site deployment from either show's own pipeline and
  avoids touching already-working, already-reviewed workflow files.

**One-time manual step required (cannot be done from this session):** repo Settings →
Pages → Build and deployment → Source: **GitHub Actions**. Until that's set, the
`deploy-pages` action will fail with a clear error naming this exact setting.

## Testing

- `generate_manifest.py`'s pure logic (release filtering by regex, transcript parsing,
  building the episode dict, handling a missing `video_id`) gets unit tests with a
  `pytest`-based `site/tests/` directory, mocking the GitHub API responses — same style as
  `pipeline/tests/`.
- The static HTML/JS has no test framework in this repo to extend; verification is a
  manual check (open the deployed page, confirm both sections render, confirm audio
  plays, confirm video embeds show for episodes published after this feature ships, and
  that older episodes show audio-only without a broken iframe).

## Rollout

1. Ship Components 1–4.
2. You flip the repo's Pages source setting to "GitHub Actions" (or I attempt it via API
   first and report whether it worked).
3. Trigger `deploy-site.yml` manually once via `workflow_dispatch` to confirm the full
   chain (manifest generation → Pages deploy) before relying on the `release: published`
   trigger for future episodes.
4. The next real PM or tech show run will carry a `youtube_video_id` in its transcript
   and automatically trigger a redeploy via the `release: published` event.
