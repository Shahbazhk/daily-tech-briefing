# Business Requirements Document (BRD)
## Project: Shahbaz Daily Updates — Tech News Podcast App

| Field | Value |
|---|---|
| Document Owner | Shahbaz |
| Status | Draft v0.1 |
| Last Updated | 2026-08-03 |
| Platform | Android (v1) |

---

## 1. Executive Summary

An Android application that automatically aggregates the last 24 hours of technical news, updates, and community discussion across a defined set of backend/DevOps technologies, and converts it into a single ~20-minute, easy-to-understand English audio podcast, delivered/ready every day at **8:00 AM Saudi Arabia Time (AST, UTC+3)**. The goal is to let the user stay current on the technologies they use professionally without spending time manually reading blogs, release notes, and forums.

## 2. Problem Statement

The user works across a broad backend/DevOps stack (Java, Spring Boot, Liferay, Hibernate, Kafka, Redis, Docker, Microservices, Kubernetes, Jenkins, Git, Cloud, etc.) and wants to stay up to date daily, but:
- Tracking updates across 10+ ecosystems individually is time-consuming.
- Most release notes / blog posts are dense, long, and not written for quick consumption.
- There's no single place that summarizes "what changed, who's using it, what broke, and how it was fixed" across all of these topics together.

## 3. Objectives (V1)

1. Every day, generate one audio podcast episode (~18–22 minutes on a typical news day) summarizing the prior 24 hours of notable activity across the tracked technologies. **Decision (2026-08-02, confirmed after live testing): episode length is allowed to vary with real news volume** — the pipeline must never pad with invented or tangential content just to hit a target runtime. A quiet day producing a 9-minute episode is correct behavior, not a bug.
2. Episode must be ready and available in the app by 8:00 AM AST daily.
3. Content must be in **simple, conversational English** — understandable without deep prior context, but still technically accurate.
4. Content should highlight, where available:
   - What changed / what's new (releases, CVEs, major discussions).
   - Which companies/organizations are using or adopting the technology in the news item.
   - Notable issues/incidents raised and how they were resolved (postmortems, bug fixes, patches).
5. App must let the user play, pause, seek, and review past episodes (archive).
6. Architecture should be extensible to support **multiple daily podcasts** later (e.g., split by topic, or a second episode at a different time).

## 4. Target User / Persona

- **Primary user (v1):** Shahbaz — a backend/full-stack engineer working with Java/Spring/Liferay-type enterprise stacks, who wants a daily audio digest instead of reading multiple sites.
- Single-user app for v1 (no multi-tenant/account system required initially), but design should not hard-block adding users later.

## 5. Scope

### 5.1 In Scope (V1)
- Automated content collection for the topic list in Section 7, once per day, covering a trailing 24-hour window.
- Summarization/scripting of collected content into a single narrated episode script.
- Text-to-speech (TTS) generation of that script into an audio file in simple, natural English.
- Android app to:
  - Notify/present the new episode at 8:00 AM AST.
  - Play the episode with standard audio controls.
  - Show an episode archive (past days) with the text transcript/show notes.
  - Basic topic on/off preferences (e.g., mute "Liferay" if not relevant that week).
- Scheduling/backend job that runs the pipeline daily in time for the 8 AM AST deadline.

### 5.2 Out of Scope (V1 — candidates for later phases)
- iOS app.
- Multiple daily episodes / topic-specific mini-episodes (planned for Phase 2, see Section 14).
- Multi-language support (Arabic, Hindi, etc.).
- Multi-user accounts, auth, and personalized feeds per user.
- Interactive/conversational Q&A about the news (chat with the episode).
- Community features (comments, sharing, ratings).
- Advanced voice styles (multiple hosts/dialogue-style podcast) — v1 is single-narrator.

## 6. High-Level Solution Overview

Pipeline (runs daily, unattended, timed to finish before 8:00 AM AST):

1. **Collect** — Pull updates from the last 24 hours from a curated set of sources per topic (official blogs/release notes, RSS feeds, GitHub releases, Q&A/forum highlights, status pages/incident reports, relevant news aggregators).
2. **Filter & Rank** — Deduplicate, filter noise, and rank items by relevance/significance per topic so the episode stays within ~20 minutes of spoken content (~2,600–3,000 words).
3. **Summarize & Script** — Use an LLM to turn raw items into a single cohesive, simple-English narration script, organized by topic, including "what happened," "who's using/affected," and "issue → resolution" where applicable.
4. **Narrate (TTS)** — Convert the script to an audio file (single narrator voice, natural pacing, ~20 minutes).
5. **Publish** — Store the audio + transcript + metadata (date, topics covered, source links) so the Android app can fetch/cache it before 8:00 AM AST.
6. **Deliver** — Android app surfaces a notification ("Your tech briefing is ready") and shows the episode in the home/player screen.

```
[Source Feeds] -> [Collector Job] -> [Filter/Rank] -> [LLM Script Writer]
     -> [TTS Engine] -> [Episode Storage (audio+transcript+metadata)]
     -> [Android App: fetch, cache, notify, play]
```

## 7. Content Topics (V1 tracked list)

Java, Spring Boot, **Liferay DXP** (Digital Experience Platform — the enterprise Java portal
framework specifically, not to be confused with anything else of a similar name), Hibernate,
Kafka, Redis, Docker, Microservices, Kubernetes, Jenkins, Git, **Angular** (front-end framework,
added 2026-08-02 — commonly paired with the Java/Spring Boot/Liferay DXP stack above in
enterprise projects), Cloud (AWS/Azure/GCP general), and an extensible "etc." category for
adjacent tools the user may add later (e.g., Maven, RabbitMQ, Elasticsearch, CI/CD tooling,
security/CVE alerts relevant to the above).

> Topic list must be config-driven (not hardcoded), so topics can be added/removed/reordered without code changes.

> Since 2026-08-03, script generation is gated by a content-safety guardrail (no vulgarity/
> profanity, no unethical use-cases/projects presented as case studies to emulate) — a
> prompt-level instruction backed by a per-segment automated check, since this content now
> publishes unattended to YouTube in addition to the personal app. A segment that's still
> flagged after one retry withholds that day's script entirely rather than publish it; see
> Section 14.9.

## 8. Functional Requirements

| ID | Requirement |
|---|---|
| FR-1 | System shall collect content published within the trailing 24 hours for each configured topic. |
| FR-2 | System shall deduplicate and rank items, dropping low-signal/noise items to fit the target runtime. |
| FR-3 | System shall generate a single narration script per day covering all topics with meaningful updates that day (topics with no news are skipped or briefly noted). |
| FR-4 | Script tone shall be simple, conversational English suitable for audio consumption — no dense jargon without a quick explanation. |
| FR-5 | Where applicable, script shall mention: what changed, example companies/projects using the tech, and any issue + how it was resolved. |
| FR-6 | System shall convert the script into an audio file. Runtime targets ~18–22 minutes on a typical news day but is allowed to run shorter on quiet days rather than pad with invented content (see Section 3, Objective 1). |
| FR-7 | The daily episode (audio + transcript) shall be available to the Android app no later than 8:00 AM AST. |
| FR-8 | Android app shall notify the user when the new episode is ready. |
| FR-9 | Android app shall support play/pause/seek/skip-forward/skip-back and playback speed control. |
| FR-10 | Android app shall maintain an archive of past episodes with date, topics covered, and transcript/show notes. |
| FR-11 | Android app shall allow offline playback of already-downloaded episodes. |
| FR-12 | Android app shall allow the user to enable/disable specific topics from being included in future episodes. |
| FR-13 | Each episode's transcript shall include source links/citations for claims made, for user follow-up/verification. |
| FR-14 | System shall log pipeline run status (success/failure per stage) for troubleshooting. |

## 9. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Reliability | Daily pipeline must complete before 8:00 AM AST with a defined buffer (e.g., start by 6:00 AM AST); alert on failure/fallback to prior episode. |
| Timezone handling | All scheduling logic anchored to AST (UTC+3), independent of device locale/timezone. |
| Performance | Episode audio should stream/start playing within a few seconds in-app; full episode pre-downloadable. |
| Accuracy | Summaries must not fabricate facts; every notable claim should be traceable to a source link. |
| Cost | **Target $0/month.** Pipeline must run entirely on free tiers and/or self-hosted open-source tools — see Section 14 for the confirmed stack. |
| Compliance | Content collection must respect source sites' Terms of Service / robots.txt; prefer official APIs/RSS over scraping where available. |
| Privacy | Single-user app in v1; no unnecessary personal data collected. |
| Scalability | Architecture should allow adding more topics or a second daily episode without redesign. |
| Storage | Retain episode archive (audio + transcript) for a defined retention period (TBD, e.g., 90 days) to manage storage cost. |

## 10. Candidate Content Sources (per topic, to be finalized)

- Official release notes / changelogs / blogs (e.g., Spring blog, Apache Kafka releases, Redis release notes, Kubernetes release/blog, Docker blog, Jenkins changelog, Liferay community/blog, Hibernate release notes, GitHub blog/changelog).
- GitHub Releases/Tags API for each project's core repo (structured, reliable, avoids scraping).
- RSS/Atom feeds where available (most of the above provide one).
- Community signal: Hacker News, Reddit (r/java, r/kubernetes, r/devops, etc.), Stack Overflow trending tags — used for "what's the buzz/issues" angle.
- Cloud provider status pages / incident postmortems (AWS/Azure/GCP) for outage-and-resolution stories.
- CVE/security advisories relevant to the tracked stack (e.g., GitHub Security Advisories).

> Preference order: **official API/RSS/GitHub API first**, generic web scraping only as a fallback where no structured source exists — this reduces breakage risk and ToS concerns.

## 11. Podcast Script Structure (per episode)

1. Intro (date, what's covered today) — ~15–20 sec.
2. Per-topic segments (only topics with real news that day), each covering:
   - What happened (release, update, incident, notable discussion).
   - Why it matters in plain English.
   - Who's using/affected (companies, notable projects) — when available.
   - Issue → root cause → resolution (when the story is about a bug/incident).
3. **The Architect's Corner** (added 2026-08-02) — a fixed ~5-minute recurring segment,
   independent of the topics above, aimed specifically at software-architecture/system-design
   growth for someone doing architect-level work on enterprise projects. Format: one real
   problem an engineering team faced → the solution they built → why it matters (trade-offs,
   when the pattern applies elsewhere). Sourced from real engineering blogs (Netflix, Uber, AWS
   Architecture, Martin Fowler, High Scalability, etc.) — never an invented case study. Since
   these blogs post far less often than the daily-release topics above, this segment uses its
   own ~7-day lookback rather than 24 hours, so there's usually real material even though the
   segment airs daily.
4. Outro (recap + sign-off).

Target length: ~2,600–3,000 spoken words for ~18–22 minutes at natural narration pace on a
typical news day (Architect's Corner accounts for ~720 words / ~5 min of that). Per the
2026-08-02 decision in Section 3, this varies honestly with real news/case-study volume rather
than being padded to a fixed number — including the Architect's Corner itself: if nothing
substantive turns up even in its wider lookback window, it's skipped that day rather than
inventing a case study.

## 12. Android App — Screens (V1)

- **Home / Today:** today's episode, play button, short written summary, topics covered as chips.
- **Player:** playback controls, transcript scroll-with-audio (optional), source links.
- **Archive:** list of past episodes by date, searchable/filterable by topic.
- **Settings:** topic toggles, notification time confirmation (fixed 8 AM AST for v1), download/offline preferences.

## 13. Assumptions

- User has one primary timezone context (AST) even if physically elsewhere; 8 AM AST is a fixed target, not device-local.
- A backend/cloud component is required (the pipeline cannot realistically run entirely on-device given scraping + LLM + TTS needs); the Android app is a client to this backend.
- Single narrator voice is acceptable for v1 (no multi-voice dialogue format).
- English-only content is acceptable for v1.

## 14. Confirmed Free & Open-Source Technology Stack

Decision made 2026-08-02: pipeline runs on **free cloud automation** (not the user's own PC), and the AI writing step uses **strictly open-weight models** (Llama / Mixtral / Gemma / Qwen family), accessed via a free-tier API rather than a paid one. Every component below is $0/month at this project's scale (single user, one ~20-minute episode/day).

### 14.1 Content Collection — free, no scraping-ToS risk
| Source type | Tool | Notes |
|---|---|---|
| Official blogs/release notes | RSS/Atom via `feedparser` (Python) | Spring, Kubernetes, Docker, Redis, Apache Kafka, Jenkins, Hibernate, Git, most cloud provider blogs all publish free RSS. |
| GitHub releases/tags | GitHub REST API | Free with a personal access token (5,000 req/hour). Track repos like `spring-projects/spring-boot`, `apache/kafka`, `redis/redis`, `kubernetes/kubernetes`, `jenkinsci/jenkins`, `hibernate/hibernate-orm`. |
| Community buzz / "issues & fixes" angle | Hacker News (Algolia HN Search API, free, no key) + Reddit API via `PRAW` (free app registration) | Used for r/java, r/kubernetes, r/devops, r/docker etc. |
| Security advisories | GitHub Security Advisories API (free) | Flags CVEs relevant to tracked stack. |

### 14.2 AI Summarization / Script Writing — open-weight models, free tier
- **Primary: [Groq Cloud](https://console.groq.com)** — free API key, no credit card required. Serves genuinely open-weight models at very high speed:
  - `llama-3.3-70b-versatile` (Meta, open weight) — best quality, used for the main script write-up.
  - `gemma2-9b-it` (Google, open weight) or `mixtral-8x7b` (Mistral, open weight) as fallback/alternate.
  - Free tier gives generous daily/per-minute request and token limits — more than enough for one generation job per day.
- **Fallback option: [OpenRouter](https://openrouter.ai)** free-tier open models (e.g. free Llama/Qwen/DeepSeek variants) in case Groq has an outage or rate-limit hiccup on a given day.
- Both keep us strictly within "open-weight model" scope — the *model* is open source (Meta/Mistral/Google/Qwen), only the *inference hosting* is a free hosted API rather than your own GPU.

### 14.3 Text-to-Speech — fully open-source, runs inside the same job
- **[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** — open-weight (Apache-2.0) neural TTS, runs on CPU (no GPU needed), fast enough to render a full episode well within a CI job's time budget. Runs *locally inside the automation job itself*, so this stage makes zero external calls. Switched from Piper TTS on 2026-08-03 — same open-weight/self-hosted/zero-cost constraints, but noticeably more natural prosody and intonation; Piper's voice was reported as sounding too artificial.
- Voice: `af_heart` (Kokoro's flagship American-English voice). Full voice list is itself open and freely downloadable.

### 14.4 Orchestration & Scheduling — free
- **GitHub Actions** scheduled workflow (`on: schedule: cron:`), triggered at **00:00 UTC = 03:00 AM AST** — a 5-hour buffer before the 08:00 AM AST deadline (widened from 2 hours on 2026-08-03 after a scheduled run fired 3h27m late — GitHub's `schedule` trigger is best-effort and can be delayed under load).
- Public repos get unlimited free Actions minutes; private repos get 2,000 free minutes/month on the free GitHub plan — either is enough for one daily job.
- Workflow steps: checkout → install Python deps → run collector → call Groq API for script → run Kokoro TTS → publish output (14.5) → done.

### 14.5 Storage & Delivery to the Android App — free
- **Firebase (Spark — free plan)**:
  - Cloud Storage: hosts the daily MP3 (a ~15–20MB file is trivial against the free 5GB storage / 1GB-per-day download quota for one user).
  - Firestore: stores episode metadata (date, topics, transcript, source links).
  - Cloud Messaging (FCM): sends the "your briefing is ready" push notification — free at any volume, and is what actually satisfies FR-8 (push notification) since GitHub alone has no way to proactively notify the app.
  - No credit card is required for the Spark plan.
- Simpler zero-account alternative (fallback if Firebase setup is ever unwanted): publish the MP3 + transcript as a GitHub Release asset each day and have the app poll a fixed "latest release" URL — works, but loses push notifications.

### 14.6 Android Client — free/open-source toolchain
- **Kotlin** + **Android Studio** (both free).
- **Jetpack Media3 (ExoPlayer)** — Google's open-source media playback library, for the podcast player screen.
- **Firebase Android SDK** (free) for Storage/Firestore/FCM integration.

### 14.7 Cost Summary

| Component | Tool | Monthly cost |
|---|---|---|
| Content collection | RSS + GitHub API + HN API + Reddit API | $0 |
| AI scripting | Groq free-tier API (open-weight models) | $0 |
| Text-to-speech | Kokoro-82M (self-hosted, open-weight) | $0 |
| Orchestration | GitHub Actions | $0 |
| Storage + push notification | Firebase Spark (free plan) | $0 |
| Android app toolchain | Kotlin, Android Studio, Media3 | $0 |
| **Total** | | **$0** |

### 14.8 Play Store Readiness (build for it now, submit later)

v1 ships as a personal sideload / internal-testing build, but since Play Store is a stated later goal, a few things are worth getting right from day one so there's no rework:

- **Package/applicationId:** use a real reverse-domain id from the start (e.g. `com.shahbaz.dailytechupdates`), not a throwaway placeholder — this can't be changed after Play Store listing without shipping as a "new" app.
- **Content originality:** the app must narrate/summarize in the pipeline's own words (already the design, per Section 11) rather than reproduce copyrighted article text verbatim — avoids Play Store content-policy and copyright issues if this ever goes public.
- **Privacy policy:** even a single-user free app needs a privacy policy URL before Play Store submission if it uses Firebase (FCM registration tokens, Firestore) — a simple static page is enough; not needed for v1 sideload, but worth a placeholder note now.
- **Sensible defaults:** proper app icon, versionCode/versionName scheme, and a `RELEASE`-vs-`DEBUG` build config from the start, so the same codebase can later produce a Play-ready release build without restructuring.
- Everything above costs $0 and is just "build it the right way the first time" — no separate Play Store spend is needed until/unless you actually publish (Google's one-time $25 developer registration fee only applies at that point, not now).

### 14.9 YouTube video publishing (added 2026-08-03) — free, unattended, additive to the app path

Each day's episode is now also rendered into a video and uploaded to the user's existing
YouTube channel/playlist, alongside (not instead of) the existing Android/Firebase delivery.
Full design rationale and rejected alternatives: `docs/superpowers/specs/2026-08-03-youtube-video-design.md`.

- **Visual style — cover art + karaoke-style captions:** a single static branded cover image
  (built once, committed under `pipeline/video/assets/`) with the script's own words burned in
  as captions, timed to the narration using the per-chunk timing Kokoro's TTS pass already
  produces (`tts/synthesize.py` → `captions_<date>.json`) — no separate forced-alignment/ASR
  tool needed, and no drift risk between audio and captions. Rendered with `ffmpeg`
  (`video/build_video.py`), already a pipeline dependency for MP3 conversion. A per-topic
  infographic slide deck was considered and deferred as meaningfully more build/maintenance
  surface for this iteration.
- **Thumbnails:** templated and Pillow-based (`video/thumbnail.py`), not AI-generated — the
  day's dominant topic (first entry in `topics_covered`) picks an accent color/template, with
  date and topic list overlaid as text. Deterministic, instant, and can't rate-limit or produce
  off-topic output, which matters for a job that must run unattended with no one watching it.
- **Metadata:** one additional Groq call per day (`video/metadata.py`), reusing the same
  free-tier open-weight model already writing the script, generates title/description/tags from
  that day's approved script text, including a fixed disclosure line that narration is
  AI-generated and content is aggregated from public sources.
- **Upload:** `publish/youtube_publish.py` (`google-api-python-client` + `google-auth`) uploads
  the video (Public, Science & Technology category, YouTube's synthetic-media disclosure flag
  set, per policy for AI-narrated content), sets the thumbnail, and adds it to the configured
  playlist. Runs as its own stage after the existing Firebase publish stage, so a YouTube-side
  failure can never block the Android app's episode delivery.
- **Auth:** a one-time OAuth 2.0 Desktop-app client (`auth/youtube_oauth_setup.py`, run locally
  only — see README) mints a refresh token stored as a GitHub Actions secret. Unverified Google
  OAuth apps have refresh tokens that expire after 7 days, which would silently break
  unattended daily uploads — per the user's decision, this project goes through Google's free
  OAuth verification process for a non-expiring token; while verification is pending, the
  upload stage detects an expired/revoked token and logs a clearly-flagged warning rather than
  failing silently.
- **Cost:** $0/month — runs entirely on the YouTube Data API v3's free quota and tools already
  used elsewhere in this stack (Groq, ffmpeg, GitHub Actions); no new paid service.

## 15. Future Enhancements (Phase 2+)

- Multiple podcasts/episodes per day (e.g., a "deep dive" second episode, or split by topic group).
- Multi-voice/dialogue-style podcast (two hosts discussing).
- Personalized topic weighting based on listening behavior.
- Interactive mode: ask follow-up questions about a news item referenced in the episode.
- Multi-language narration.
- iOS app / web player.
- Push a weekly "top stories" recap episode.

## 16. Open Questions

Resolved on 2026-08-02: pipeline hosting (free cloud automation via GitHub Actions), LLM choice (open-weight models via free Groq API), TTS choice (Piper, open-source/self-hosted), and budget (hard $0 target) — see Section 14.

Resolved on 2026-08-02: **Distribution** — personal/sideload for v1, but built with Play Store submission as a later goal (see Section 14.8 for what that implies now vs. later).

Still open:
1. **Retention:** How many days/months of episode archive should be kept (affects Firebase free-tier storage headroom, though $0 easily covers a year+ of daily 20-min episodes at this size)?
2. **Source licensing:** Any specific sites you explicitly want included or explicitly want avoided?
3. **Firebase acceptance:** Defaulting to yes (free Firebase Spark project, no card needed) since it's the only free way to get real push notifications (FR-8). Flag it if you'd rather avoid Google services and fall back to the GitHub-Release-only option (Section 14.5), which drops push notifications.

## 17. Success Metrics (V1)

- Episode successfully generated and available by 8:00 AM AST on ≥95% of days.
- Episode runtime tracks real news volume (~18–22 min on active days, shorter on quiet ones) — never padded to hit a number. See Section 3.
- Zero fabricated facts, companies, or resolutions traced back to source items (spot-checked periodically against `topics_covered` source links in the transcript).
- User (self-reported) finds content accurate and non-redundant across days.
- Pipeline cost stays at $0/month.

---
*This BRD is a living document — update as decisions are made on the Open Questions in Section 16.*
