# Daily YouTube video publishing — design

Status: approved (video style + auth approach), pending final spec review
Date: 2026-08-03

## 1. Goal

Extend the existing daily pipeline (collect → script → TTS → publish) so that,
in addition to the Android app episode, each day's episode is automatically
turned into a video and uploaded to the user's existing YouTube channel and
playlist — fully unattended, no manual step once set up. Same hard constraint
as the rest of the project: $0/month, open-weight/free tools only where a
choice exists.

## 2. Context (what already exists)

- `pipeline/run_pipeline.py` runs four stages in order: `collector/collect.py`
  → `scripting/generate_script.py` → `tts/synthesize.py` → `publish/publish.py`.
- `tts/synthesize.py` uses Kokoro-82M (`KPipeline`) to synthesize
  `pipeline/data/script_<date>.md` into `episode_<date>.mp3`. Kokoro's
  `pipeline(text, voice=...)` call is itself a generator that yields
  `(graphemes, phonemes, audio_chunk)` tuples in text order as it synthesizes
  — `synthesize.py` currently just concatenates the audio chunks.
- `publish/publish.py` uploads the MP3 + Firestore doc + FCM push to Firebase
  (falls back to a GitHub Release if Firebase isn't configured).
- The whole thing runs daily via `.github/workflows/daily-episode.yml` on a
  GitHub Actions schedule (public repo → unlimited free Actions minutes).
- User already has a YouTube channel and a playlist created for this content.

## 3. Chosen visual style

**Cover art + karaoke-style captions** (confirmed via mockup comparison):
a static branded cover image for the whole episode, with the script's actual
words displayed as captions synced to the narration underneath — not a
per-topic slide deck, not just a waveform.

Rejected alternatives:
- *Static cover + waveform only* — simpler, but the user wants readable
  content on screen, not just an audio-reactive visual.
- *Per-topic infographic slide deck* — higher production value but
  meaningfully more build/maintenance surface (per-segment layout, icon
  selection per topic, bullet extraction). Deferred; the caption approach can
  evolve toward this later without changing the underlying architecture.

## 4. New pipeline stage: video generation

New module: `pipeline/video/build_video.py`, runs after `tts/synthesize.py`
and before `publish/publish.py` in `run_pipeline.py`.

### 4.1 Caption timing (no new dependency)

Modify `tts/synthesize.py`'s Kokoro loop: as it iterates
`pipeline(text, voice=voice)`, record each chunk's text alongside a running
cumulative sample count (chunk length in samples / `SAMPLE_RATE`). This
produces a list of `(text, start_seconds, end_seconds)` caption cues for free,
exactly matching what was actually synthesized — no separate forced-alignment
or ASR tool needed, and no risk of drift between audio and captions. Written
to `pipeline/data/captions_<date>.json`.

### 4.2 Rendering

- One static cover-art background image (channel branding — logo/title
  treatment, built once and committed under `pipeline/video/assets/`, not
  regenerated daily).
- `ffmpeg`, using the caption cues, overlays the current caption text on the
  background for its `[start, end]` window (`drawtext` with `enable='between(t,start,end)'`
  per cue, or an equivalent generated filter script for the full cue list),
  composited with the episode's audio track.
- Output: `pipeline/data/video_<date>.mp4`, same duration as the audio
  episode. ffmpeg is already a pipeline dependency (used for MP3 conversion),
  so this adds no new system package.

## 5. Thumbnail generation

New module: `pipeline/video/thumbnail.py`, Pillow-based, templated (not AI
image generation — see trade-off below).

- Template chosen by that day's dominant topic (first entry in
  `topics_covered`), each topic mapped to an accent color, matching the
  existing `sources.yaml` topic list (Java, Spring Boot, Liferay DXP,
  Hibernate, Kafka, Redis, Docker, Microservices, Kubernetes, Jenkins, Git,
  Angular, Cloud, Architect's Corner).
- Overlays: date, and a short topic list, rendered as large legible text over
  the accent-colored template.
- Deterministic, instant, zero external calls, cannot rate-limit or fail
  unpredictably — appropriate for a fully unattended daily job. An AI-image
  approach (e.g. a free-tier hosted Stable Diffusion API) was considered and
  rejected for now: it adds latency, occasional bad/off-topic output, and a
  dependency on a hosted free tier whose terms could change — more novelty,
  materially less reliability for a job that must never need a human to
  notice and fix it. Can revisit later if visual variety becomes a priority.

## 6. Title / description / tags generation

New module `pipeline/video/metadata.py` that makes one additional Groq call
per day —
reusing the same free API/model already generating the script — given that
day's `topics_covered` and script text, producing:
- A short, specific title (not a fixed template).
- A description including: an episode summary, the topic list, and a fixed
  disclosure line stating the narration is AI-generated (Kokoro TTS) and
  content is aggregated from public sources (listed in the existing
  `sources.yaml`/transcript sourcing).
- A handful of relevant tags.

## 7. YouTube upload

New module: `pipeline/publish/youtube_publish.py`, using
`google-api-python-client` + `google-auth`.

### 7.1 One-time setup (manual, requires the user's Google login)

1. Create a Google Cloud project, enable the YouTube Data API v3.
2. Create OAuth 2.0 credentials (Desktop app type) → `client_id` +
   `client_secret`.
3. Run a short local consent-flow script once (provided as part of this
   work) to authorize against the user's YouTube channel and obtain a
   refresh token.
4. Store `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`,
   and `YOUTUBE_PLAYLIST_ID` as GitHub Actions secrets — same pattern as
   `GROQ_API_KEY`.

### 7.2 OAuth verification (per user decision — go through verification)

Unverified/"Testing" Google OAuth apps have refresh tokens that expire after
7 days, which would silently break unattended daily uploads. Per the user's
choice, this project will go through Google's (free) OAuth verification
process:
- Prepare a minimal privacy policy, app homepage reference, and scope
  justification for the `youtube.upload`/`youtube` scopes.
- User submits the verification request under their own Google account
  (cannot be done on their behalf).
- Turnaround is Google's, typically days to a few weeks; not something this
  project controls.
- **Interim behavior while verification is pending:** uploads keep working
  on the 7-day token. The workflow's YouTube-upload step will detect an
  auth failure (expired/revoked token) and log a clearly-flagged warning
  (distinct from ordinary step failures) so it's obvious a re-auth is needed,
  rather than uploads silently stopping with no signal.

### 7.3 Daily upload flow

1. `videos.insert` — uploads `video_<date>.mp4` with the generated title,
   description, tags, category (Science & Technology), visibility **Public**,
   and the "altered/synthetic content" disclosure flag set (per user's
   choice — required by YouTube policy for realistic AI-generated voice).
2. `thumbnails.set` — uploads the generated thumbnail for that video.
3. `playlistItems.insert` — adds the video to the existing configured
   playlist (`YOUTUBE_PLAYLIST_ID`).

### 7.4 Idempotency

Before uploading, check whether a video for that date already exists (e.g.
search the playlist for a title/date match). Re-running the workflow the
same day (as already happens during manual testing) must not create a
duplicate upload.

## 8. Error handling

The YouTube/video stage is additive and must never block the existing
Android-app delivery path. It runs as an independent stage after
`publish/publish.py`: if video rendering or YouTube upload fails, the error
is logged clearly, but the workflow's overall episode delivery (audio +
Firebase/Release) is unaffected. This mirrors the existing pattern where the
GitHub Release fallback step in `daily-episode.yml` runs independently of the
Firebase publish step.

## 9. Workflow changes

`.github/workflows/daily-episode.yml` and `pipeline/run_pipeline.py`:
- Two new stages added to `run_pipeline.py`'s existing stage-runner pattern,
  in order after `synthesize` and before `publish`: `build_video` (Section 4,
  producing `video_<date>.mp4` and `captions_<date>.json`) and, after
  `publish`, a new final stage `youtube_publish` (Sections 5–7: thumbnail +
  metadata + upload). Kept as its own stage after `publish` (not before) so
  the Firebase/Release publish that the Android app depends on always
  completes first, regardless of YouTube's outcome (Section 8).
- The workflow file itself only needs new `env:` secrets added (no new
  `run:` steps) plus one new system/Python dependency install (Pillow).
- New env secrets: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
  `YOUTUBE_REFRESH_TOKEN`, `YOUTUBE_PLAYLIST_ID`.
- No new system dependencies beyond what's already installed (ffmpeg,
  Pillow — Pillow is a new Python dependency, pure-Python/no system package).
- Expected added runtime: a few minutes for video rendering + upload, on top
  of the current ~7-minute run. Still comfortably free (public repo →
  unlimited Actions minutes).

## 10. Testing plan

Same live-test discipline used for the rest of this project:
1. Local dry run of `build_video.py` + `thumbnail.py` + `metadata.py` against
   an already-generated episode's artifacts, inspecting the output MP4/PNG
   directly.
2. One-time manual OAuth consent flow, run locally, to mint the refresh
   token and do one manual `youtube_publish.py` run end-to-end against the
   real channel/playlist — this is also the artifact needed for the
   verification submission's demo requirement.
3. Full `workflow_dispatch` run of the updated `daily-episode.yml` on the
   real repo, confirming: video renders, thumbnail generates, title/description
   look reasonable, video appears in the YouTube playlist with the disclosure
   flag set, and a same-day re-run doesn't duplicate the upload.
4. Only after a clean manual run, rely on the schedule.

## 11. Non-goals (this iteration)

- Per-topic infographic slide deck (Section 3's rejected alternative) —
  possible future iteration on top of the same caption-timing data.
- AI-generated thumbnail art.
- Multi-language / dubbed versions.
- Editing/trimming video content differently from the audio episode — video
  length always matches the audio episode length.
