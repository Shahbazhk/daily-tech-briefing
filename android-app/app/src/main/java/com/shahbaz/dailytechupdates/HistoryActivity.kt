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
