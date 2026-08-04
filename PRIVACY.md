# Privacy Policy — Shahbaz Daily Updates

**Last updated:** 2026-08-04

Shahbaz Daily Updates is a personal, single-operator automation project that
generates and publishes a daily tech-news podcast (audio, a companion Android
app, and a YouTube video). This policy describes how the project's automated
pipeline uses Google APIs and what data, if any, it collects.

## Who operates this

This project is built and operated by a single individual (the "operator")
for their own personal YouTube channel and Android app. It is not a
multi-tenant service, and it does not have external end users whose accounts
it accesses — it only ever acts on the operator's own YouTube channel, using
credentials the operator generated for themselves.

## What the pipeline does

Once a day, an automated script (running on GitHub Actions):

1. Collects publicly available tech-news headlines and summaries from public
   RSS feeds, GitHub Releases, Hacker News, and Reddit.
2. Uses a third-party LLM API (Groq) to write a short news script from that
   public content.
3. Synthesizes narration audio using an open-weight text-to-speech model
   (Kokoro), run locally within the automation — no third party receives the
   audio content for this step.
4. Renders a video (a static cover image with synchronized captions) from
   that audio.
5. Uploads the resulting video to the operator's own YouTube channel via the
   YouTube Data API v3, sets a thumbnail, and adds it to a playlist the
   operator owns.

## Use of Google user data (YouTube Data API)

This project's only use of Google/YouTube data is to manage content on the
**operator's own YouTube channel**:

- Uploading videos (`youtube.videos.insert`)
- Setting a video's thumbnail (`youtube.thumbnails.set`)
- Adding videos to a playlist the operator owns (`youtube.playlistItems.insert`)
- Listing items already in that playlist, to avoid uploading a duplicate
  video for a day that's already been published (`youtube.playlistItems.list`)

The project does **not** access, read, or store any other Google user's
data. It does not access viewer data, comments, analytics, or any other
YouTube channel besides the operator's own. The OAuth refresh token used for
this is stored as an encrypted GitHub Actions secret (encrypted at rest,
never exposed in workflow logs or to forks of the repository) and is never
committed to source control or transmitted anywhere else. The automation's
source code is in a public GitHub repository, but this secret is not part
of that code and is not visible in it.

## Data this project does not collect

This project does not collect, store, or share personal data about end
users, viewers, or any third party. It has no user accounts, no sign-in
flow for anyone other than the operator's one-time OAuth consent, no
analytics/tracking, and no database of user information.

## Data retention

- The YouTube OAuth refresh token is retained only as a GitHub Actions
  secret, until the operator revokes/rotates it.
- Generated episode content (scripts, audio, video, captions) is published
  publicly (to YouTube and/or the operator's own Android app release
  channel) and is not otherwise retained beyond what's needed to build that
  day's episode.

## Third-party services used

- **Groq** (LLM API) — receives only publicly available headline/summary
  text collected in step 1 above, to generate the day's script.
- **Google/YouTube Data API v3** — used as described above, for the
  operator's own channel only.
- **Hugging Face** — used only to download the open-weight Kokoro TTS model
  weights; no user or episode data is sent to it.

## Contact

Questions about this policy or the project can be sent to
khan.shahbazmohd@gmail.com.
