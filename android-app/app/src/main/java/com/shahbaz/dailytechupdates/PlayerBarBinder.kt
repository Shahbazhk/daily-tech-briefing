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
