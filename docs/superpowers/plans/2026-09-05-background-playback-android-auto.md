# Background Playback + Android Auto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let playback continue in the background (lock screen, other apps, screen off) and be controllable from Android Auto with standard transport controls, replacing `PlayerManager`'s current in-app-only, pause-on-background design.

**Architecture:** A new `PlaybackService : MediaLibraryService` (media3-session) becomes the durable owner of the `ExoPlayer` and the episode queue. `PlayerManager` is refactored from directly owning an `ExoPlayer` into a thin client holding a `MediaController` bound to `PlaybackService` — since `MediaController` implements the same `Player` interface `ExoPlayer` does, `PlayerManager`'s public function signatures are unchanged, so `PlayerBarBinder`/`MainActivity`/`HistoryActivity` require no changes beyond deleting the now-obsolete `enterForeground()`/`leaveForeground()` calls.

**Tech Stack:** Kotlin, AndroidX Media3 (`media3-exoplayer`, `media3-ui`, new: `media3-session`), `kotlin-parcelize` plugin, View Binding, JUnit4.

## Global Constraints

- No new third-party dependency beyond `androidx.media3:media3-session:1.4.1` (version-matched to the already-pinned `media3-exoplayer`/`media3-ui`). Enabling the first-party `kotlin-parcelize` Gradle plugin (needed to send `EpisodeSummary` across the `MediaController`/session boundary) is not considered a new dependency — it's a built-in feature of the Kotlin Gradle plugin already applied.
- Next/previous **episode** navigation is a custom `SessionCommand`, not ExoPlayer's playlist next/prev (a different concept — track-order skipping within a loaded playlist). This keeps `nextIndex`/`previousIndex`/`clampSeek`/`formatTime` (and their existing unit tests) completely unchanged, and preserves today's lazy, download-aware URI resolution (an episode's local-vs-streaming URL is resolved only when it becomes current, inside `PlaybackService`).
- ±15s skip uses ExoPlayer's built-in `setSeekForwardIncrementMs`/`setSeekBackIncrementMs` + `Player.seekForward()`/`seekBack()` — not custom commands.
- No browsable episode list in Android Auto: `onGetLibraryRoot`/`onGetChildren` return an empty tree. Android Auto still shows its standard "now playing" screen against the active session regardless.
- Reuse existing, currently-unused assets: `res/drawable/ic_notification.xml` (notification small icon) and the `notification_channel_name` string (`"Daily Episode"`) — no new assets.
- Single-process service (no `android:process=":playback"`).
- No automated tests for `PlaybackService`/`MediaController`/Android-Auto wiring — this is Android-runtime-and-hardware-dependent, following this project's existing pattern (see the audio-player-controls plan's Global Constraints) of manual on-device verification for this class of code. Verification is: it compiles (`gradle testDebugUnitTest`, which compiles the whole module including `main`), the existing test suite still passes, and it's exercised for real in the final two manual-verification tasks.
- No new GitHub Actions workflow — `.github/workflows/build-apk.yml` already rebuilds and republishes the debug APK to the `app-latest` GitHub Release on every push to `master` touching `android-app/**`.

---

### Task 1: Add `media3-session` + `kotlin-parcelize`, make `EpisodeSummary` `Parcelable`

**Files:**
- Modify: `android-app/app/build.gradle.kts`
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeSummary.kt`

**Interfaces:**
- Produces: `EpisodeSummary` now implements `Parcelable` — used by Task 2 (`PlaybackService`, receiving a `List<EpisodeSummary>` via a custom command's `Bundle`) and Task 3 (`PlayerManager`, sending it).

No automated test — this is a dependency/annotation-only change with no new logic. Verified by compiling.

- [ ] **Step 1: Add the plugin and dependency**

In `android-app/app/build.gradle.kts`, add `id("kotlin-parcelize")` to the `plugins` block:

```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("kotlin-parcelize")
    // Re-add "com.google.gms.google-services" here (and its classpath in the root
    // build.gradle.kts) once Firebase is set up and app/google-services.json exists —
    // see EpisodeRepository's TODO. Left out for now so the app builds and installs
    // without needing a Firebase project first (BRD Section 14.5 fallback path).
}
```

Add `media3-session` to `dependencies`, directly below the existing media3 lines:

```kotlin
    // Podcast playback - Google's open-source Media3/ExoPlayer.
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")
    implementation("androidx.media3:media3-session:1.4.1")
```

- [ ] **Step 2: Make `EpisodeSummary` Parcelable**

Replace the whole file `android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeSummary.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import android.os.Parcelable
import kotlinx.parcelize.Parcelize

@Parcelize
data class EpisodeSummary(
    val date: String,
    val topicsCovered: List<String>,
    val audioUrl: String,
    val transcriptUrl: String
) : Parcelable
```

- [ ] **Step 3: Run the existing test suite to confirm it still compiles and passes**

Run (from `android-app/`): `gradle testDebugUnitTest`

- [ ] **Step 4: Commit**

```bash
git add android-app/app/build.gradle.kts android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeSummary.kt
git commit -m "Add media3-session dependency and make EpisodeSummary Parcelable"
```

---

### Task 2: Create `PlaybackService` (background playback + Android Auto discovery)

**Files:**
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlaybackService.kt`
- Create: `android-app/app/src/main/res/xml/automotive_app_desc.xml`
- Modify: `android-app/app/src/main/AndroidManifest.xml`

**Interfaces:**
- Consumes: `nextIndex`, `previousIndex` (existing, in `PlayerManager.kt`, unchanged by this task); `EpisodeSummary` (Task 1); `DownloadStore.localPathFor(date): String?` (existing); `resolvePlaybackUri(audioUrl, localPath): String` (existing, in `PlaybackSource.kt`).
- Produces (used by Task 3): the custom session-command protocol —
  `COMMAND_NEXT_EPISODE`, `COMMAND_PREVIOUS_EPISODE`, `COMMAND_LOAD_QUEUE` (action strings),
  `ARG_EPISODES`/`ARG_START_INDEX`/`ARG_AUTO_PLAY` (bundle keys for `COMMAND_LOAD_QUEUE`'s args),
  `EXTRA_TOPICS`/`EXTRA_HAS_NEXT`/`EXTRA_HAS_PREVIOUS` (bundle keys inside each `MediaItem`'s `MediaMetadata.extras`) — all as top-level `internal const val`s in this file, visible unqualified from `PlayerManager.kt` (same package). Also produces the `PlaybackService` class itself, referenced by `PlayerManager` via `PlaybackService::class.java` for building its `SessionToken`.

No automated test — depends on `ExoPlayer`/`MediaLibrarySession`, needing the Android runtime (same constraint `DownloadStore`'s Android-dependent parts already have). Verified by compiling now; exercised for real in Tasks 4 and 5.

**Note on task-removal behavior:** `MediaSessionService`'s *default* `onTaskRemoved()` already does exactly what the design calls for — stop the service if playback isn't ongoing, otherwise keep it running in the foreground — so `PlaybackService` deliberately does **not** override `onTaskRemoved()`. This is verified directly in Task 4, Step 5.

- [ ] **Step 1: Create the automotive app descriptor**

Create `android-app/app/src/main/res/xml/automotive_app_desc.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<automotiveApp>
    <uses name="media"/>
</automotiveApp>
```

- [ ] **Step 2: Create `PlaybackService.kt`**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlaybackService.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import android.app.PendingIntent
import android.content.Intent
import android.os.Bundle
import androidx.core.os.BundleCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaLibraryService.LibraryParams
import androidx.media3.session.MediaSession
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

internal const val COMMAND_NEXT_EPISODE = "com.shahbaz.dailytechupdates.NEXT_EPISODE"
internal const val COMMAND_PREVIOUS_EPISODE = "com.shahbaz.dailytechupdates.PREVIOUS_EPISODE"
internal const val COMMAND_LOAD_QUEUE = "com.shahbaz.dailytechupdates.LOAD_QUEUE"
internal const val ARG_EPISODES = "episodes"
internal const val ARG_START_INDEX = "start_index"
internal const val ARG_AUTO_PLAY = "auto_play"
internal const val EXTRA_TOPICS = "topics_covered"
internal const val EXTRA_HAS_NEXT = "has_next"
internal const val EXTRA_HAS_PREVIOUS = "has_previous"

private const val NOTIFICATION_CHANNEL_ID = "daily_episode_playback"
private const val ROOT_MEDIA_ID = "root"

/**
 * Owns the one shared ExoPlayer + MediaSession for the whole app - the durable playback
 * owner instead of PlayerManager, so playback survives the app backgrounding (a foreground
 * service, unlike an app-lifetime singleton, keeps running once no activity is visible).
 * PlayerManager (in the app process) talks to this service exclusively through a
 * MediaController; Android Auto, the lock screen, and Bluetooth media buttons talk to the
 * same MediaSession directly as peer controllers - that's what makes background playback and
 * Android Auto support "the same change" rather than two separate features.
 */
class PlaybackService : MediaLibraryService() {

    private lateinit var player: ExoPlayer
    private lateinit var mediaLibrarySession: MediaLibrarySession
    private lateinit var downloadStore: DownloadStore

    private var queue: List<EpisodeSummary> = emptyList()
    private var currentIndex: Int = -1

    override fun onCreate() {
        super.onCreate()
        downloadStore = DownloadStore(applicationContext)

        player = ExoPlayer.Builder(this)
            .setSeekForwardIncrementMs(15_000)
            .setSeekBackIncrementMs(15_000)
            .build()

        val sessionActivity = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )

        mediaLibrarySession = MediaLibrarySession.Builder(this, player, LibrarySessionCallback())
            .setSessionActivity(sessionActivity)
            .build()

        val notificationProvider = DefaultMediaNotificationProvider.Builder(this)
            .setChannelId(NOTIFICATION_CHANNEL_ID)
            .setChannelName(R.string.notification_channel_name)
            .build()
        notificationProvider.setSmallIcon(R.drawable.ic_notification)
        setMediaNotificationProvider(notificationProvider)
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession =
        mediaLibrarySession

    override fun onDestroy() {
        mediaLibrarySession.release()
        player.release()
        super.onDestroy()
    }

    private fun loadQueue(episodes: List<EpisodeSummary>, startIndex: Int, autoPlay: Boolean) {
        if (startIndex !in episodes.indices) return
        if (queue == episodes && currentIndex == startIndex) return
        queue = episodes
        currentIndex = startIndex
        playCurrent(autoPlay)
    }

    private fun playCurrent(autoPlay: Boolean) {
        val episode = queue.getOrNull(currentIndex) ?: return
        val uri = resolvePlaybackUri(episode.audioUrl, downloadStore.localPathFor(episode.date))
        val metadataExtras = Bundle().apply {
            putStringArrayList(EXTRA_TOPICS, ArrayList(episode.topicsCovered))
            putBoolean(EXTRA_HAS_NEXT, nextIndex(currentIndex, queue.size) != null)
            putBoolean(EXTRA_HAS_PREVIOUS, previousIndex(currentIndex, queue.size) != null)
        }
        val mediaItem = MediaItem.Builder()
            .setUri(uri)
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(episode.date)
                    .setExtras(metadataExtras)
                    .build()
            )
            .build()
        player.setMediaItem(mediaItem)
        player.prepare()
        if (autoPlay) player.play()
    }

    private fun next() {
        val target = nextIndex(currentIndex, queue.size) ?: return
        currentIndex = target
        playCurrent(autoPlay = true)
    }

    private fun previous() {
        val target = previousIndex(currentIndex, queue.size) ?: return
        currentIndex = target
        playCurrent(autoPlay = true)
    }

    private inner class LibrarySessionCallback : MediaLibrarySession.Callback {

        override fun onConnect(
            session: MediaSession,
            controller: MediaSession.ControllerInfo
        ): MediaSession.ConnectionResult {
            val sessionCommands = MediaSession.ConnectionResult.DEFAULT_SESSION_AND_LIBRARY_COMMANDS
                .buildUpon()
                .add(SessionCommand(COMMAND_NEXT_EPISODE, Bundle.EMPTY))
                .add(SessionCommand(COMMAND_PREVIOUS_EPISODE, Bundle.EMPTY))
                .add(SessionCommand(COMMAND_LOAD_QUEUE, Bundle.EMPTY))
                .build()
            return MediaSession.ConnectionResult.accept(
                sessionCommands,
                MediaSession.ConnectionResult.DEFAULT_PLAYER_COMMANDS
            )
        }

        override fun onCustomCommand(
            session: MediaSession,
            controller: MediaSession.ControllerInfo,
            customCommand: SessionCommand,
            args: Bundle
        ): ListenableFuture<SessionResult> {
            when (customCommand.customAction) {
                COMMAND_NEXT_EPISODE -> next()
                COMMAND_PREVIOUS_EPISODE -> previous()
                COMMAND_LOAD_QUEUE -> {
                    val episodes = BundleCompat.getParcelableArrayList(
                        args, ARG_EPISODES, EpisodeSummary::class.java
                    ) ?: arrayListOf()
                    loadQueue(episodes, args.getInt(ARG_START_INDEX), args.getBoolean(ARG_AUTO_PLAY))
                }
            }
            return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
        }

        override fun onGetLibraryRoot(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            params: LibraryParams?
        ): ListenableFuture<LibraryResult<MediaItem>> {
            val rootItem = MediaItem.Builder()
                .setMediaId(ROOT_MEDIA_ID)
                .setMediaMetadata(
                    MediaMetadata.Builder()
                        .setIsBrowsable(false)
                        .setIsPlayable(false)
                        .build()
                )
                .build()
            return Futures.immediateFuture(LibraryResult.ofItem(rootItem, params))
        }

        override fun onGetChildren(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            parentId: String,
            page: Int,
            pageSize: Int,
            params: LibraryParams?
        ): ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> {
            return Futures.immediateFuture(LibraryResult.ofItemList(ImmutableList.of(), params))
        }
    }
}
```

- [ ] **Step 3: Update the manifest**

Replace the whole file `android-app/app/src/main/AndroidManifest.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <!-- Needed for the GitHub Releases API poll and streaming episode audio (EpisodeRepository). -->
    <uses-permission android:name="android.permission.INTERNET" />

    <!-- Needed for PlaybackService to run as a foreground service while playing in the
         background (lock screen, other apps open, screen off), and for Android Auto. -->
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />

    <application
        android:allowBackup="true"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher_round"
        android:label="@string/app_name"
        android:theme="@style/Theme.DailyTechUpdates">

        <!-- Declares this as a media app so Android Auto can discover it - see
             res/xml/automotive_app_desc.xml. -->
        <meta-data
            android:name="com.google.android.gms.car.application"
            android:resource="@xml/automotive_app_desc" />

        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <activity
            android:name=".HistoryActivity"
            android:exported="false" />

        <service
            android:name=".PlaybackService"
            android:foregroundServiceType="mediaPlayback"
            android:exported="true">
            <intent-filter>
                <action android:name="androidx.media3.session.MediaSessionService" />
                <action android:name="android.media.browse.MediaBrowserService" />
            </intent-filter>
        </service>

    </application>
</manifest>
```

- [ ] **Step 4: Run the existing test suite to confirm it still compiles and passes**

Run: `gradle testDebugUnitTest`

- [ ] **Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlaybackService.kt android-app/app/src/main/res/xml/automotive_app_desc.xml android-app/app/src/main/AndroidManifest.xml
git commit -m "Add PlaybackService: MediaLibraryService for background playback and Android Auto discovery"
```

---

### Task 3: Refactor `PlayerManager` into a `MediaController` client; update `MainActivity`/`HistoryActivity`

**Files:**
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt`
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt`
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt`
- Test: `android-app/app/src/test/java/com/shahbaz/dailytechupdates/PlayerManagerTest.kt` (unchanged — confirms `nextIndex`/`previousIndex`/`clampSeek`/`formatTime` still behave identically after the refactor)

**Interfaces:**
- Consumes: `PlaybackService` (Task 2) and its custom-command protocol constants (`COMMAND_NEXT_EPISODE`, `COMMAND_PREVIOUS_EPISODE`, `COMMAND_LOAD_QUEUE`, `ARG_EPISODES`, `ARG_START_INDEX`, `ARG_AUTO_PLAY`, `EXTRA_TOPICS`, `EXTRA_HAS_NEXT`, `EXTRA_HAS_PREVIOUS`); `EpisodeSummary` (Task 1, now `Parcelable`).
- Produces: `PlayerManager`'s public functions keep their existing exact names/signatures (`init(context)`, `currentEpisode(): EpisodeSummary?`, `loadQueue(episodes, startIndex, autoPlay)`, `togglePlayPause()`, `seekTo(positionMs)`, `skipForward15()`, `skipBackward15()`, `next()`, `previous()`, `addListener(listener)`, `removeListener(listener)`) — `PlayerBarBinder` needs no changes at all. `enterForeground()`/`leaveForeground()` are deleted (that pause-on-background behavior is exactly what this feature removes); `MainActivity`/`HistoryActivity` drop their calls to those two.

No automated test beyond re-running the existing `PlayerManagerTest.kt` (its four pure functions are untouched by this refactor — this step exists to prove that, and to prove the whole module still compiles with `PlayerManager`'s internals rewritten).

- [ ] **Step 1: Rewrite `PlayerManager.kt`**

Replace the whole file `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import android.content.ComponentName
import android.content.Context
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.MoreExecutors

/**
 * The queue is newest-first (index 0 = today). "Next" means chronologically newer
 * (toward index 0); "Previous" means chronologically older (toward the end of the list).
 * Both return null at their respective boundary rather than wrapping around.
 */
fun nextIndex(currentIndex: Int, size: Int): Int? =
    if (currentIndex > 0) currentIndex - 1 else null

fun previousIndex(currentIndex: Int, size: Int): Int? =
    if (currentIndex < size - 1) currentIndex + 1 else null

/**
 * Clamps a seek to [0, durationMs]. If durationMs is unknown (negative, e.g. ExoPlayer's
 * C.TIME_UNSET before metadata loads), only the lower bound is enforced.
 */
fun clampSeek(currentMs: Long, deltaMs: Long, durationMs: Long): Long {
    val target = currentMs + deltaMs
    val upperBound = if (durationMs >= 0) durationMs else Long.MAX_VALUE
    return target.coerceIn(0, upperBound)
}

/** mm:ss. A negative `ms` (used as the "unknown" sentinel for duration) renders as "--:--". */
fun formatTime(ms: Long): String {
    if (ms < 0) return "--:--"
    val totalSeconds = ms / 1000
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return "%02d:%02d".format(minutes, seconds)
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

/**
 * App-side client for the shared PlaybackService: holds a MediaController instead of owning
 * an ExoPlayer directly, so playback lives in a foreground service and survives the app
 * backgrounding. MediaController implements the same Player interface ExoPlayer does, so this
 * object's public functions are unchanged from before this refactor - only their internals
 * swapped from calling the player directly to calling it through the controller. The queue
 * and current-episode state now live in PlaybackService; this class only mirrors what the
 * controller reports (via MediaMetadata.extras - see PlaybackService.playCurrent()).
 */
object PlayerManager {

    private var controller: MediaController? = null
    private val listeners = mutableListOf<PlayerStateListener>()

    private val positionHandler = Handler(Looper.getMainLooper())
    private var positionRunnable: Runnable? = null

    fun init(context: Context) {
        if (controller != null) return
        val appContext = context.applicationContext
        val sessionToken = SessionToken(appContext, ComponentName(appContext, PlaybackService::class.java))
        val controllerFuture = MediaController.Builder(appContext, sessionToken).buildAsync()
        controllerFuture.addListener(
            {
                controller = controllerFuture.get()
                controller?.addListener(object : Player.Listener {
                    override fun onIsPlayingChanged(isPlaying: Boolean) {
                        if (isPlaying) startPositionUpdates() else stopPositionUpdates()
                        notifyListeners()
                    }

                    override fun onPlaybackStateChanged(playbackState: Int) {
                        notifyListeners()
                    }

                    override fun onMediaMetadataChanged(mediaMetadata: MediaMetadata) {
                        notifyListeners()
                    }
                })
                notifyListeners()
            },
            MoreExecutors.directExecutor()
        )
    }

    fun currentEpisode(): EpisodeSummary? {
        val c = controller ?: return null
        if (c.currentMediaItem == null) return null
        return episodeFromMetadata(c.mediaMetadata)
    }

    /** Forwards the queue to PlaybackService, which owns the actual queue/index state and is
     * responsible for the no-op-if-unchanged check (matching the old single-process check,
     * now done inside the service since that's where the state lives). */
    fun loadQueue(episodes: List<EpisodeSummary>, startIndex: Int, autoPlay: Boolean) {
        val c = controller ?: return
        val args = Bundle().apply {
            putParcelableArrayList(ARG_EPISODES, ArrayList(episodes))
            putInt(ARG_START_INDEX, startIndex)
            putBoolean(ARG_AUTO_PLAY, autoPlay)
        }
        c.sendCustomCommand(SessionCommand(COMMAND_LOAD_QUEUE, Bundle.EMPTY), args)
    }

    fun togglePlayPause() {
        val c = controller ?: return
        if (c.isPlaying) c.pause() else c.play()
    }

    fun seekTo(positionMs: Long) {
        controller?.seekTo(positionMs)
    }

    fun skipForward15() {
        controller?.seekForward()
    }

    fun skipBackward15() {
        controller?.seekBack()
    }

    fun next() {
        controller?.sendCustomCommand(SessionCommand(COMMAND_NEXT_EPISODE, Bundle.EMPTY), Bundle.EMPTY)
    }

    fun previous() {
        controller?.sendCustomCommand(SessionCommand(COMMAND_PREVIOUS_EPISODE, Bundle.EMPTY), Bundle.EMPTY)
    }

    fun addListener(listener: PlayerStateListener) {
        listeners.add(listener)
        notifyListener(listener)
    }

    fun removeListener(listener: PlayerStateListener) {
        listeners.remove(listener)
    }

    private fun startPositionUpdates() {
        stopPositionUpdates()
        val runnable = object : Runnable {
            override fun run() {
                notifyListeners()
                positionHandler.postDelayed(this, 500L)
            }
        }
        positionRunnable = runnable
        positionHandler.post(runnable)
    }

    private fun stopPositionUpdates() {
        positionRunnable?.let { positionHandler.removeCallbacks(it) }
        positionRunnable = null
    }

    private fun notifyListeners() {
        listeners.forEach { notifyListener(it) }
    }

    private fun notifyListener(listener: PlayerStateListener) {
        val c = controller
        listener.onStateChanged(
            episode = if (c?.currentMediaItem != null) episodeFromMetadata(c.mediaMetadata) else null,
            isPlaying = c?.isPlaying ?: false,
            positionMs = c?.currentPosition ?: 0L,
            durationMs = c?.duration ?: -1L,
            hasNext = c?.mediaMetadata?.extras?.getBoolean(EXTRA_HAS_NEXT) ?: false,
            hasPrevious = c?.mediaMetadata?.extras?.getBoolean(EXTRA_HAS_PREVIOUS) ?: false
        )
    }

    /** Reconstructs just enough of an EpisodeSummary for display: date and topics, read back
     * from the MediaMetadata PlaybackService.playCurrent() attaches to the current MediaItem.
     * audioUrl/transcriptUrl are always "" here - neither MainActivity's nor PlayerBarBinder's
     * onStateChanged reads them; they only ever mattered inside PlaybackService, for resolving
     * the playback URI, which now happens entirely inside the service. */
    private fun episodeFromMetadata(metadata: MediaMetadata): EpisodeSummary {
        val topics = metadata.extras?.getStringArrayList(EXTRA_TOPICS)?.toList() ?: emptyList()
        return EpisodeSummary(
            date = metadata.title?.toString() ?: "",
            topicsCovered = topics,
            audioUrl = "",
            transcriptUrl = ""
        )
    }
}
```

- [ ] **Step 2: Update `MainActivity.kt`**

In `android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt`, replace the `onStart`/`onStop` pair:

```kotlin
    override fun onStart() {
        super.onStart()
        PlayerManager.enterForeground()
        PlayerManager.addListener(this)
        playerBarBinder.start()
    }

    override fun onStop() {
        playerBarBinder.stop()
        PlayerManager.removeListener(this)
        PlayerManager.leaveForeground()
        super.onStop()
    }
```

with:

```kotlin
    override fun onStart() {
        super.onStart()
        PlayerManager.addListener(this)
        playerBarBinder.start()
    }

    override fun onStop() {
        playerBarBinder.stop()
        PlayerManager.removeListener(this)
        super.onStop()
    }
```

- [ ] **Step 3: Update `HistoryActivity.kt`**

In `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt`, replace the `onStart`/`onStop` pair:

```kotlin
    override fun onStart() {
        super.onStart()
        PlayerManager.enterForeground()
        playerBarBinder.start()
    }

    override fun onStop() {
        playerBarBinder.stop()
        PlayerManager.leaveForeground()
        super.onStop()
    }
```

with:

```kotlin
    override fun onStart() {
        super.onStart()
        playerBarBinder.start()
    }

    override fun onStop() {
        playerBarBinder.stop()
        super.onStop()
    }
```

- [ ] **Step 4: Run the existing test suite to confirm it still compiles and passes**

Run: `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.PlayerManagerTest"` then the full suite: `gradle testDebugUnitTest`.
Expected: all pre-existing tests (including `PlayerManagerTest`'s 11 cases, unchanged) still PASS — this proves the refactor didn't alter `nextIndex`/`previousIndex`/`clampSeek`/`formatTime` behavior.

- [ ] **Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt
git commit -m "Refactor PlayerManager into a MediaController client; drop pause-on-background"
```

---

### Task 4: Manual on-device verification — background playback

**Files:** none (verification only).

- [ ] **Step 1: Build and install**

Run: `gradle installDebug` (from `android-app/`)

- [ ] **Step 2: Verify playback starts and the notification appears**

Launch the app, play today's episode. Confirm a media notification appears (small icon, date as title, play/pause, ±15s, previous/next-episode buttons) and that the seek bar in `player_bar.xml` and the notification's progress stay in sync.

- [ ] **Step 3: Verify background playback**

While playing, press Home (backgrounding the app without swiping it from recents). Confirm audio keeps playing. Lock the screen; confirm audio keeps playing and the lock-screen media control shows the same episode/controls. Use the notification's play/pause and ±15s buttons while backgrounded; confirm they work and reopening the app shows the same, now-updated state in `player_bar.xml`.

- [ ] **Step 4: Verify next/previous from the notification**

From the notification (or lock screen), tap previous/next-episode. Confirm it switches episodes correctly (matching the existing in-app next/previous semantics — next = newer, previous = older, disabled at the queue's boundaries) and the notification's title updates.

- [ ] **Step 5: Verify task-removal behavior**

Start playback, then swipe the app away from the recent-apps list. Confirm playback **continues** (foreground service). Pause playback, then swipe the app away from recents again. Confirm playback stops and the notification disappears (service stops itself when not playing, per `MediaSessionService`'s default `onTaskRemoved` behavior).

- [ ] **Step 6: Report results**

Report pass/fail for each of Steps 2–5.

---

### Task 5: Manual verification — Android Auto

**Files:** none (verification only).

This project has no physical-car-dependent automated tests (Android Auto integration can't run in CI). Verify by hand, using either a real car head unit or Android Auto's Desktop Head Unit (DHU) emulator (installed via Android Studio's SDK Manager → SDK Tools → "Android Auto Desktop Head Unit", no car required) — whichever is convenient. If neither is available, report that explicitly as an unverified concern rather than skipping verification silently.

- [ ] **Step 1: Connect**

Connect the phone to Android Auto (real car, or run the DHU against a phone/emulator with the Android Auto app installed and "developer mode" head unit enabled per Google's Android Auto testing docs). Confirm "Daily Tech Updates" appears as an available media app/source.

- [ ] **Step 2: Verify playback mirrors into the car**

Start playback on the phone before or after connecting. Confirm the car screen shows the "now playing" transport UI: episode date as the title, play/pause, ±15s skip, and previous/next-episode buttons — matching the approved design's scope (no browsable episode list in the car).

- [ ] **Step 3: Verify controls from the car**

Tap each control from the car's screen (play/pause, ±15s, previous/next-episode) and confirm playback responds correctly and the car's displayed state (title, play/pause icon) updates.

- [ ] **Step 4: Verify no crash on connect with nothing loaded**

Force-stop the app, connect to Android Auto first (before opening the app at all), and confirm the car doesn't crash or show a broken/error UI even with no episode loaded yet — this is exercising `onGetLibraryRoot`/`onGetChildren`'s empty-tree response.

- [ ] **Step 5: Report results**

Report pass/fail for each of Steps 1–4, and note whether verification used a real car or the DHU emulator.
