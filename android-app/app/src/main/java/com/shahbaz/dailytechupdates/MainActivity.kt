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
