package com.shahbaz.dailytechupdates

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import com.shahbaz.dailytechupdates.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var player: ExoPlayer
    private lateinit var downloadStore: DownloadStore
    private val repository = EpisodeRepository()
    private var isPlaying = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        player = ExoPlayer.Builder(this).build()
        downloadStore = DownloadStore(applicationContext)
        downloadStore.purgeExpired()

        binding.playPauseButton.setOnClickListener { togglePlayback() }
        binding.statusText.setOnClickListener { loadTodayEpisode() }
        binding.historyButton.setOnClickListener {
            startActivity(Intent(this, HistoryActivity::class.java))
        }

        loadTodayEpisode()
    }

    private fun loadTodayEpisode() {
        binding.statusText.text = getString(R.string.loading_episode)
        lifecycleScope.launch {
            val episode = try {
                repository.getLatestEpisode()
            } catch (e: Exception) {
                null
            }
            if (episode == null || episode.audioUrl.isEmpty()) {
                binding.statusText.text = getString(R.string.no_episode_yet)
                return@launch
            }
            binding.dateText.text = episode.date
            binding.topicsText.text = episode.topicsCovered.joinToString(" • ")
            binding.statusText.text = getString(R.string.ready_to_play)
            val uri = resolvePlaybackUri(episode.audioUrl, downloadStore.localPathFor(episode.date))
            player.setMediaItem(MediaItem.fromUri(uri))
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
        downloadStore.unregister()
        super.onDestroy()
    }
}
