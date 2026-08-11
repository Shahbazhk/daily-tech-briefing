# Episode history and offline downloads — design

Status: approved, ready for implementation plan
Date: 2026-08-11

## 1. Goal

Today the Android app only ever shows the single latest episode, streamed
live from its GitHub Release URL — there's no way to go back and replay an
older day, and no way to listen with no internet connection. This adds:

1. A history screen listing every past episode (not just the latest).
2. An explicit, per-episode "save for offline" download, so a chosen
   episode can be replayed with no network connection.

Same hard constraint as the rest of the project: $0/month, no new paid
services, and — specifically for this piece — no new third-party
dependencies beyond what standard Android already provides (`DownloadManager`,
`SharedPreferences`), matching the app's existing minimal-dependency style.

## 2. Context (what already exists)

- `EpisodeRepository.getLatestEpisode()` lists all GitHub Releases
  (`GET /repos/.../releases`, unauthenticated), picks the newest one tagged
  `episode-YYYY-MM-DD` (never uses `/releases/latest`, since this repo also
  publishes `app-latest` APK releases into the same list — see the existing
  code comment), and returns a single `Episode` with `date`, `audioUrl`,
  `topicsCovered`, and `script`.
- `MainActivity` is a single screen: fetches the latest episode on open,
  streams its `audioUrl` directly into an ExoPlayer `MediaItem`, no
  persistence of any kind.
- The app has no test infrastructure today (no test source set, no test
  dependencies in `app/build.gradle`) and no local storage beyond what
  Android/ExoPlayer manage internally.
- Every day's episode already exists indefinitely as its own GitHub Release
  — this feature doesn't change the pipeline or backend at all, it's
  entirely new Android-app code consuming data that already exists.

## 3. Data layer

### 3.1 `EpisodeSummary` (new data class)

```kotlin
data class EpisodeSummary(
    val date: String,           // "2026-08-10"
    val topicsCovered: List<String>,
    val audioUrl: String,
    val transcriptUrl: String
)
```

Lighter than `Episode` — no `script` field, since the history list only
needs enough to render a row and to know where to fetch full detail
(`audioUrl`/`transcriptUrl`) if the user picks that row.

### 3.2 `EpisodeRepository.getEpisodeHistory()`

```kotlin
suspend fun getEpisodeHistory(): List<EpisodeSummary>
```

- Pages through `GET /repos/.../releases?per_page=100&page=N`, incrementing
  `page` until a page comes back empty, collecting every release whose
  `tag_name` starts with `episode-`.
- For each such release, builds an `EpisodeSummary` from its assets (same
  `.mp3` / `transcript_*.json` asset-matching logic already in
  `getLatestEpisode()` — extract it into a shared private helper so both
  methods use one implementation, not two copies) — but does **not**
  eagerly fetch each transcript's JSON body (that's 100+ HTTP calls for a
  year of history). `topicsCovered` for the list view comes from a topics
  cache alongside the history cache (3.3); if a day isn't cached yet,
  `topicsCovered` is empty for that row until it's fetched once via
  `getEpisodeDetail`.
- Sorted newest-first by tag name (ISO dates sort correctly as strings).
- On any network failure partway through paging, returns what was
  successfully fetched so far merged with the local cache (3.3) rather than
  throwing — the caller (HistoryActivity) always gets a usable list.

### 3.3 Local history cache (`history_cache.json`)

A JSON file in the app's private files directory (`filesDir`), read/written
with the same raw `org.json` style already used elsewhere in this codebase
(no new JSON library). Shape:

```json
{
  "2026-08-10": {"topicsCovered": ["Java", "Kafka", "Docker"]},
  "2026-08-09": {"topicsCovered": ["Rust", "WASM"]}
}
```

- Written any time `getEpisodeHistory()` or the single-episode detail fetch
  successfully resolves a day's topics.
- Read first on every `getEpisodeHistory()` call, so the History screen has
  an immediate, possibly-stale list to render before/instead-of the network
  call resolving — merged with fresh network results when they arrive
  (network data always wins on conflict).
- This is what makes History browsable with no connection at all: cached
  rows render (with a ⬇/✓ status from `DownloadStore`); rows never seen
  before simply don't appear until back online.

### 3.4 `DownloadStore`

Tracks explicit user downloads, same `org.json`-over-`SharedPreferences`
pattern, separate file/key from the history cache since it has a different
lifecycle (survives regardless of history-cache staleness):

```json
{
  "2026-08-10": {"localPath": "/data/.../episodes/2026-08-10.mp3", "downloadedAtEpochMillis": 1786000000000}
}
```

- `DownloadStore.startDownload(date, audioUrl)`: enqueues via Android's
  `DownloadManager` into `getExternalFilesDir(null)/episodes/<date>.mp3`;
  registers a `BroadcastReceiver` for `ACTION_DOWNLOAD_COMPLETE` to record
  the entry on success, or leave the row un-downloaded (no partial file
  left registered) on failure.
- `DownloadStore.localPathFor(date): String?` — null if not downloaded.
- `DownloadStore.purgeExpired()`: called once on every `MainActivity` and
  `HistoryActivity` `onCreate`; deletes the file and drops the record for
  any entry where `now - downloadedAtEpochMillis > 30 days`.
- `DownloadStore.delete(date)`: manual delete, for a future "remove
  download" affordance (not a required UI in this pass, but the store
  supports it since purge needs the same delete path).

### 3.5 Shared playback-source resolution

A single helper (e.g. top-level function in `EpisodeRepository.kt` or a
small new `PlaybackSource.kt`):

```kotlin
fun resolvePlaybackUri(date: String, audioUrl: String, downloadStore: DownloadStore): Uri
```

Returns a `file://` URI if `downloadStore.localPathFor(date)` is non-null,
else the streamed `audioUrl` as-is. Both `MainActivity` (today's episode)
and `HistoryActivity` (any past episode) call this one function before
`player.setMediaItem(...)`, so the local-vs-stream decision lives in
exactly one place.

## 4. UI

### 4.1 `MainActivity` changes

Adds one new icon/button (existing top area, next to the date) that opens
`HistoryActivity`. No other change to its current behavior — it still
loads and plays today's episode on open, using `resolvePlaybackUri` instead
of always streaming.

### 4.2 `HistoryActivity` (new)

- A `RecyclerView` backed by `getEpisodeHistory()`, one row per day:
  date, `topicsCovered.joinToString(" • ")`, and a status icon:
  - ▶ — not downloaded, tap plays via streaming.
  - ⬇ — not downloaded, tap starts a download (icon becomes a progress
    state until `DownloadManager` reports completion, then becomes ✓).
  - ✓ — downloaded, tap plays from local file.
- Tapping the row's text (not the icon) always plays that episode
  (streamed or local, whichever `resolvePlaybackUri` resolves to); the
  icon on the right is specifically the download affordance.
- Reuses the same `ExoPlayer` instance/playback UI pattern as
  `MainActivity` (pass the player instance in, or duplicate the minimal
  play/pause bar — implementation plan decides based on how much
  MainActivity's playback UI is worth extracting into a shared component;
  YAGNI says don't over-abstract a two-screen app, so plan for a small
  shared playback-bar view rather than a bigged-up "player service").

### 4.3 Error/empty states

- History list empty (first launch, nothing cached, no network): existing
  app string pattern (`R.string.no_episode_yet`-style) reused for
  "History unavailable — check your connection."
- A row whose download fails: icon reverts to ⬇, no toast/dialog needed —
  failure is visually silent and simply retryable by tapping again.

## 5. Testing

The app has zero test infrastructure today; this feature is also where
that gets introduced, scoped to what's actually pure-Kotlin-testable:

- Add `testImplementation("junit:junit:4.13.2")` (standard, no new
  runtime dependency) to `app/build.gradle`, plus a `test/` source set.
- `DownloadStoreTest`: purge-expiry logic (entries older than 30 days
  removed, newer ones kept), record/read round-trip on the JSON shape.
- `PlaybackSourceTest`: `resolvePlaybackUri` returns the local file URI
  when present, the stream URL otherwise.
- History-cache merge logic (3.3): network results overwrite stale cache
  entries for the same date; a network failure doesn't wipe out
  previously-cached entries.
- `HistoryActivity`/`RecyclerView` wiring itself is not unit-tested (no
  instrumentation test infra exists or is being added here) — verified
  manually, consistent with how `MainActivity` is verified today.

## 6. Non-goals (explicitly out of scope for this pass)

- No "delete download" UI (the store supports it; wiring a button is a
  trivial follow-up, not required for the core feature).
- No download-progress percentage in the list row — just the three-state
  icon (▶ / downloading-spinner / ✓). `DownloadManager`'s own system
  notification already shows percentage if the user wants it.
- No change to the pipeline/backend — this is purely new Android-app code
  against data that already exists in GitHub Releases.
