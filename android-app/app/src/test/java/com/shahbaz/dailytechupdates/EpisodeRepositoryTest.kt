package com.shahbaz.dailytechupdates

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EpisodeRepositoryTest {

    @Test
    fun `TECH pattern matches only tech-dated tags, never PM tags`() {
        assertTrue(Show.TECH.tagPattern.matches("episode-2026-09-08"))
        assertFalse(Show.TECH.tagPattern.matches("episode-pm-2026-09-08"))
    }

    @Test
    fun `PM pattern matches only pm-dated tags`() {
        assertTrue(Show.PM.tagPattern.matches("episode-pm-2026-09-08"))
        assertFalse(Show.PM.tagPattern.matches("episode-2026-09-08"))
    }

    @Test
    fun `neither pattern matches the app-latest APK release tag`() {
        assertFalse(Show.TECH.tagPattern.matches("app-latest"))
        assertFalse(Show.PM.tagPattern.matches("app-latest"))
    }

    @Test
    fun `date is captured directly from the tag match`() {
        assertEquals("2026-09-08", Show.TECH.tagPattern.find("episode-2026-09-08")?.groupValues?.get(1))
        assertEquals("2026-09-08", Show.PM.tagPattern.find("episode-pm-2026-09-08")?.groupValues?.get(1))
    }
}
