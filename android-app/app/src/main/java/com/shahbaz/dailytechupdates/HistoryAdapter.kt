package com.shahbaz.dailytechupdates

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.shahbaz.dailytechupdates.databinding.ItemEpisodeHistoryBinding

enum class RowStatus { STREAM_ONLY, DOWNLOADING, DOWNLOADED }

class HistoryAdapter(
    private val onPlay: (EpisodeSummary) -> Unit,
    private val onDownload: (EpisodeSummary) -> Unit
) : RecyclerView.Adapter<HistoryAdapter.ViewHolder>() {

    private var items: List<EpisodeSummary> = emptyList()
    private val statuses = mutableMapOf<String, RowStatus>()

    fun submitList(newItems: List<EpisodeSummary>, downloadedDates: Set<String>) {
        items = newItems
        statuses.clear()
        newItems.forEach { statuses[it.date] = if (it.date in downloadedDates) RowStatus.DOWNLOADED else RowStatus.STREAM_ONLY }
        notifyDataSetChanged()
    }

    fun markDownloading(date: String) {
        statuses[date] = RowStatus.DOWNLOADING
        notifyItemChanged(items.indexOfFirst { it.date == date })
    }

    fun markResult(date: String, downloaded: Boolean) {
        statuses[date] = if (downloaded) RowStatus.DOWNLOADED else RowStatus.STREAM_ONLY
        notifyItemChanged(items.indexOfFirst { it.date == date })
    }

    class ViewHolder(val binding: ItemEpisodeHistoryBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemEpisodeHistoryBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return ViewHolder(binding)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = items[position]
        holder.binding.rowDateText.text = item.date
        holder.binding.rowTopicsText.text = item.topicsCovered.joinToString(" • ")
        holder.binding.root.setOnClickListener { onPlay(item) }

        val status = statuses[item.date] ?: RowStatus.STREAM_ONLY
        holder.binding.rowStatusIcon.text = when (status) {
            RowStatus.STREAM_ONLY -> "⬇"
            RowStatus.DOWNLOADING -> "⏳"
            RowStatus.DOWNLOADED -> "✓"
        }
        holder.binding.rowStatusIcon.setOnClickListener {
            if (status == RowStatus.STREAM_ONLY) onDownload(item)
        }
    }

    override fun getItemCount(): Int = items.size
}
