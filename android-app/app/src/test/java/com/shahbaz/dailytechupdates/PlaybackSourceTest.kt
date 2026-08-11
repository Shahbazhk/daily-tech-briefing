package com.shahbaz.dailytechupdates

import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class PlaybackSourceTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    @Test
    fun `returns the stream URL when no local path is given`() {
        val result = resolvePlaybackUri("https://example.com/episode.mp3", null)
        assertEquals("https://example.com/episode.mp3", result)
    }

    @Test
    fun `returns the stream URL when the local path does not exist on disk`() {
        val missingPath = File(tempFolder.root, "missing.mp3").absolutePath
        val result = resolvePlaybackUri("https://example.com/episode.mp3", missingPath)
        assertEquals("https://example.com/episode.mp3", result)
    }

    @Test
    fun `returns a file URI when the local path exists on disk`() {
        val localFile = File(tempFolder.root, "episode.mp3")
        localFile.writeText("fake audio bytes")

        val result = resolvePlaybackUri("https://example.com/episode.mp3", localFile.absolutePath)

        assertEquals("file://${localFile.absolutePath}", result)
    }
}
