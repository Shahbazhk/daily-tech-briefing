# Daily YouTube video publishing — design

Status: approved (video style, auth approach, content guardrails), pending final spec review
Date: 2026-08-03

## 1. Goal

Extend the existing daily pipeline (collect → script → TTS → publish) so that,
in addition to the Android app episode, each day's episode is automatically
turned into a video and uploaded to the user's existing YouTube channel and
playlist — fully unattended, no manual step once set up. Same hard constraint
as the rest of the project: $0/month, open-weight/free tools only where a
choice exists. Also adds content safety guardrails to the underlying script
generation, since this content is now going out unattended on a public
platform with its own content policy, not just a personal phone.

## 2. Context (what already exists)

- `pipeline/run_pipeline.py` runs four stages in order: `collector/collect.py`
  → `scripting/generate_script.py` → `tts/synthesize.py` → `publish/publish.py`.
- `scripting/generate_script.py` generates the episode script as one Groq
  call per topic segment (plus one for "The Architect's Corner"), each with
  its own system prompt and a retry-once-if-too-short pattern
  (`SEGMENT_RETRY_THRESHOLD`).
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

## 3. Content safety guardrails

Applies to the existing `scripting/generate_script.py` stage, gating both
the app publish path and the new YouTube publish path — this is upstream of
both, so neither can ship content that fails the guardrail.

### 3.1 Prompt-level instructions

Every script-generation system prompt (the per-topic segment prompt and
`ARCHITECTURE_SYSTEM_PROMPT`) gets an added explicit rule set: no vulgarity
or profanity, and no presenting unethical examples/use-cases or projects
(e.g. surveillance abuse, exploit/attack tooling, privacy-violating scraping,
discriminatory systems) as case studies to emulate. This is the first line
of defense but not sufficient alone, since LLM instruction-following isn't
guaranteed.

### 3.2 Automated safety-net check

After each segment is generated (topic segments and the Architecture's
Corner segment alike), one additional Groq call classifies that segment's
text as `SAFE` or `FLAGGED: <one-line reason>` against the same rules
(vulgarity, unethical use-cases/projects). This runs per-segment, in the
same loop that already generates each segment, so a flag can be resolved
without discarding the whole episode.

### 3.3 On flag: retry once, then skip the day

If a segment comes back `FLAGGED`, regenerate that one segment once with a
stricter reminder appended to its prompt (mirrors the existing
retry-once-if-too-short pattern) and re-run the safety check on the retry.
If still `FLAGGED`, the pipeline does not write `script_<date>.md` and logs
a clearly-labeled error explaining which segment/topic was flagged and why.

No new "skip" signaling mechanism is needed: every downstream stage already
hard-requires `script_<date>.md` to exist (`tts/synthesize.py` already raises
`SystemExit` if it's missing) — so a withheld script file naturally halts
the rest of that day's pipeline, for both the app and YouTube paths. The
distinct, clearly-labeled log line is what makes this diagnosable as "a
safety check blocked publish" rather than looking like an unrelated bug.

### 3.4 Cost/scope note

Adds up to one extra Groq call per segment (~13 topics + 1 Architecture's
Corner ⇒ up to 14 calls/day), on top of the generation calls already made —
trivial for Groq's free tier at this volume. Title/description/tags
(Section 6) are generated from already-approved script text, so they don't
need their own separate safety check.

## 4. Chosen visual style

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

## 5. New pipeline stage: video generation

New module: `pipeline/video/build_video.py`, runs after `tts/synthesize.py`
and before `publish/publish.py` in `run_pipeline.py`.

### 5.1 Caption timing (no new dependency)

Modify `tts/synthesize.py`'s Kokoro loop: as it iterates
`pipeline(text, voice=voice)`, record each chunk's text alongside a running
cumulative sample count (chunk length in samples / `SAMPLE_RATE`). This
produces a list of `(text, start_seconds, end_seconds)` caption cues for free,
exactly matching what was actually synthesized — no separate forced-alignment
or ASR tool needed, and no risk of drift between audio and captions. Written
to `pipeline/data/captions_<date>.json`.

### 5.2 Rendering

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

## 6. Thumbnail generation

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

## 7. Title / description / tags generation

New module `pipeline/video/metadata.py` that makes one additional Groq call
per day — reusing the same free API/model already generating the script —
given that day's `topics_covered` and (safety-approved, per Section 3)
script text, producing:
- A short, specific title (not a fixed template).
- A description including: an episode summary, the topic list, and a fixed
  disclosure line stating the narration is AI-generated (Kokoro TTS) and
  content is aggregated from public sources (listed in the existing
  `sources.yaml`/transcript sourcing).
- A handful of relevant tags.

## 8. YouTube upload

New module: `pipeline/publish/youtube_publish.py`, using
`google-api-python-client` + `google-auth`.

### 8.1 One-time setup (manual, requires the user's Google login)

1. Create a Google Cloud project, enable the YouTube Data API v3.
2. Create OAuth 2.0 credentials (Desktop app type) → `client_id` +
   `client_secret`.
3. Run a short local consent-flow script once (provided as part of this
   work) to authorize against the user's YouTube channel and obtain a
   refresh token.
4. Store `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`,
   and `YOUTUBE_PLAYLIST_ID` as GitHub Actions secrets — same pattern as
   `GROQ_API_KEY`.

### 8.2 OAuth verification (per user decision — go through verification)

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

### 8.3 Daily upload flow

1. `videos.insert` — uploads `video_<date>.mp4` with the generated title,
   description, tags, category (Science & Technology), visibility **Public**,
   and the "altered/synthetic content" disclosure flag set (per user's
   choice — required by YouTube policy for realistic AI-generated voice).
2. `thumbnails.set` — uploads the generated thumbnail for that video.
3. `playlistItems.insert` — adds the video to the existing configured
   playlist (`YOUTUBE_PLAYLIST_ID`).

### 8.4 Idempotency

Before uploading, check whether a video for that date already exists.
Live testing during implementation proved that matching the date against
the video *title* doesn't work: LLM-generated titles ("Aug 4: Java, Kafka,
Docker") don't reliably contain the ISO date, so a title/date search
silently fails to find the existing video and re-uploads a duplicate. The
implementation instead embeds a code-controlled marker
(`[Episode date: YYYY-MM-DD]`) in the video *description* at upload time,
and checks the playlist's descriptions for that exact marker. Re-running the
workflow the same day (as already happens during manual testing) must not
create a duplicate upload.

## 9. Error handling

The YouTube/video stage is additive and must never block the existing
Android-app delivery path. It runs as an independent stage after
`publish/publish.py`: if video rendering or YouTube upload fails, the error
is logged clearly, but the workflow's overall episode delivery (audio +
Firebase/Release) is unaffected. This mirrors the existing pattern where the
GitHub Release fallback step in `daily-episode.yml` runs independently of the
Firebase publish step. The content-safety guardrail (Section 3) is the one
exception that blocks everything, by design — it gates the script before
either delivery path has anything to publish.

## 10. Workflow changes

`.github/workflows/daily-episode.yml` and `pipeline/run_pipeline.py`:
- Two new stages added to `run_pipeline.py`'s existing stage-runner pattern,
  in order after `synthesize` and before `publish`: `build_video` (Section 5,
  producing `video_<date>.mp4` and `captions_<date>.json`) and, after
  `publish`, a new final stage `youtube_publish` (Sections 6–8: thumbnail +
  metadata + upload). Kept as its own stage after `publish` (not before) so
  the Firebase/Release publish that the Android app depends on always
  completes first, regardless of YouTube's outcome (Section 9).
- `scripting/generate_script.py` changes in place (Section 3's guardrails) —
  no new stage, since it's part of the existing script-generation stage.
- The workflow file itself only needs new `env:` secrets added (no new
  `run:` steps) plus one new system/Python dependency install (Pillow).
- New env secrets: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
  `YOUTUBE_REFRESH_TOKEN`, `YOUTUBE_PLAYLIST_ID`.
- No new system dependencies beyond what's already installed (ffmpeg,
  Pillow — Pillow is a new Python dependency, pure-Python/no system package).
- Expected added runtime: a few minutes for video rendering + upload, on top
  of the current ~7-minute run. Still comfortably free (public repo →
  unlimited Actions minutes).

## 11. Testing plan

Same live-test discipline used for the rest of this project:
1. Local dry run of `build_video.py` + `thumbnail.py` + `metadata.py` against
   an already-generated episode's artifacts, inspecting the output MP4/PNG
   directly.
2. Local test of the safety-check guardrail (Section 3) against both a
   normal segment (expect `SAFE`) and a deliberately adversarial test prompt
   (expect `FLAGGED`, and confirm the retry-then-skip behavior actually
   withholds `script_<date>.md`).
3. One-time manual OAuth consent flow, run locally, to mint the refresh
   token and do one manual `youtube_publish.py` run end-to-end against the
   real channel/playlist — this is also the artifact needed for the
   verification submission's demo requirement.
4. Full `workflow_dispatch` run of the updated `daily-episode.yml` on the
   real repo, confirming: video renders, thumbnail generates, title/description
   look reasonable, video appears in the YouTube playlist with the disclosure
   flag set, and a same-day re-run doesn't duplicate the upload.
5. Only after a clean manual run, rely on the schedule.

## 12. Non-goals (this iteration)

- Per-topic infographic slide deck (Section 4's rejected alternative) —
  possible future iteration on top of the same caption-timing data.
- AI-generated thumbnail art.
- Multi-language / dubbed versions.
- Editing/trimming video content differently from the audio episode — video
  length always matches the audio episode length.
- Retroactively re-checking already-published past episodes against the new
  guardrails (Section 3 only applies going forward).
