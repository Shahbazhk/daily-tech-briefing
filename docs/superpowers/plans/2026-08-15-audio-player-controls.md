# Audio Player Controls Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single Play/Pause button (MainActivity-only, no History playback UI at all) with a real transport bar — seek/progress, ±15s skip, next/previous across the full episode history — backed by one player shared across `MainActivity` and `HistoryActivity` so playback survives navigating between them.

**Architecture:** A new `PlayerManager` singleton object owns the one shared `ExoPlayer` instance, the current episode queue, and a small `PlayerStateListener` callback mechanism. A new reusable `player_bar.xml` layout (wired by a new `PlayerBarBinder` helper) is `<include>`-d at the bottom of both activities' layouts. Both activities drop their own per-activity `ExoPlayer` entirely and delegate all playback to `PlayerManager`.

**Tech Stack:** Kotlin, AndroidX ExoPlayer (`androidx.media3`, already a dependency — no new dependencies), View Binding, JUnit4 (existing `app/src/test` source set).

## Global Constraints

- No new third-party dependencies — built entirely on ExoPlayer (already present) and stock Android views (`SeekBar`, `Button`).
- No background/lock-screen playback (no foreground service, no media notification) — explicitly out of scope. Playback must actively **stop** (not silently keep playing) once no activity of this app is in the foreground — see Task 2's foreground-tracking mechanism, added during planning to make this actually true once playback moves to an app-level singleton.
- Next = chronologically **newer** episode (index − 1, toward today, index 0). Previous = chronologically **older** (index + 1). Buttons disable at queue boundaries — no wraparound.
- Seek bar only calls `seekTo` on `onStopTrackingTouch`, never mid-drag.
- Pure boundary/formatting logic (`nextIndex`, `previousIndex`, `clampSeek`, `formatTime`) is unit-tested on the JVM (no Robolectric). ExoPlayer/View-Binding-dependent code is not unit-tested — verified by `gradle testDebugUnitTest` (compiles + doesn't break existing tests) plus manual on-device verification in the final task, matching how `DownloadStore`'s Android-dependent parts and both activities are verified today.
- `formatTime(ms)` clarification vs. the design doc's slightly loose wording: the threshold is `ms < 0` (not `<= 0`) — position `0` must format as `"00:00"` (start of a real episode), while an *unknown* duration is represented by passing a negative sentinel (e.g. `-1`), which formats as `"--:--"`. This resolves an internal contradiction in the design doc's two example test cases (`0 → "00:00"` vs. `<=0 duration → "--:--"`).

---

### Task 1: Pure player-math functions + unit tests

**Files:**
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt` (this task only adds the top-level pure functions to this file — the `PlayerManager` object itself is Task 2)
- Test: `android-app/app/src/test/java/com/shahbaz/dailytechupdates/PlayerManagerTest.kt`

**Interfaces:**
- Produces: `fun nextIndex(currentIndex: Int, size: Int): Int?`, `fun previousIndex(currentIndex: Int, size: Int): Int?`, `fun clampSeek(currentMs: Long, deltaMs: Long, durationMs: Long): Long`, `fun formatTime(ms: Long): String` — all top-level functions in package `com.shahbaz.dailytechupdates`, used by Task 2's `PlayerManager` object and Task 3's `PlayerBarBinder`.

- [ ] **Step 1: Write the failing tests**

Create `android-app/app/src/test/java/com/shahbaz/dailytechupdates/PlayerManagerTest.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PlayerManagerTest {

    @Test
    fun `nextIndex returns the index toward index 0 (newer)`() {
        assertEquals(1, nextIndex(2, 5))
    }

    @Test
    fun `nextIndex returns null at index 0 (nothing newer)`() {
        assertNull(nextIndex(0, 5))
    }

    @Test
    fun `previousIndex returns the index toward the end (older)`() {
        assertEquals(3, previousIndex(2, 5))
    }

    @Test
    fun `previousIndex returns null at the last index (nothing older)`() {
        assertNull(previousIndex(4, 5))
    }

    @Test
    fun `clampSeek keeps a normal seek within bounds unchanged`() {
        assertEquals(45_000L, clampSeek(30_000L, 15_000L, 120_000L))
    }

    @Test
    fun `clampSeek clamps to zero when seeking before the start`() {
        assertEquals(0L, clampSeek(10_000L, -20_000L, 120_000L))
    }

    @Test
    fun `clampSeek clamps to duration when seeking past the end`() {
        assertEquals(120_000L, clampSeek(110_000L, 15_000L, 120_000L))
    }

    @Test
    fun `clampSeek does not clamp the upper bound when duration is unknown`() {
        assertEquals(25_000L, clampSeek(10_000L, 15_000L, -1L))
    }

    @Test
    fun `formatTime formats zero as 00 00`() {
        assertEquals("00:00", formatTime(0L))
    }

    @Test
    fun `formatTime formats over a minute correctly`() {
        assertEquals("01:05", formatTime(65_000L))
    }

    @Test
    fun `formatTime shows a placeholder for a negative (unknown) value`() {
        assertEquals("--:--", formatTime(-1L))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `android-app/`): `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.PlayerManagerTest"`
Expected: FAIL — `PlayerManagerTest.kt` references `nextIndex`/`previousIndex`/`clampSeek`/`formatTime`, none of which exist yet (compile error).

- [ ] **Step 3: Write the minimal implementation**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt`:

```kotlin
package com.shahbaz.dailytechupdates

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.PlayerManagerTest"`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt android-app/app/src/test/java/com/shahbaz/dailytechupdates/PlayerManagerTest.kt
git commit -m "Add pure player-math functions (next/previous index, seek clamp, time format)"
```

---

### Task 2: `PlayerStateListener` + `PlayerManager` singleton (shared ExoPlayer)

**Files:**
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt` (adds the interface and object below Task 1's pure functions)

**Interfaces:**
- Consumes: `nextIndex`, `previousIndex`, `clampSeek` (Task 1); `EpisodeSummary` (existing); `DownloadStore.localPathFor(date): String?` (existing); `resolvePlaybackUri(audioUrl, localPath): String` (existing, in `PlaybackSource.kt`).
- Produces (used by Tasks 3, 4, 5):
  - `interface PlayerStateListener { fun onStateChanged(episode: EpisodeSummary?, isPlaying: Boolean, positionMs: Long, durationMs: Long, hasNext: Boolean, hasPrevious: Boolean) }`
  - `object PlayerManager` with: `fun init(context: Context)`, `fun loadQueue(episodes: List<EpisodeSummary>, startIndex: Int, autoPlay: Boolean)`, `fun currentEpisode(): EpisodeSummary?`, `fun togglePlayPause()`, `fun seekTo(positionMs: Long)`, `fun skipForward15()`, `fun skipBackward15()`, `fun next()`, `fun previous()`, `fun addListener(listener: PlayerStateListener)`, `fun removeListener(listener: PlayerStateListener)`, `fun enterForeground()`, `fun leaveForeground()`.

This task has no automated test — it depends on `ExoPlayer`, which needs the Android runtime and isn't available to plain JVM unit tests (same constraint `DownloadStore`'s Android-dependent parts already have). Verification is: it compiles, the existing test suite still passes, and it's exercised for real once Tasks 4–5 wire it into the activities (checked manually in Task 6).

- [ ] **Step 1: Add the interface and singleton to `PlayerManager.kt`**

Kotlin requires imports at the top of the file, so this step has two edits to
`android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt`:

First, insert these import lines immediately after the `package
com.shahbaz.dailytechupdates` line at the top of the file (before Task 1's
`nextIndex`/`previousIndex`/`clampSeek`/`formatTime` functions):

```kotlin
import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
```

Second, append the following at the very bottom of the file (below Task 1's
functions):

```kotlin
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
 * App-lifetime singleton owning the one shared ExoPlayer instance, so playback survives
 * navigating between MainActivity and HistoryActivity instead of each owning its own player.
 * Deliberately NOT a background/foreground service: enterForeground()/leaveForeground() pause
 * playback once no activity of this app is visible, keeping playback strictly in-app (no
 * lock-screen/notification controls) rather than accidentally gaining background playback
 * just by virtue of the player no longer being tied to a single activity's lifecycle.
 */
object PlayerManager {

    private lateinit var player: ExoPlayer
    private lateinit var downloadStore: DownloadStore
    private var initialized = false

    private var queue: List<EpisodeSummary> = emptyList()
    private var currentIndex: Int = -1
    private val listeners = mutableListOf<PlayerStateListener>()

    private var foregroundActivityCount = 0

    private val positionHandler = Handler(Looper.getMainLooper())
    private var positionRunnable: Runnable? = null

    fun init(context: Context) {
        if (initialized) return
        val appContext = context.applicationContext
        player = ExoPlayer.Builder(appContext).build()
        downloadStore = DownloadStore(appContext)
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                if (isPlaying) startPositionUpdates() else stopPositionUpdates()
                notifyListeners()
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                notifyListeners()
            }
        })
        initialized = true
    }

    fun currentEpisode(): EpisodeSummary? = queue.getOrNull(currentIndex)

    /** No-op if the same queue at the same index is already loaded, so reopening a screen
     * mid-playback doesn't restart the current episode. */
    fun loadQueue(episodes: List<EpisodeSummary>, startIndex: Int, autoPlay: Boolean) {
        if (startIndex !in episodes.indices) return
        if (queue == episodes && currentIndex == startIndex) return
        queue = episodes
        currentIndex = startIndex
        playCurrent(autoPlay)
    }

    private fun playCurrent(autoPlay: Boolean) {
        val episode = queue.getOrNull(currentIndex) ?: return
        val uri = resolvePlaybackUri(episode.audioUrl, downloadStore.localPathFor(episode.date))
        player.setMediaItem(MediaItem.fromUri(uri))
        player.prepare()
        if (autoPlay) player.play()
        notifyListeners()
    }

    fun togglePlayPause() {
        if (player.isPlaying) player.pause() else player.play()
    }

    fun seekTo(positionMs: Long) {
        player.seekTo(positionMs)
        notifyListeners()
    }

    fun skipForward15() = seekTo(clampSeek(player.currentPosition, 15_000, player.duration))

    fun skipBackward15() = seekTo(clampSeek(player.currentPosition, -15_000, player.duration))

    fun next() {
        val target = nextIndex(currentIndex, queue.size) ?: return
        currentIndex = target
        playCurrent(autoPlay = true)
    }

    fun previous() {
        val target = previousIndex(currentIndex, queue.size) ?: return
        currentIndex = target
        playCurrent(autoPlay = true)
    }

    fun addListener(listener: PlayerStateListener) {
        listeners.add(listener)
        notifyListener(listener)
    }

    fun removeListener(listener: PlayerStateListener) {
        listeners.remove(listener)
    }

    fun enterForeground() {
        foregroundActivityCount++
    }

    /** Once the last visible activity of this app stops, pause playback - this is what keeps
     * playback in-app-only now that the player is a singleton instead of tied to one activity's
     * onDestroy(). Deliberately pause (not release): returning to the app should be able to
     * resume from the same position, just not automatically. */
    fun leaveForeground() {
        foregroundActivityCount = (foregroundActivityCount - 1).coerceAtLeast(0)
        if (foregroundActivityCount == 0) {
            player.pause()
        }
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
        listener.onStateChanged(
            episode = queue.getOrNull(currentIndex),
            isPlaying = if (initialized) player.isPlaying else false,
            positionMs = if (initialized) player.currentPosition else 0L,
            durationMs = if (initialized) player.duration else -1L,
            hasNext = nextIndex(currentIndex, queue.size) != null,
            hasPrevious = previousIndex(currentIndex, queue.size) != null
        )
    }
}
```

- [ ] **Step 2: Run the existing test suite to confirm it still compiles and passes**

Run: `gradle testDebugUnitTest` (confirms the whole module — including Task 1's new tests and all pre-existing tests — still compiles and passes; there's no new automated test in this task).

- [ ] **Step 3: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerManager.kt
git commit -m "Add PlayerManager: shared ExoPlayer singleton with queue, transport controls, and foreground tracking"
```

---

### Task 3: `player_bar.xml` layout + `PlayerBarBinder`

**Files:**
- Create: `android-app/app/src/main/res/layout/player_bar.xml`
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerBarBinder.kt`
- Modify: `android-app/app/src/main/res/values/strings.xml`

**Interfaces:**
- Consumes: `PlayerManager` and `PlayerStateListener` (Task 2), `formatTime` (Task 1).
- Produces (used by Tasks 4, 5): `class PlayerBarBinder(binding: PlayerBarBinding) : PlayerStateListener` with `fun start()` (registers with `PlayerManager`) and `fun stop()` (unregisters). View Binding auto-generates `PlayerBarBinding` from `player_bar.xml`'s filename.

No automated test — this is UI glue (View/SeekBar), same as Task 2. Verified by compilation plus Task 6's manual pass.

- [ ] **Step 1: Add new strings**

In `android-app/app/src/main/res/values/strings.xml`, add these four lines inside `<resources>`, anywhere after the existing `pause` string:

```xml
    <string name="previous">⏮</string>
    <string name="skip_backward_15">-15s</string>
    <string name="skip_forward_15">+15s</string>
    <string name="next">⏭</string>
```

- [ ] **Step 2: Create the player bar layout**

Create `android-app/app/src/main/res/layout/player_bar.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:orientation="vertical"
    android:paddingHorizontal="16dp"
    android:paddingVertical="8dp"
    android:background="?android:attr/colorBackground">

    <TextView
        android:id="@+id/playerEpisodeLabel"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:textSize="12sp"
        android:textColor="?android:attr/textColorSecondary" />

    <LinearLayout
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:orientation="horizontal"
        android:gravity="center_vertical">

        <SeekBar
            android:id="@+id/playerSeekBar"
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="1" />

        <TextView
            android:id="@+id/playerPositionText"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:layout_marginStart="8dp"
            android:textSize="12sp" />
    </LinearLayout>

    <LinearLayout
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:orientation="horizontal"
        android:gravity="center">

        <Button
            android:id="@+id/playerPreviousButton"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:text="@string/previous" />

        <Button
            android:id="@+id/playerSkipBackButton"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:text="@string/skip_backward_15" />

        <Button
            android:id="@+id/playerPlayPauseButton"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:text="@string/play" />

        <Button
            android:id="@+id/playerSkipForwardButton"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:text="@string/skip_forward_15" />

        <Button
            android:id="@+id/playerNextButton"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:text="@string/next" />

    </LinearLayout>

</LinearLayout>
```

- [ ] **Step 3: Create `PlayerBarBinder`**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerBarBinder.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import android.widget.SeekBar
import com.shahbaz.dailytechupdates.databinding.PlayerBarBinding

/** Wires one player_bar.xml (included in both MainActivity and HistoryActivity) to
 * PlayerManager. Registers/unregisters itself as a PlayerStateListener via start()/stop(),
 * called from each host activity's onStart()/onStop(). */
class PlayerBarBinder(private val binding: PlayerBarBinding) : PlayerStateListener {

    init {
        binding.playerPreviousButton.setOnClickListener { PlayerManager.previous() }
        binding.playerSkipBackButton.setOnClickListener { PlayerManager.skipBackward15() }
        binding.playerPlayPauseButton.setOnClickListener { PlayerManager.togglePlayPause() }
        binding.playerSkipForwardButton.setOnClickListener { PlayerManager.skipForward15() }
        binding.playerNextButton.setOnClickListener { PlayerManager.next() }
        binding.playerSeekBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar, progress: Int, fromUser: Boolean) {}
            override fun onStartTrackingTouch(seekBar: SeekBar) {}
            override fun onStopTrackingTouch(seekBar: SeekBar) {
                PlayerManager.seekTo(seekBar.progress.toLong())
            }
        })
    }

    fun start() {
        PlayerManager.addListener(this)
    }

    fun stop() {
        PlayerManager.removeListener(this)
    }

    override fun onStateChanged(
        episode: EpisodeSummary?,
        isPlaying: Boolean,
        positionMs: Long,
        durationMs: Long,
        hasNext: Boolean,
        hasPrevious: Boolean
    ) {
        val context = binding.root.context
        binding.playerEpisodeLabel.text = episode?.date ?: ""
        binding.playerPlayPauseButton.text =
            context.getString(if (isPlaying) R.string.pause else R.string.play)

        val durationForSeekBar = if (durationMs > 0) durationMs.toInt() else 0
        binding.playerSeekBar.max = durationForSeekBar
        binding.playerSeekBar.progress = positionMs.toInt().coerceIn(0, durationForSeekBar)

        val durationLabel = if (durationMs > 0) durationMs else -1L
        binding.playerPositionText.text = "${formatTime(positionMs)} / ${formatTime(durationLabel)}"

        binding.playerPreviousButton.isEnabled = hasPrevious
        binding.playerNextButton.isEnabled = hasNext
    }
}
```

- [ ] **Step 4: Run the existing test suite to confirm it still compiles and passes**

Run: `gradle testDebugUnitTest` — confirms the module (including all Kotlin added so far) still compiles cleanly; no new tests in this task.

- [ ] **Step 5: Commit**

```bash
git add android-app/app/src/main/res/layout/player_bar.xml android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlayerBarBinder.kt android-app/app/src/main/res/values/strings.xml
git commit -m "Add reusable player_bar layout and PlayerBarBinder"
```

---

### Task 4: Wire `MainActivity` to the shared player

**Files:**
- Modify: `android-app/app/src/main/res/layout/activity_main.xml`
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt`

**Interfaces:**
- Consumes: `PlayerManager`, `PlayerStateListener` (Task 2); `PlayerBarBinder` (Task 3); `EpisodeRepository.getEpisodeHistory(context): List<EpisodeSummary>` (existing, in `EpisodeRepository.kt`).

No automated test — verified by compilation now, manually on-device in Task 6.

- [ ] **Step 1: Update `activity_main.xml`**

Replace the whole file (`android-app/app/src/main/res/layout/activity_main.xml`) — this removes the old `playPauseButton` and adds the `player_bar` include pinned to the bottom:

```xml
<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:padding="24dp">

    <TextView
        android:id="@+id/dateText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:textSize="14sp"
        android:textColor="?android:attr/textColorSecondary"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent" />

    <Button
        android:id="@+id/historyButton"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="@string/history"
        android:textSize="12sp"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintEnd_toEndOf="parent" />

    <TextView
        android:id="@+id/topicsText"
        android:layout_width="0dp"
        android:layout_height="wrap_content"
        android:layout_marginTop="8dp"
        android:textSize="20sp"
        android:textStyle="bold"
        app:layout_constraintTop_toBottomOf="@id/dateText"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent" />

    <TextView
        android:id="@+id/statusText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:layout_marginTop="16dp"
        app:layout_constraintTop_toBottomOf="@id/topicsText"
        app:layout_constraintStart_toStartOf="parent" />

    <include
        android:id="@+id/playerBar"
        layout="@layout/player_bar"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent" />

</androidx.constraintlayout.widget.ConstraintLayout>
```

- [ ] **Step 2: Rewrite `MainActivity.kt`**

Replace the whole file (`android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt`):

```kotlin
package com.shahbaz.dailytechupdates

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.shahbaz.dailytechupdates.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity(), PlayerStateListener {

    private lateinit var binding: ActivityMainBinding
    private lateinit var playerBarBinder: PlayerBarBinder
    private val repository = EpisodeRepository()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        PlayerManager.init(applicationContext)
        playerBarBinder = PlayerBarBinder(binding.playerBar)

        binding.statusText.setOnClickListener { loadTodayEpisode() }
        binding.historyButton.setOnClickListener {
            startActivity(Intent(this, HistoryActivity::class.java))
        }

        loadTodayEpisode()
    }

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

    private fun loadTodayEpisode() {
        binding.statusText.text = getString(R.string.loading_episode)
        lifecycleScope.launch {
            val history = try {
                repository.getEpisodeHistory(applicationContext)
            } catch (e: Exception) {
                emptyList()
            }
            val today = history.firstOrNull()
            if (today == null || today.audioUrl.isEmpty()) {
                binding.statusText.text = getString(R.string.no_episode_yet)
                return@launch
            }
            binding.statusText.text = getString(R.string.ready_to_play)
            // Only seed the queue on the very first load in this process - if PlayerManager
            // already has something loaded (e.g. the user navigated here after using Next/
            // Previous from History), don't reset playback back to today.
            if (PlayerManager.currentEpisode() == null) {
                PlayerManager.loadQueue(history, startIndex = 0, autoPlay = false)
            }
        }
    }

    override fun onStateChanged(
        episode: EpisodeSummary?,
        isPlaying: Boolean,
        positionMs: Long,
        durationMs: Long,
        hasNext: Boolean,
        hasPrevious: Boolean
    ) {
        if (episode == null) return
        binding.dateText.text = episode.date
        binding.topicsText.text = episode.topicsCovered.joinToString(" • ")
    }
}
```

- [ ] **Step 3: Run the existing test suite to confirm it still compiles and passes**

Run: `gradle testDebugUnitTest` — confirms the whole module compiles and all prior unit tests still pass.

- [ ] **Step 4: Commit**

```bash
git add android-app/app/src/main/res/layout/activity_main.xml android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt
git commit -m "Wire MainActivity to the shared PlayerManager and player bar"
```

---

### Task 5: Wire `HistoryActivity` to the shared player

**Files:**
- Modify: `android-app/app/src/main/res/layout/activity_history.xml`
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt`

**Interfaces:**
- Consumes: `PlayerManager` (Task 2); `PlayerBarBinder` (Task 3); existing `DownloadStore`, `HistoryAdapter`, `EpisodeRepository.getEpisodeHistory()`.

No automated test — verified by compilation now, manually on-device in Task 6.

- [ ] **Step 1: Update `activity_history.xml`**

Replace the whole file (`android-app/app/src/main/res/layout/activity_history.xml`) — adds the `player_bar` include, and re-anchors `historyList`/`emptyText`'s bottom to sit above it instead of the screen bottom:

```xml
<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="match_parent">

    <androidx.recyclerview.widget.RecyclerView
        android:id="@+id/historyList"
        android:layout_width="0dp"
        android:layout_height="0dp"
        android:padding="16dp"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintBottom_toTopOf="@id/playerBar" />

    <TextView
        android:id="@+id/emptyText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:padding="24dp"
        android:text="@string/history_unavailable"
        android:visibility="gone"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintBottom_toTopOf="@id/playerBar" />

    <include
        android:id="@+id/playerBar"
        layout="@layout/player_bar"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent" />

</androidx.constraintlayout.widget.ConstraintLayout>
```

- [ ] **Step 2: Rewrite `HistoryActivity.kt`**

Replace the whole file (`android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt`):

```kotlin
package com.shahbaz.dailytechupdates

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.shahbaz.dailytechupdates.databinding.ActivityHistoryBinding
import kotlinx.coroutines.launch

class HistoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoryBinding
    private lateinit var playerBarBinder: PlayerBarBinder
    private lateinit var downloadStore: DownloadStore
    private lateinit var adapter: HistoryAdapter
    private val repository = EpisodeRepository()
    private var history: List<EpisodeSummary> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHistoryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        PlayerManager.init(applicationContext)
        playerBarBinder = PlayerBarBinder(binding.playerBar)
        downloadStore = DownloadStore(applicationContext)
        downloadStore.purgeExpired()

        adapter = HistoryAdapter(
            onPlay = { episode -> play(episode) },
            onDownload = { episode -> download(episode) }
        )
        binding.historyList.layoutManager = LinearLayoutManager(this)
        binding.historyList.adapter = adapter

        loadHistory()
    }

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

    override fun onDestroy() {
        downloadStore.unregister()
        super.onDestroy()
    }

    private fun loadHistory() {
        lifecycleScope.launch {
            val result = try {
                repository.getEpisodeHistory(applicationContext)
            } catch (e: Exception) {
                emptyList()
            }
            history = result
            if (history.isEmpty()) {
                binding.emptyText.visibility = View.VISIBLE
                binding.historyList.visibility = View.GONE
                return@launch
            }
            binding.emptyText.visibility = View.GONE
            binding.historyList.visibility = View.VISIBLE
            val downloadedDates = history.filter { downloadStore.localPathFor(it.date) != null }.map { it.date }.toSet()
            adapter.submitList(history, downloadedDates)
        }
    }

    private fun play(episode: EpisodeSummary) {
        val index = history.indexOf(episode)
        if (index == -1) return
        PlayerManager.loadQueue(history, startIndex = index, autoPlay = true)
    }

    private fun download(episode: EpisodeSummary) {
        if (episode.audioUrl.isEmpty()) return
        adapter.markDownloading(episode.date)
        downloadStore.startDownload(episode.date, episode.audioUrl) { success ->
            runOnUiThread { adapter.markResult(episode.date, success) }
        }
    }
}
```

Note: `downloadStore.unregister()` moved to `onDestroy()` (unchanged from before) — this is unrelated to `PlayerManager` and keeps working exactly as it did.

- [ ] **Step 3: Run the existing test suite to confirm it still compiles and passes**

Run: `gradle testDebugUnitTest` — confirms the whole module compiles and all prior unit tests still pass.

- [ ] **Step 4: Commit**

```bash
git add android-app/app/src/main/res/layout/activity_history.xml android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt
git commit -m "Wire HistoryActivity to the shared PlayerManager and player bar"
```

---

### Task 6: Manual on-device verification

**Files:** none (verification only).

This feature has no instrumentation-test infrastructure (same as the rest of the app's UI — see Global Constraints). If a device or emulator is available, verify by hand; if not, note that explicitly as a concern rather than skipping verification silently.

- [ ] **Step 1: Build and install**

Run: `gradle installDebug` (from `android-app/`)

- [ ] **Step 2: Verify MainActivity**

Launch the app. Confirm: today's episode loads (date/topics show), the player bar appears at the bottom showing today's date, tapping ▶ starts playback and the seek bar begins advancing, tapping ⏸ pauses it, ⏮ is disabled (today is the newest episode — nothing newer), ⏭ is enabled if there's an older episode in history to go to... wait — re-read: ⏮ is Previous (older, should be enabled if history has more than one episode) and ⏭ is Next (newer, disabled at today since nothing is newer). Confirm ±15s buttons move the seek bar by roughly 15 seconds each tap, clamped at 0 and at the end.

- [ ] **Step 3: Verify cross-screen persistence**

While an episode is playing on MainActivity, tap History. Confirm the player bar is still showing the same episode, still playing, seek position continuing from where it was (not reset) — this is the main behavior this feature adds over the old per-activity players.

- [ ] **Step 4: Verify History screen playback + Next/Previous**

Tap an older row's title/date (not the download icon) to play it. Confirm the player bar updates to that episode. Tap Previous (⏮) repeatedly to walk toward older episodes, confirming the episode label and seek bar reset for each new episode, and that it's disabled once at the oldest available episode. Tap Next (⏭) back toward today, confirming it's disabled again once back at today's episode. Confirm downloaded (✓) rows still play from local storage (unaffected by this feature) and stream-only rows still play by streaming.

- [ ] **Step 5: Verify in-app-only lifecycle**

Start playback, then press the device Home button (backgrounding the app without closing it). Confirm playback pauses (via `PlayerManager.leaveForeground()`). Reopen the app (tap its icon/recent-apps entry) and confirm it does **not** auto-resume — the play button should show "Play", and tapping it resumes from the same position.

- [ ] **Step 6: Report results**

If a device/emulator was available, report pass/fail for each of Steps 2–5. If no device/emulator was available, report that explicitly as an unverified concern rather than claiming success.
