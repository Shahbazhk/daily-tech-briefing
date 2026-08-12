package com.shahbaz.dailytechupdates

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.recyclerview.widget.LinearLayoutManager
import com.shahbaz.dailytechupdates.databinding.ActivityHistoryBinding
import kotlinx.coroutines.launch

class HistoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoryBinding
    private lateinit var player: ExoPlayer
    private lateinit var downloadStore: DownloadStore
    private lateinit var adapter: HistoryAdapter
    private val repository = EpisodeRepository()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHistoryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        player = ExoPlayer.Builder(this).build()
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

    private fun loadHistory() {
        lifecycleScope.launch {
            val history = try {
                repository.getEpisodeHistory(applicationContext)
            } catch (e: Exception) {
                emptyList()
            }
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
        val uri = resolvePlaybackUri(episode.audioUrl, downloadStore.localPathFor(episode.date))
        player.setMediaItem(MediaItem.fromUri(uri))
        player.prepare()
        player.play()
    }

    private fun download(episode: EpisodeSummary) {
        if (episode.audioUrl.isEmpty()) return
        adapter.markDownloading(episode.date)
        downloadStore.startDownload(episode.date, episode.audioUrl) { success ->
            runOnUiThread { adapter.markResult(episode.date, success) }
        }
    }

    override fun onDestroy() {
        player.release()
        downloadStore.unregister()
        super.onDestroy()
    }
}
