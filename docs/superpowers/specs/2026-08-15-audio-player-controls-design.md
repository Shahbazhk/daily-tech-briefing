# Audio player controls upgrade — design

Status: approved, ready for implementation plan
Date: 2026-08-15

## 1. Goal

Today's playback UI is minimal: `MainActivity` has a single Play/Pause
button for the latest episode only, and `HistoryActivity` has no player UI
at all — tapping a row just calls `player.play()` silently, with no way to
pause, seek, or see what's playing. Each activity also owns its own
`ExoPlayer` instance, released in `onDestroy()`, so playback doesn't survive
navigating between the two screens.

This adds a real transport bar: seek/progress, ±15 second skip, and
next/previous navigation across the full episode history — shared across
both screens via one persistent player, so switching from History back to
MainActivity doesn't stop what's playing.

Same $0/month, no-new-paid-services constraint as the rest of the project.
No new third-party dependencies — this is built entirely on ExoPlayer
(already a dependency) plus stock Android views (`SeekBar`, `Button`).

## 2. Context (what already exists)

- `EpisodeRepository.getEpisodeHistory(context)` already returns every
  released episode, newest-first, including today's (it lists all
  GitHub Releases tagged `episode-*`, no exclusion of the most recent one).
  `MainActivity` currently ignores this and instead calls the separate
  `getLatestEpisode()`, which resolves "today" independently (its date
  comes from the transcript body, with the release tag as fallback — a
  second, slightly different code path for the same concept).
- `DownloadStore.localPathFor(date)` / `resolvePlaybackUri(audioUrl,
  localPath)` already decide streamed-vs-downloaded per episode; unchanged
  by this feature.
- `HistoryAdapter` already tracks per-row download status
  (`RowStatus.STREAM_ONLY` / `DOWNLOADING` / `DOWNLOADED`) and calls
  `onPlay(episode)` on row tap; unchanged by this feature except for what
  `onPlay` now does.
- No test infrastructure beyond plain JUnit on pure top-level functions
  (see `DownloadStore.kt`'s `parseDownloadRecords`/`purgeExpiredRecords`
  pattern) — this feature follows the same split.
- Explicitly **out of scope** (confirmed with the app owner): background
  playback (foreground service, media-session notification, lock-screen
  controls). Playback stays tied to the app being in the foreground, same
  lifecycle boundary as today — just shared across the two screens instead
  of siloed per-activity.

## 3. `PlayerManager` (new singleton)

A new `object PlayerManager` in `PlayerManager.kt`, app-lifetime, owning
the one shared `ExoPlayer` instance and the current queue:

```kotlin
object PlayerManager {
    fun init(context: Context)   // idempotent; creates ExoPlayer + DownloadStore once
    fun loadQueue(episodes: List<EpisodeSummary>, startIndex: Int, autoPlay: Boolean)
    fun togglePlayPause()
    fun seekTo(positionMs: Long)
    fun skipForward15()
    fun skipBackward15()
    fun next()      // no-op if nextIndex() is null
    fun previous()  // no-op if previousIndex() is null
    fun addListener(listener: PlayerStateListener)
    fun removeListener(listener: PlayerStateListener)
}

interface PlayerStateListener {
    fun onStateChanged(
        episode: EpisodeSummary?,
        isPlaying: Boolean,
        positionMs: Long,
        durationMs: Long,
        hasNext: Boolean,
        hasPrevious: Boolean
    )
}
```

- `loadQueue` is a no-op if the same queue (by episode dates) and
  `startIndex` are already loaded — so reopening a screen mid-playback
  doesn't restart the current episode. A genuinely different
  `startIndex` (e.g. tapping a different History row) switches episodes.
- Internally resolves playback URI via the existing
  `resolvePlaybackUri(episode.audioUrl, downloadStore.localPathFor(episode.date))`
  before every `setMediaItem`/`prepare` — unchanged logic, just called from
  one place instead of two.
- While playing, runs a ~500ms `Handler.postDelayed` position-poll loop
  (ExoPlayer has no native "position changed" callback) and pushes
  `onStateChanged` to all registered listeners; stops polling when paused
  or nothing is loaded.
- **Next/Previous direction:** the queue is newest-first (today = index 0).
  **Next = chronologically newer** (index − 1, toward today); **Previous =
  chronologically older** (index + 1, toward history). `hasNext`/
  `hasPrevious` in the callback tell the UI when to disable a button — no
  wraparound.
- Activities call `PlayerManager.addListener(this)` in `onStart()` and
  `removeListener(this)` in `onStop()`, matching the existing
  `DownloadStore` broadcast-receiver register/unregister lifecycle pattern
  already used in both activities.

### 3.1 Pure, unit-testable helpers (same file, top-level functions)

```kotlin
fun nextIndex(currentIndex: Int, size: Int): Int?       // null at index 0
fun previousIndex(currentIndex: Int, size: Int): Int?    // null at size - 1
fun clampSeek(currentMs: Long, deltaMs: Long, durationMs: Long): Long
fun formatTime(ms: Long): String                          // "mm:ss"; "--:--" if ms <= 0
```

`PlayerManager`'s `next()`/`previous()`/`skipForward15()`/
`skipBackward15()` are thin wrappers calling these plus the ExoPlayer side
effect — mirrors how `DownloadStore` wraps `purgeExpiredRecords` etc.

## 4. UI

### 4.1 `player_bar.xml` (new, reusable layout)

One `<include>`-able layout, pinned to the bottom of both `activity_main.xml`
and `activity_history.xml`:

- Episode label (date) — small text, top of the bar.
- `SeekBar` (`max` = duration once known) + `mm:ss / mm:ss` position text.
- Transport row: `⏮ (previous)` · `-15s` · `▶/⏸ (play/pause)` · `+15s` ·
  `⏭ (next)`. `⏮`/`⏭` disabled (not hidden) when `hasPrevious`/`hasNext`
  is false.
- Dragging the `SeekBar` only calls `PlayerManager.seekTo(...)` on
  `onStopTrackingTouch`, not on every `onProgressChanged` — avoids seek
  spam mid-drag.

### 4.2 `MainActivity` changes

- Drops its own `ExoPlayer` field entirely; calls `PlayerManager.init(this)`
  and registers as a `PlayerStateListener`.
- Initial load switches from `repository.getLatestEpisode()` to
  `repository.getEpisodeHistory(applicationContext)`, treating index `0` as
  "today" — `loadQueue(history, startIndex = 0, autoPlay = false)`. Removes
  the second, slightly-inconsistent date-resolution path.
- `dateText`/`topicsText`/`statusText` now reflect whichever episode
  `PlayerManager` reports as current (via `onStateChanged`'s `episode`
  param) rather than being fixed to "today" — so if the user hits `Next`/
  `Previous` from this screen, the header stays in sync with what's
  actually playing.
- Old single Play/Pause button is replaced by the shared `player_bar`
  include; `binding.playPauseButton` and its click listener are removed.

### 4.3 `HistoryActivity` changes

- Drops its own `ExoPlayer` field entirely; same `PlayerManager.init` +
  listener registration as `MainActivity`.
- `onPlay(episode)` (row tap) now calls
  `PlayerManager.loadQueue(history, startIndex = tappedIndex, autoPlay = true)`
  instead of building a local `MediaItem` and calling `player.play()`
  directly.
- Adds the same `player_bar` include at the bottom of
  `activity_history.xml`, above `historyList`'s bottom constraint (list
  gets a bottom margin so the last row isn't hidden behind the bar).

### 4.4 Not in scope (explicit cuts)

- Highlighting the currently-playing row in the History list — adds
  RecyclerView state-tracking for something not asked for. Flagged as a
  conscious cut, not an oversight.
- Background/lock-screen playback (media-session service, notification
  transport controls) — confirmed out of scope; in-app-only playback
  lifecycle is fine for now.
- Playback speed control, sleep timer, queue reordering — not requested.

## 5. Testing

- `PlayerManagerTest` (new, plain JUnit, no Robolectric — same style as
  `DownloadStoreTest`): `nextIndex`/`previousIndex` boundary behavior
  (`null` at each end, correct index otherwise), `clampSeek` (clamps to
  `0` and to `durationMs`, normal case passes through), `formatTime`
  (`0` → `"00:00"`, `65_000` → `"01:05"`, `<= 0` duration →
  `"--:--"`).
- `PlayerManager`'s ExoPlayer-dependent internals and both activities'
  wiring are not unit-tested (no instrumentation test infra exists or is
  being added here) — verified manually on-device, same as the rest of the
  app's UI today.
- No CI changes needed — new tests land in the existing
  `app/src/test/...` source set already run by `android-tests.yml`'s
  `gradle testDebugUnitTest`.

## 6. Non-goals (explicitly out of scope for this pass)

- Background/lock-screen playback (foreground service, media notification).
- Currently-playing row highlight in History.
- Playback speed, sleep timer, queue reordering/shuffle.
- Any backend/pipeline change — this is purely new Android-app code against
  data (`getEpisodeHistory`) that already exists.
