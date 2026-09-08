# Design: "Project Manager's Room" — a second daily show (PM/Delivery)

Date: 2026-09-08

## Overview

A second, independent daily podcast/video show alongside the existing tech
briefing: **"Project Manager's Room"**, ~10 minutes, aimed at an IT
Project/Delivery Manager audience. Same pipeline architecture, same YouTube
channel (new playlist), published to a separate GitHub Actions schedule, and
surfaced in the Android app via a show toggle. The video link is intended to
be shared manually to LinkedIn (not automated — no LinkedIn integration
exists or is in scope here).

## Goals

- Produce a second ~10-minute show daily: 5 min latest PM/delivery updates,
  2 min deep-dive on the day's biggest item, 3 min fictional/illustrative
  story segment.
- Publish it through the same mechanical pipeline (collect → script →
  synthesize → build video → publish → YouTube) without duplicating that
  plumbing.
- Surface it in the Android app alongside the existing tech show.

## Non-goals

- No LinkedIn posting automation (manual sharing, out of scope).
- No new Firestore/FCM push-notification infrastructure — master's Android
  app doesn't use Firestore/push yet for the tech show either (there's an
  existing TODO for that migration); the PM show rides along whenever that
  happens, not before.
- No new YouTube channel — same channel, new playlist.
- No dedicated cover-art/visual-identity design pass now — reuses the
  existing thumbnail/cover generation code with a different title/voice;
  visual polish can be iterated once real thumbnails exist.

## Show manifest

One plain dict in `pipeline/common.py` (no new class — two entries, accessed
by key, doesn't earn a dataclass):

```python
SHOWS = {
    "tech": {
        "sources_path": CONFIG_PATH,  # existing pipeline/config/sources.yaml
        "file_stub": "episode",       # unsuffixed — backward compatible with published episodes
        "script_module": "scripting.generate_script",
        "firestore_collection": "episodes",
        "release_tag_prefix": "episode",
        "youtube_playlist_env": "YOUTUBE_PLAYLIST_ID",
        "youtube_category_id": "28",  # Science & Technology
    },
    "pm": {
        "sources_path": PIPELINE_ROOT / "config" / "sources_pm.yaml",
        "file_stub": "episode_pm",
        "script_module": "scripting.generate_script_pm",
        "firestore_collection": "episodes_pm",
        "release_tag_prefix": "episode-pm",
        "youtube_playlist_env": "YOUTUBE_PM_PLAYLIST_ID",
        "youtube_category_id": "27",  # Education
    },
}
```

`run_pipeline.py` gets a `--show {tech,pm}` flag (default `tech`, so the
existing workflow/behavior is unchanged) and sets `PIPELINE_SHOW` in the
process environment; each stage reads it via a `current_show()` helper in
`common.py` that returns the dict above.

## Pipeline stages

**Shared, parameterized (no duplication):** `collector/collect.py`,
`tts/synthesize.py`, `video/build_video.py`, `publish/publish.py`,
`publish/youtube_publish.py`. Each resolves its config path / filename stub /
Firestore collection / playlist env var / category id from `current_show()`
instead of hardcoded constants. This is a mechanical find-and-replace of
constants, not new logic.

**Per-show (genuinely different content):** `run_pipeline.py` dispatches the
`generate_script` stage to either `scripting/generate_script.py` (existing,
untouched) or the new `scripting/generate_script_pm.py`, per the manifest's
`script_module`.

**Voice:** no code change — `synthesize.py` already reads `KOKORO_VOICE` from
the environment. The PM workflow sets `KOKORO_VOICE=am_michael` as a job env
var (distinct from the tech show's default `af_heart`).

**Shared refactor:** `check_segment_safety` / `ContentSafetyError` /
`SAFETY_SYSTEM_PROMPT`, currently defined in `scripting/generate_script.py`,
move to `common.py` — both script generators import the same implementation
rather than duplicating a safety check. This is reuse (rung 2), not a new
abstraction.

## `generate_script_pm.py`

Total ~10 min ≈ 1,500 words at the existing 150 wpm convention, three
Groq-driven segments (same "one segment per call with its own word budget"
pattern as the tech show — a single big prompt was already shown to
undershoot in this repo's testing):

1. **Latest updates (~5 min / ~750 words).** One call per PM sub-topic
   (Agile/Scrum delivery, Risk & Stakeholder Management, PMI/PMBOK &
   certification news, Hybrid/Remote delivery, PM tooling), word budget
   allocated proportionally to collected-item count, band 100–250
   words/topic (reuses `allocate_word_budgets` from `generate_script.py`,
   imported not copied).
2. **Deep dive (~2 min / ~300 words).** No extra LLM call for selection:
   pick the sub-topic with the most collected items that day, and its
   longest/most detailed item as the anchor. Own system prompt: go deeper on
   implications for a working delivery manager, same "don't invent facts"
   rule as the roundup segment.
3. **Story segment (~3 min / ~450 words).** Fictional/illustrative — its own
   system prompt that explicitly *permits* invention (the one deliberate
   exception to the "never invent facts" rule elsewhere in this codebase),
   themed by a fixed list cycled deterministically by day-of-year
   (`THEMES[date.timetuple().tm_yday % len(THEMES)]` — no saved state
   needed):
   `["scope creep", "stakeholder conflict", "vendor/dependency risk",
   "distributed-team friction", "burnout and crunch", "agile vs. waterfall
   tension", "scope negotiation", "communication breakdown"]`.
   Hard rule in the prompt: **no real company or person names** — fictional
   characters/organizations only. A templated (non-LLM) transition line
   introduces it explicitly as a story
   (`"Now, a quick scenario — a fictional situation to bring today's theme
   to life."`), so the fictional framing is deterministic, not left to the
   model to remember.

All three segments run through the shared `check_segment_safety` check
(including the "no real names" constraint being reinforced there for the
story segment specifically).

## `pipeline/config/sources_pm.yaml`

Same shape as `sources.yaml` (topic → rss/reddit_subs/hn_query). Reddit
(`r/projectmanagement`, `r/agile`, `r/pmp`, `r/scrum`) and HN queries are
used as the reliable defaults (same mechanism already proven for the tech
show). RSS entries for PMI's blog, Agile Alliance, and Scrum.org are included
as **unverified best-effort URLs** — attempted verification during this
design session was inconclusive (Agile Alliance and Scrum.org didn't resolve
to parseable feed XML via fetch; PMI blocked the fetch with a 403, most
likely bot-blocking rather than a real paywall) — same "collector skips a
broken URL and logs it, doesn't fail the run" tolerance the existing file
already documents. **Action for you before the first real run:** open each
candidate blog in a browser and confirm/replace the RSS URL.

No PMI login/credentials are used anywhere in this pipeline — confirmed out
of scope in this design session (security and PMI ToS risk for an unattended
CI pipeline; the PMI blog itself is public marketing content, not
member-gated).

## Publish targets

- **Firebase (if configured):** `publish.py` writes to `episodes_pm`
  collection (doc id = date), storage path `episodes_pm/episode_pm_<date>.mp3`,
  and sends to FCM topic `daily_pm_episode` — same code path as today,
  parameterized. The app doesn't consume any of this yet (see Non-goals);
  writing it now avoids a rework when the Firestore migration eventually
  happens.
- **YouTube:** same channel, new playlist via `YOUTUBE_PM_PLAYLIST_ID` (new
  secret, reuses existing `YOUTUBE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN`).
  Category id `27` (Education). Idempotency check (`video_already_uploaded`)
  already scopes by `playlist_id`, so no collision with the tech playlist —
  no change needed there.
- **GitHub Release fallback:** new workflow's own step, tag
  `episode-pm-$DATE`, assets `episode_pm_*.mp3` / `transcript_pm_*.json`.

## Required fix: Android release-tag filtering

`EpisodeRepository.kt`'s current filter
(`tag_name.startsWith("episode-")`) would incorrectly also match a new
`episode-pm-2026-09-08` tag. Must tighten to an exact-date match before the
PM show's first release: tech matches
`^episode-\d{4}-\d{2}-\d{2}$`, PM matches `^episode-pm-\d{4}-\d{2}-\d{2}$`.
This is a latent bug this feature surfaces, not new complexity — one regex
change.

## Android app

- `EpisodeRepository` takes a small `show` parameter (release-tag-prefix
  regex + display name) instead of the hardcoded prefix — same class, one
  constructor parameter, not a new hierarchy.
- `MainActivity` gets a two-button toggle ("Tech Briefing" / "Project
  Manager's Room") above the existing player UI; switching re-points the
  same `loadTodayEpisode()`-style call at the other show's repository. No
  new architecture layer — the existing code is a plain `Activity` with
  direct `lifecycleScope` calls, so the new code matches that, not a
  ViewModel/LiveData layer this app doesn't otherwise use.
- No Firestore, no push-notification work (see Non-goals).

## Workflow

New `.github/workflows/daily-pm-episode.yml`, copied from the existing
`daily-episode.yml` pattern (own file, not a matrix — the schedules
genuinely differ, and GitHub Actions matrix jobs share one trigger time,
which doesn't fit): `python pipeline/run_pipeline.py --show pm`, cron
`0 9 * * *` (09:00 UTC ≈ 12:00 PM AST) — several hours after the tech show's
00:00 UTC run, landing as a distinct midday touchpoint and avoiding
scheduler/Groq-rate-limit contention between the two jobs. Reuses existing
`GROQ_API_KEY`/Reddit/Firebase secrets; one new secret,
`YOUTUBE_PM_PLAYLIST_ID`.

## Testing

Following the existing `pipeline/tests/` pytest convention:
- `test_generate_script_pm_safety.py` — the fictional-story segment's safety
  check and "no real names" rule (mirrors `test_generate_script_safety.py`).
- Extend `test_run_pipeline.py`'s style to cover the `--show` dispatch
  picking the right script module and file stub.
- No Android test suite exists to extend (skeleton app has none today).

## Risks carried over from earlier discussion (still relevant, now scoped)

- RSS source URLs for PM content are unverified — flagged above, action
  needed before first run.
- Doubling Groq/TTS/Actions-minutes usage — mitigated by staggering the
  schedule (09:00 UTC vs 00:00 UTC) rather than running both in one job.
- YouTube OAuth app is still in Google's "Testing" tier (7-day token expiry)
  per the existing README — unchanged by this feature, but the PM show adds
  a second upload target sharing that same unresolved risk.
