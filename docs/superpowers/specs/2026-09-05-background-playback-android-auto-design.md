# Background Playback + Android Auto — design

Status: approved, ready for implementation plan
Date: 2026-09-05

## 1. Goal

Today, playback is deliberately in-app-only: `PlayerManager` pauses whenever no
activity of this app is visible (`enterForeground()`/`leaveForeground()`, see
`PlayerManager.kt`'s class doc). This means:
- Playback stops the moment you switch apps or lock the phone.
- Connecting to Android Auto does nothing — there's no `MediaSession` for the
  car to discover or control.

This project lifts that constraint: playback continues in the background
(lock screen, other apps open, screen off), and the currently-playing episode
is controllable from Android Auto with standard transport controls (play,
pause, ±15s skip, next/previous episode).

**Explicitly out of scope:** a browsable episode list inside Android Auto's
UI. The car mirrors whatever's already playing/paused — you pick a different
episode on your phone, same as picking a track in a podcast app before
driving off. No new dependency beyond `androidx.media3:media3-session`
(version-matched to the `media3-exoplayer`/`media3-ui` already in
`build.gradle.kts`).

## 2. Context (what already exists)

- `PlayerManager` (`android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt`)
  is an app-lifetime singleton wrapping one `ExoPlayer` directly. It owns the
  queue (`List<EpisodeSummary>` + `currentIndex`, newest-first), exposes
  transport controls (`togglePlayPause`, `seekTo`, `skipForward15`/`skipBackward15`,
  `next`/`previous`), and notifies registered `PlayerStateListener`s (used by
  `PlayerBarBinder`) via a 500ms position-polling `Handler` loop while playing.
- Pure, already-unit-tested helper functions in the same file:
  `nextIndex`/`previousIndex` (chronological queue navigation, index 0 = newest,
  "next" = toward index 0, "previous" = toward the end, both `null` at their
  boundary — no wraparound), `clampSeek` (clamps a seek to `[0, durationMs]`,
  tolerant of an unknown/negative duration), `formatTime` (mm:ss, `"--:--"`
  for a negative/unknown value).
- `enterForeground()`/`leaveForeground()`: called from `MainActivity`/
  `HistoryActivity`'s `onStart()`/`onStop()`. When the last visible activity of
  this app stops, `leaveForeground()` pauses the player — this is precisely
  the in-app-only constraint being lifted.
- `PlayerBarBinder` binds a `player_bar.xml` (`<include>`d in both activities)
  to `PlayerManager` via the `PlayerStateListener` interface; it calls
  `PlayerManager`'s functions directly on button taps.
- `DownloadStore.localPathFor(date)` resolves whether an episode has a local
  file; `resolvePlaybackUri(audioUrl, localPath)` (in `PlaybackSource.kt`)
  picks local-vs-streaming. Today this resolution happens lazily, only when
  an episode actually becomes current (`playCurrent()` in `PlayerManager`) —
  so downloading an episode while a *different* one is playing already works
  correctly today (the download only matters once that episode is selected).
- `android-app/app/src/main/res/drawable/ic_notification.xml` already exists
  but is currently unused anywhere in the app — a ready-made small icon for
  the media notification.
- `.github/workflows/build-apk.yml` already builds a debug APK and republishes
  it to the `app-latest` GitHub Release on every push to `master` touching
  `android-app/**` — no new CI work needed; this feature landing on `master`
  is sufficient for "download and update my app."

## 3. Architecture

A new `PlaybackService : MediaLibraryService` (from `androidx.media3:media3-session`)
becomes the durable owner of the `ExoPlayer` and the queue. This logic moves
out of `PlayerManager` into `PlaybackService`, because the service — not any
Activity — must now survive the app backgrounding.

`PlayerManager` is refactored into a thin client: instead of holding an
`ExoPlayer` directly, it holds a `MediaController` bound to `PlaybackService`
via a `SessionToken`. Because `MediaController` implements the same `Player`
interface `ExoPlayer` does, `PlayerManager`'s existing public function
signatures are preserved as-is — `togglePlayPause()`, `seekTo()`,
`skipForward15()`/`skipBackward15()`, `next()`/`previous()`, `loadQueue()`,
`currentEpisode()`, `addListener()`/`removeListener()` — and the 500ms
position-polling loop moves over unchanged, just reading from the controller
instead of the raw player. **`PlayerBarBinder`, `MainActivity`, and
`HistoryActivity` require no changes to how they call `PlayerManager`** —
they keep calling the same functions.

`PlayerManager.init(context)` becomes asynchronous under the hood
(`MediaController.Builder(context, sessionToken).buildAsync()`), since binding
to the service isn't instant. Consistent with the existing `initialized`
guard pattern in `PlayerManager` (methods already no-op safely before
`init()` completes), calls made before the controller connects are similarly
guarded/no-op'd rather than queued — in practice this is a non-issue since
every real call site already calls `init()` in `onCreate()` and only calls
`loadQueue()` after an async repository fetch, which takes far longer than
local service binding.

### 3.1 Transport-control mapping

| Control | Mechanism |
|---|---|
| Play/pause, seek bar | Standard `Player` commands — unchanged from today. |
| ±15s skip | ExoPlayer's built-in `setSeekForwardIncrementMs(15_000)` / `setSeekBackIncrementMs(15_000)` (set on the `ExoPlayer.Builder` in `PlaybackService`). Media3's default notification renders these as standard skip buttons for free. |
| Next/previous **episode** | Custom `SessionCommand`s (`"NEXT_EPISODE"` / `"PREVIOUS_EPISODE"`), *not* ExoPlayer's playlist next/prev (which means track-order skipping within a loaded playlist — a different concept). `PlaybackService`'s session callback handles these by reusing the existing `nextIndex`/`previousIndex` pure functions unchanged, calling the same single-current-`MediaItem`-swap logic `playCurrent()` already does today. This keeps the existing unit tests valid and preserves today's lazy, download-aware URI resolution exactly as it is now. |

Custom commands are advertised to controllers (including Android Auto) via
`MediaLibrarySession.Callback.onConnect()`'s returned `SessionCommands`, with
icons matching the app's existing ⏮/⏭ styling from `player_bar.xml`.

### 3.2 Background lifecycle

`enterForeground()`/`leaveForeground()` and the `foregroundActivityCount`
field are deleted from `PlayerManager` — that pause-on-background behavior
*is* the constraint being lifted. `MainActivity`/`HistoryActivity` drop their
calls to these from `onStart()`/`onStop()`.

`PlaybackService` overrides `onTaskRemoved()` (called when the app's task is
swiped away from recents): if the player is not currently playing, it stops
the service (releasing the player and resources, matching how a paused media
app is expected to behave when dismissed); if playing, the service stays
alive as a foreground service with the notification, which is precisely
"background playback."

### 3.3 Manifest / permissions

- `<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />`
- `<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />`
  (required for a `mediaPlayback`-type foreground service on API 34, which
  matches this project's `targetSdk`; both are install-time permissions, no
  runtime prompt).
- `<service>` entry for `PlaybackService`, `android:foregroundServiceType="mediaPlayback"`,
  `android:exported="true"` (required so Android Auto's separate process can
  bind to it), with the standard `androidx.media3.session.MediaSessionService`
  intent-filter action.
- `res/xml/automotive_app_desc.xml` declaring `<automotiveApp><uses name="media"/></automotiveApp>`,
  referenced via a `<meta-data android:name="com.google.android.gms.car.application" .../>`
  entry in `<application>` — this is what makes Android Auto discover the app
  as a media app at all.

### 3.4 Notification

Media3's `DefaultMediaNotificationProvider` builds and keeps the notification
in sync with player state automatically. Small icon: the existing, currently
unused `ic_notification.xml` (no new asset needed). Title/subtitle: episode
date/topics (same text already shown in `player_bar.xml`'s label). Tapping
the notification opens `MainActivity` via `MediaSession.Builder.setSessionActivity()`.

### 3.5 Android Auto library root

`onGetLibraryRoot()` returns a minimal, non-expandable root; `onGetChildren()`
returns an empty list. This satisfies Android Auto's discovery contract
(a `MediaLibraryService` must exist and respond) without building any browse
UI — Android Auto shows its standard "now playing" screen against the active
session's transport controls and metadata regardless of an empty browse tree.

## 4. Data flow

1. `MainActivity`/`HistoryActivity` call `PlayerManager.init(context)` in
   `onCreate()`, which starts an async `MediaController` connection to
   `PlaybackService`.
2. `PlaybackService` is created on first bind (standard Android service
   lifecycle) and builds its `ExoPlayer` + `MediaLibrarySession` once.
3. UI calls into `PlayerManager` (`loadQueue`, `togglePlayPause`, `seekTo`,
   `skipForward15`/`skipBackward15`, `next`/`previous`) become `MediaController`
   calls — standard `Player` methods for playback/seek, custom command
   dispatches for next/previous episode.
4. State changes flow back via the same `Player.Listener` mechanism
   `PlayerManager` already uses (registered on the `MediaController` instead
   of the raw player) → existing `PlayerStateListener` notification →
   `PlayerBarBinder` updates the UI — unchanged.
5. Android Auto, the lock screen, and Bluetooth media buttons talk directly
   to the `MediaSession` inside `PlaybackService` as peer controllers,
   bypassing the app's own `MediaController`/UI entirely.
6. Task removed while paused → service stops itself. Task removed while
   playing → service continues in the foreground with the notification.

## 5. Error handling

- Controller connection failure (e.g. the service process died unexpectedly):
  `PlayerManager` logs and leaves its `initialized`-style guard false; UI
  buttons remain safely no-op rather than crashing, matching the existing
  guard philosophy already in `PlayerManager` today.
- Everything else (playback errors, missing audio URL, download failures) is
  unchanged from today's behavior — this feature doesn't touch that surface.

## 6. Testing

No new unit-testable pure logic — `nextIndex`, `previousIndex`, `clampSeek`,
`formatTime` are reused unchanged, tests unchanged. `PlaybackService`,
`MediaController` wiring, the notification, and Android Auto integration are
all Android-runtime-and-hardware-dependent, following this project's existing
pattern (see the audio-player-controls plan's Global Constraints) of manual
on-device verification rather than automated tests for this class of code.

Android Auto verification can be done either against a real car head unit or
Android Auto's Desktop Head Unit (DHU) emulator (runs on a PC via Android
Studio, no car required) — whichever is convenient at verification time; the
implementation plan will call out both as options rather than assuming one.

## 7. Non-goals (explicitly out of scope for this pass)

- No browsable episode list in Android Auto (§3.5) — pick episodes on the
  phone.
- No episode/album artwork — no such assets exist today; notification and
  Android Auto show the app's existing monochrome icon only.
- No new GitHub Actions workflow — the existing `build-apk.yml` already
  covers "download and update my app" once this lands on `master`.
- No multi-process service (`android:process=":playback"`) — stays
  single-process for simplicity; not needed at this app's scale.
