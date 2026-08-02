package com.shahbaz.dailytechupdates

data class Episode(
    val date: String = "",
    val audioUrl: String = "",
    val topicsCovered: List<String> = emptyList(),
    val script: String = ""
)
