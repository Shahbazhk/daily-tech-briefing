package com.shahbaz.dailytechupdates

import android.app.PendingIntent
import android.content.Intent
import android.os.Bundle
import androidx.core.os.BundleCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.CommandButton
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
            .setCustomLayout(
                ImmutableList.of(
                    CommandButton.Builder(CommandButton.ICON_PREVIOUS)
                        .setSessionCommand(SessionCommand(COMMAND_PREVIOUS_EPISODE, Bundle.EMPTY))
                        .setDisplayName("Previous episode")
                        .build(),
                    CommandButton.Builder(CommandButton.ICON_NEXT)
                        .setSessionCommand(SessionCommand(COMMAND_NEXT_EPISODE, Bundle.EMPTY))
                        .setDisplayName("Next episode")
                        .build()
                )
            )
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
                        .setIsBrowsable(true)
                        .setIsPlayable(false)
                        .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_MIXED)
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
