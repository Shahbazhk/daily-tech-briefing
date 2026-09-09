# Episode Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A static GitHub Pages website listing every episode of both shows, each with an audio player, an embedded per-episode YouTube video, and topics covered.

**Architecture:** A small pipeline addition records each episode's YouTube video ID into its existing `transcript_<date>.json` (already a GitHub Release asset). A self-contained Python script (`site/generate_manifest.py`) regenerates two JSON manifests from the repo's GitHub Releases at deploy time, filtered by an exact-date regex per show. A plain HTML/CSS/JS static site (`site/public/`) renders those manifests client-side. A new GitHub Actions workflow deploys the site via the modern Pages Actions on every new release.

**Tech Stack:** Python 3.11 + `requests` (manifest script, isolated from the heavier `pipeline/requirements.txt`), plain HTML/CSS/vanilla JS (no framework, no build step), GitHub Actions (`actions/upload-pages-artifact`, `actions/deploy-pages`).

**Spec:** `docs/superpowers/specs/2026-09-09-episode-website-design.md`

## Global Constraints

- Show-filtering regex must be exact-date, never a prefix match: `^episode-\d{4}-\d{2}-\d{2}$` (tech), `^episode-pm-\d{4}-\d{2}-\d{2}$` (PM) — this is the specific bug the design deliberately avoids repeating (still open, separately tracked, in the Android app).
- `site/generate_manifest.py` depends only on `requests` (via `site/requirements.txt`) — never import from or depend on `pipeline/`.
- An episode missing its `youtube_video_id` (published before this feature) must render audio-only, never a broken embed or an error.
- The deployment workflow is separate from `daily-episode.yml` and `daily-pm-episode.yml` — do not modify either of those files.

---

## Task 1: Record the YouTube video ID into the transcript file

**Files:**
- Modify: `pipeline/publish/youtube_publish.py`
- Test: `pipeline/tests/test_youtube_publish.py`

**Interfaces:**
- Produces: `youtube_publish.record_video_id(transcript_path: Path, transcript: dict, video_id: str) -> None`.

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/test_youtube_publish.py`:

```python
def test_record_video_id_writes_id_into_transcript_file(tmp_path):
    transcript_path = tmp_path / "transcript_2026-09-08.json"
    transcript = {"date": "2026-09-08", "script": "hello", "topics_covered": []}

    youtube_publish.record_video_id(transcript_path, transcript, "abc123")

    saved = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert saved["youtube_video_id"] == "abc123"
    assert saved["date"] == "2026-09-08"
    assert saved["script"] == "hello"
```

Add `import json` to the top of the test file if not already present (check first — `test_youtube_publish.py` currently does not import `json`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && python -m pytest tests/test_youtube_publish.py -v`
Expected: FAIL — `AttributeError: module 'youtube_publish' has no attribute 'record_video_id'`.

- [ ] **Step 3: Implement `record_video_id` and call it from `main()`**

In `pipeline/publish/youtube_publish.py`, add this function right after `add_to_playlist` (before `main`):

```python
def record_video_id(transcript_path: Path, transcript: dict, video_id: str) -> None:
    """Writes the uploaded video's id back into the transcript file so downstream
    consumers (the episode website's manifest generator) can build a direct per-episode
    YouTube embed without a second API call. transcript_path is already a GitHub Release
    asset by the time the workflow's later "attach to release" step runs, so no workflow
    change is needed - this just has to happen before this process exits."""
    transcript["youtube_video_id"] = video_id
    transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
```

In `main()`, replace:
```python
    log.info("Uploading %s to YouTube...", video_path.name)
    video_id = upload_video(youtube, video_path, result, date)
    log.info("Uploaded video id %s, adding to playlist %s...", video_id, playlist_id)
```
with:
```python
    log.info("Uploading %s to YouTube...", video_path.name)
    video_id = upload_video(youtube, video_path, result, date)
    record_video_id(transcript_path, transcript, video_id)
    log.info("Uploaded video id %s, adding to playlist %s...", video_id, playlist_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd pipeline && python -m pytest tests/test_youtube_publish.py -v`
Expected: PASS (7 tests — the original 6 plus this one).

- [ ] **Step 5: Run the full pipeline suite to confirm no regressions**

Run: `cd pipeline && python -m pytest tests/ -v`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add pipeline/publish/youtube_publish.py pipeline/tests/test_youtube_publish.py
git commit -m "Record uploaded YouTube video id into the episode transcript file"
```

---

## Task 2: Manifest generation script

**Files:**
- Create: `site/generate_manifest.py`
- Create: `site/requirements.txt`
- Create: `site/tests/test_generate_manifest.py`
- Create: `site/tests/__init__.py` (empty, matches `pipeline/tests/__init__.py`'s convention)

**Interfaces:**
- Produces: `generate_manifest.fetch_all_releases(token: str | None) -> list[dict]`, `generate_manifest.find_asset_url(release: dict, predicate) -> str | None`, `generate_manifest.build_episode(release: dict, token: str | None) -> dict | None`, `generate_manifest.build_manifest(show_key: str, releases: list[dict], token: str | None) -> dict`, `generate_manifest.SHOWS: dict`, `generate_manifest.main()`.

- [ ] **Step 1: Create `site/requirements.txt`**

```
requests==2.32.3
```

- [ ] **Step 2: Write the failing tests**

Create `site/tests/__init__.py` (empty file).

Create `site/tests/test_generate_manifest.py`:

```python
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate_manifest  # noqa: E402


def _release(tag: str, assets: list[dict]) -> dict:
    return {"tag_name": tag, "assets": assets}


def _asset(name: str, url: str) -> dict:
    return {"name": name, "browser_download_url": url}


def _fake_response(payload: dict):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_build_manifest_filters_by_exact_show_regex():
    releases = [
        _release(
            "episode-2026-09-08",
            [_asset("episode_2026-09-08.mp3", "http://a"), _asset("transcript_2026-09-08.json", "http://t1")],
        ),
        _release(
            "episode-pm-2026-09-08",
            [_asset("episode_pm_2026-09-08.mp3", "http://b"), _asset("transcript_pm_2026-09-08.json", "http://t2")],
        ),
        _release("app-latest", [_asset("app.apk", "http://c")]),
    ]
    fake_transcript = {
        "date": "2026-09-08",
        "topics_covered": [{"topic": "Java", "sources": []}],
        "youtube_video_id": "vid1",
    }
    with patch("generate_manifest.requests.get", return_value=_fake_response(fake_transcript)):
        manifest = generate_manifest.build_manifest("tech", releases, token=None)

    assert len(manifest["episodes"]) == 1
    assert manifest["episodes"][0]["date"] == "2026-09-08"
    assert manifest["episodes"][0]["topics"] == ["Java"]
    assert manifest["episodes"][0]["video_id"] == "vid1"
    assert manifest["show_label"] == "Daily Tech Briefing"


def test_build_manifest_does_not_match_other_shows_tag():
    # Regression test for the specific bug this design deliberately avoids: a PM release
    # tag must never satisfy the tech show's filter (or vice versa).
    releases = [
        _release(
            "episode-pm-2026-09-08",
            [_asset("episode_pm_2026-09-08.mp3", "http://b"), _asset("transcript_pm_2026-09-08.json", "http://t2")],
        )
    ]

    manifest = generate_manifest.build_manifest("tech", releases, token=None)

    assert manifest["episodes"] == []


def test_build_episode_handles_missing_video_id():
    release = _release(
        "episode-2026-08-01",
        [_asset("episode_2026-08-01.mp3", "http://a"), _asset("transcript_2026-08-01.json", "http://t1")],
    )
    fake_transcript = {"date": "2026-08-01", "topics_covered": []}  # no youtube_video_id - older episode

    with patch("generate_manifest.requests.get", return_value=_fake_response(fake_transcript)):
        episode = generate_manifest.build_episode(release, token=None)

    assert episode["video_id"] is None


def test_build_episode_skips_release_missing_transcript_asset():
    release = _release("episode-2026-08-01", [_asset("episode_2026-08-01.mp3", "http://a")])

    episode = generate_manifest.build_episode(release, token=None)

    assert episode is None


def test_build_episode_skips_release_missing_audio_asset():
    release = _release("episode-2026-08-01", [_asset("transcript_2026-08-01.json", "http://t1")])

    episode = generate_manifest.build_episode(release, token=None)

    assert episode is None


def test_build_manifest_sorts_newest_first():
    releases = [
        _release(
            "episode-2026-09-01",
            [_asset("episode_2026-09-01.mp3", "http://a1"), _asset("transcript_2026-09-01.json", "http://t1")],
        ),
        _release(
            "episode-2026-09-05",
            [_asset("episode_2026-09-05.mp3", "http://a2"), _asset("transcript_2026-09-05.json", "http://t2")],
        ),
    ]
    responses = {
        "http://t1": {"date": "2026-09-01", "topics_covered": []},
        "http://t2": {"date": "2026-09-05", "topics_covered": []},
    }

    def fake_get(url, **kwargs):
        return _fake_response(responses[url])

    with patch("generate_manifest.requests.get", side_effect=fake_get):
        manifest = generate_manifest.build_manifest("tech", releases, token=None)

    assert [e["date"] for e in manifest["episodes"]] == ["2026-09-05", "2026-09-01"]


def test_find_asset_url_returns_none_when_no_match():
    release = _release("episode-2026-08-01", [_asset("other.txt", "http://x")])

    assert generate_manifest.find_asset_url(release, lambda n: n.endswith(".mp3")) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd site && python -m pytest tests/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generate_manifest'`.

- [ ] **Step 4: Write `site/generate_manifest.py`**

```python
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
import sys
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd site && python -m pytest tests/ -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add site/generate_manifest.py site/requirements.txt site/tests/
git commit -m "Add episode-website manifest generation script"
```

---

## Task 3: Static site (HTML/CSS/JS)

**Files:**
- Create: `site/public/index.html`
- Create: `site/public/style.css`
- Create: `site/public/app.js`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `site/public/data/tech.json`, `site/public/data/pm.json` (produced by Task 2's script at deploy time — not present in the repo; fetched at runtime by `app.js`).

- [ ] **Step 1: Add the generated-data directory to `.gitignore`**

Add this line to `.gitignore`, in the Python section (near `pipeline/data/`):
```
site/public/data/
```

- [ ] **Step 2: Create `site/public/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Daily Tech Briefing &amp; Project Manager's Room</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <header>
    <h1>Episodes</h1>
    <nav>
      <button id="tab-tech" class="tab-button active" data-show="tech">Tech Briefing</button>
      <button id="tab-pm" class="tab-button" data-show="pm">Project Manager's Room</button>
    </nav>
  </header>

  <main>
    <section id="section-tech" class="show-section"></section>
    <section id="section-pm" class="show-section" hidden></section>
  </main>

  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `site/public/app.js`**

```javascript
const SHOWS = ["tech", "pm"];

function buildEpisodeCard(episode) {
  const card = document.createElement("article");
  card.className = "episode-card";

  const heading = document.createElement("h2");
  heading.textContent = episode.date;
  card.appendChild(heading);

  if (episode.topics && episode.topics.length > 0) {
    const topics = document.createElement("p");
    topics.className = "topics";
    topics.textContent = episode.topics.join(", ");
    card.appendChild(topics);
  }

  const audio = document.createElement("audio");
  audio.controls = true;
  audio.src = episode.audio_url;
  card.appendChild(audio);

  if (episode.video_id) {
    const iframe = document.createElement("iframe");
    iframe.src = `https://www.youtube.com/embed/${episode.video_id}`;
    iframe.title = `${episode.date} video`;
    iframe.allowFullscreen = true;
    iframe.loading = "lazy";
    card.appendChild(iframe);
  }

  return card;
}

function renderEpisodes(section, manifest) {
  if (!manifest.episodes || manifest.episodes.length === 0) {
    section.innerHTML = '<p class="status">No episodes published yet.</p>';
    return;
  }
  section.innerHTML = "";
  for (const episode of manifest.episodes) {
    section.appendChild(buildEpisodeCard(episode));
  }
}

async function loadShow(showKey) {
  const section = document.getElementById(`section-${showKey}`);
  section.innerHTML = '<p class="status">Loading episodes…</p>';
  try {
    const response = await fetch(`data/${showKey}.json`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = await response.json();
    renderEpisodes(section, manifest);
  } catch (err) {
    section.innerHTML = `<p class="status error">Couldn't load episodes (${err.message}).</p>`;
  }
}

function switchTab(showKey) {
  for (const key of SHOWS) {
    document.getElementById(`section-${key}`).hidden = key !== showKey;
    document.getElementById(`tab-${key}`).classList.toggle("active", key === showKey);
  }
}

document.getElementById("tab-tech").addEventListener("click", () => switchTab("tech"));
document.getElementById("tab-pm").addEventListener("click", () => switchTab("pm"));

for (const key of SHOWS) {
  loadShow(key);
}
```

- [ ] **Step 4: Create `site/public/style.css`**

```css
:root {
  color-scheme: light dark;
  --accent: #4f7cff;
  --bg: #ffffff;
  --fg: #1a1a1a;
  --card-bg: #f5f6f8;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a;
    --fg: #f0f0f0;
    --card-bg: #1f2228;
  }
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--fg);
}

header {
  padding: 1.5rem 1rem 1rem;
  text-align: center;
}

h1 {
  margin: 0 0 1rem;
  font-size: 1.5rem;
}

nav {
  display: flex;
  justify-content: center;
  gap: 0.5rem;
}

.tab-button {
  padding: 0.6rem 1.2rem;
  border: 1px solid var(--accent);
  background: transparent;
  color: var(--accent);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.95rem;
}

.tab-button.active {
  background: var(--accent);
  color: white;
}

main {
  max-width: 720px;
  margin: 0 auto;
  padding: 1rem;
}

.episode-card {
  background: var(--card-bg);
  border-radius: 12px;
  padding: 1rem;
  margin-bottom: 1rem;
}

.episode-card h2 {
  margin: 0 0 0.4rem;
  font-size: 1.1rem;
}

.episode-card .topics {
  margin: 0 0 0.75rem;
  opacity: 0.8;
  font-size: 0.9rem;
}

.episode-card audio {
  width: 100%;
  margin-bottom: 0.75rem;
}

.episode-card iframe {
  width: 100%;
  aspect-ratio: 16 / 9;
  border: none;
  border-radius: 8px;
}

.status {
  text-align: center;
  opacity: 0.7;
}

.status.error {
  color: #d64545;
}
```

- [ ] **Step 5: Manually verify locally**

Run: `python site/generate_manifest.py` from the repo root with `GITHUB_TOKEN` unset (unauthenticated is fine for a one-off manual check, just slower/rate-limited) — this populates `site/public/data/tech.json` and `site/public/data/pm.json` from the real, already-published releases.
Then run: `cd site/public && python -m http.server 8000`, open `http://localhost:8000` in a browser. Confirm: both tabs switch correctly, tech episodes list with working audio players, at least the two episodes published after Task 1 landed show an embedded video (older ones show audio-only, no broken iframe), and the PM tab shows its one episode.

- [ ] **Step 6: Commit**

```bash
git add site/public/index.html site/public/app.js site/public/style.css .gitignore
git commit -m "Add the episode website's static HTML/CSS/JS"
```

---

## Task 4: Deployment workflow

**Files:**
- Create: `.github/workflows/deploy-site.yml`

**Interfaces:**
- Consumes: `site/generate_manifest.py`, `site/requirements.txt` (Task 2), `site/public/` (Task 3).

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/deploy-site.yml`:

```yaml
name: Deploy Episode Website

on:
  release:
    types: [published]
  workflow_dispatch: {}

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install manifest-generation deps
        run: pip install -r site/requirements.txt

      - name: Generate episode manifest
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python site/generate_manifest.py

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: site/public

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Validate the YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-site.yml')); print('valid')"`
Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-site.yml
git commit -m "Add GitHub Pages deployment workflow for the episode website"
```

---

## Task 5: Rollout (enable Pages, trigger first deploy)

This task is mostly manual/verification — no new files.

- [ ] **Step 1: Attempt to enable GitHub Pages via API**

Run: `gh api -X POST repos/Shahbazhk/daily-tech-briefing/pages -f build_type=workflow`
- If this succeeds (no error): Pages is now configured for Actions-based deployment. Continue to Step 3.
- If this fails with a permissions/scope error: the GitHub CLI token doesn't have the `admin:repo` scope needed to change Pages settings via API. Report this to the user and ask them to do it manually: repo **Settings → Pages → Build and deployment → Source: GitHub Actions**. Wait for their confirmation before continuing.

- [ ] **Step 2: If Step 1 needed the manual path, confirm it's done**

Run: `gh api repos/Shahbazhk/daily-tech-briefing/pages --jq '.build_type'`
Expected: `workflow`. If this errors with "Not Found", Pages still isn't enabled — do not proceed until it is.

- [ ] **Step 3: Trigger the first deploy manually**

Run: `gh workflow run deploy-site.yml`
Then watch it: `gh run watch <run-id> --exit-status` (get `<run-id>` from `gh run list --workflow=deploy-site.yml --limit 1`).
Expected: the run completes successfully.

- [ ] **Step 4: Verify the live site**

Run: `gh api repos/Shahbazhk/daily-tech-briefing/pages --jq '.html_url'` to get the live URL.
Fetch it (e.g. via a browser, or `curl`) and confirm the page loads, both tabs render episodes, and audio/video work as expected — same checks as Task 3 Step 5, but against the real deployed site instead of a local server.

- [ ] **Step 5: Report the live URL**

Tell the user the site's live URL and confirm the `release: published` trigger will keep it in sync automatically from here on — no further manual deploys needed unless the site's own code changes.
