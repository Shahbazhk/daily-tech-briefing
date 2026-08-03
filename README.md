# Shahbaz Daily Updates

Automated ~20-minute daily tech podcast (Java, Spring Boot, Liferay, Hibernate, Kafka, Redis,
Docker, Microservices, Kubernetes, Jenkins, Git, Cloud, …), delivered by 8:00 AM AST every day
to a personal Android app. Full requirements/design rationale: [`BRD.md`](./BRD.md) (see
Section 14 for the free/open-source stack decisions this scaffold implements).

## Repo layout

```
pipeline/            Python automation: collect news -> write script (Groq/open-weight LLM)
                      -> synthesize audio (Kokoro, open-weight TTS) -> publish (Firebase)
.github/workflows/    GitHub Actions cron job that runs the pipeline daily, for free
android-app/          Android (Kotlin) app: plays the daily episode, push notification
```

Everything here targets **$0/month** — see BRD Section 14.7 for the full cost breakdown.

## One-time setup

### 1. Groq API key (free, for AI script writing)
1. Create an account at https://console.groq.com (no card required).
2. Generate an API key under **API Keys**.
3. You'll add this as `GROQ_API_KEY`.

### 2. GitHub token (free, raises API rate limits for collection)
- In Actions this is provided automatically (`secrets.GITHUB_TOKEN`), nothing to do.
- For local runs, create a classic personal access token with no special scopes (public repo
  read is enough) at https://github.com/settings/tokens.

### 3. Reddit API app (free, optional but recommended)
1. https://www.reddit.com/prefs/apps → **create app** → type **script**.
2. Note the client ID (under the app name) and client secret.

### 4. Firebase project (free Spark plan — storage, episode metadata, push notifications)
1. https://console.firebase.google.com → **Add project** (no card needed on Spark plan).
2. Enable **Firestore Database**, **Cloud Storage**, and **Cloud Messaging** in the console.
3. Register an Android app with applicationId `com.shahbaz.dailytechupdates`, download
   `google-services.json`, place it at `android-app/app/google-services.json`
   (see `android-app/app/google-services.json.example` for what it looks like — gitignored, never commit the real one).
4. Project Settings → **Service accounts** → **Generate new private key** → this JSON becomes
   the `FIREBASE_SERVICE_ACCOUNT` secret. Also note your storage bucket name (usually
   `<project-id>.appspot.com`) for `FIREBASE_STORAGE_BUCKET`.

> Don't want any Google service at all? Leave `FIREBASE_SERVICE_ACCOUNT` unset — the pipeline
> and workflow both detect this and fall back to publishing each episode as a GitHub Release
> instead (see `pipeline/publish/publish.py` and the last step of the workflow). You lose push
> notifications in that mode; the app would need to poll GitHub Releases instead (not yet wired
> up in the app skeleton — flag if you want this path instead of Firebase).

### 5. GitHub Actions secrets
In your repo → **Settings → Secrets and variables → Actions**, add:
`GROQ_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`,
`FIREBASE_SERVICE_ACCOUNT` (paste the whole service-account JSON), `FIREBASE_STORAGE_BUCKET`.

## Running the pipeline locally

```bash
cd pipeline
python -m venv .venv && . .venv/Scripts/activate   # Windows; use bin/activate on macOS/Linux
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in values, then export them into your shell, e.g.:
#   set -a; source ../.env; set +a      (bash)
#   Get-Content ..\.env | ... (or just set $env:VAR manually in PowerShell)

python run_pipeline.py --skip-publish   # collect + write script + synthesize audio only
```

ffmpeg and espeak-ng aren't in `requirements.txt` (they're system packages, see the workflow
steps that `apt-get install` them) — for local runs on Linux/macOS, install both with your
package manager once, same as CI does. `torch` is also installed separately as a CPU-only
build (`pip install torch --index-url https://download.pytorch.org/whl/cpu`) to avoid pulling
in unused CUDA libraries.

Outputs land in `pipeline/data/` (gitignored): `collected_<date>.json`, `script_<date>.md`,
`transcript_<date>.json`, `episode_<date>.mp3`.

## Running the daily job

Already wired up in `.github/workflows/daily-episode.yml` — cron-scheduled for 00:00 UTC
(03:00 AM AST, a 5-hour buffer before the 8 AM delivery target, since GitHub's `schedule`
trigger is best-effort and can be delayed by hours under load). You can also trigger it
manually from the **Actions** tab (**Run workflow**) to test end-to-end before relying on the
schedule.

## Opening the Android app

1. Open `android-app/` in Android Studio (Iguana+ recommended). Studio will offer to
   generate the Gradle wrapper on first sync if it's missing — accept it.
2. Make sure `android-app/app/google-services.json` exists (step 4 above) — the
   `google-services` Gradle plugin fails the build without it.
3. Run on a device/emulator running Android 8.0 (API 26) or newer.

## Things worth double-checking before the first real run

- **RSS feed URLs** in `pipeline/config/sources.yaml` are best-effort defaults; official blogs
  occasionally move their feeds. The collector logs and skips a broken URL rather than failing
  the whole run, but worth spot-checking once.
- **Kokoro voice name** (`af_heart`) in `pipeline/tts/synthesize.py` — see
  https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md for the full voice list if
  you want to swap it (e.g. for a male voice, try `am_michael`).
- **Groq model id** (`llama-3.3-70b-versatile`) — Groq's free-tier model lineup changes over
  time; check https://console.groq.com/docs/models if `generate_script.py` starts 404ing, and
  override via the `GROQ_MODEL` env var without touching code.

## Roadmap

See BRD Section 15 (Future Enhancements) — multiple daily episodes, dialogue-style two-host
format, personalized topic weighting, multi-language, and eventually Play Store distribution
(BRD Section 14.8 covers what's already built in now to avoid rework later).
