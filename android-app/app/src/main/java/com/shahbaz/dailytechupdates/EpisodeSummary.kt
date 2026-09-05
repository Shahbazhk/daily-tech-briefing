package com.shahbaz.dailytechupdates

import android.os.Parcelable
import kotlinx.parcelize.Parcelize

@Parcelize
data class EpisodeSummary(
    val date: String,
    val topicsCovered: List<String>,
    val audioUrl: String,
    val transcriptUrl: String
) : Parcelable
