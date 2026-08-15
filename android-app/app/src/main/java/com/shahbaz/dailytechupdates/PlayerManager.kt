package com.shahbaz.dailytechupdates

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer

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
