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
