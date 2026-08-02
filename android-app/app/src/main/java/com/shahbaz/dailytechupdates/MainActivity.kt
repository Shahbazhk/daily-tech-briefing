package com.shahbaz.dailytechupdates

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import com.google.firebase.messaging.FirebaseMessaging
import com.shahbaz.dailytechupdates.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var player: ExoPlayer
    private val repository = EpisodeRepository()
    private var isPlaying = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        player = ExoPlayer.Builder(this).build()

        // Every install subscribes here; publish/publish.py pushes to this topic once
        // the episode is ready (see FcmService).
        FirebaseMessaging.getInstance().subscribeToTopic("daily_episode")

        binding.playPauseButton.setOnClickListener { togglePlayback() }

        loadTodayEpisode()
    }

    private fun loadTodayEpisode() {
        binding.statusText.text = getString(R.string.loading_episode)
        lifecycleScope.launch {
            val episode = repository.getLatestEpisode()
            if (episode == null || episode.audioUrl.isEmpty()) {
                binding.statusText.text = getString(R.string.no_episode_yet)
                return@launch
            }
            binding.dateText.text = episode.date
            binding.topicsText.text = episode.topicsCovered.joinToString(" • ")
            binding.statusText.text = getString(R.string.ready_to_play)
            player.setMediaItem(MediaItem.fromUri(episode.audioUrl))
            player.prepare()
        }
    }

    private fun togglePlayback() {
        isPlaying = !isPlaying
        if (isPlaying) {
            player.play()
            binding.playPauseButton.text = getString(R.string.pause)
        } else {
            player.pause()
            binding.playPauseButton.text = getString(R.string.play)
        }
    }

    override fun onDestroy() {
        player.release()
        super.onDestroy()
    }
}
