package com.shahbaz.dailytechupdates

data class EpisodeSummary(
    val date: String,
    val topicsCovered: List<String>,
    val audioUrl: String,
    val transcriptUrl: String
)
