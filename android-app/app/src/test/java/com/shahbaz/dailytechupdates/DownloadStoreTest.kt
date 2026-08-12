package com.shahbaz.dailytechupdates

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadStoreTest {

    @Test
    fun `serialize then parse round-trips a record`() {
        val records = mapOf(
            "2026-08-10" to DownloadRecord("2026-08-10", "/data/episodes/2026-08-10.mp3", 1786435200000L)
        )
        val json = serializeDownloadRecords(records)
        assertEquals(records, parseDownloadRecords(json))
    }

    @Test
    fun `parseDownloadRecords returns empty map for blank input`() {
        assertTrue(parseDownloadRecords("").isEmpty())
    }

    @Test
    fun `purgeExpiredRecords keeps records within the max age window`() {
        val now = 1_000_000_000_000L
        val recent = DownloadRecord("2026-08-10", "/a.mp3", now - 1_000)

        val kept = purgeExpiredRecords(mapOf("2026-08-10" to recent), now, DOWNLOAD_MAX_AGE_MILLIS)

        assertEquals(mapOf("2026-08-10" to recent), kept)
    }

    @Test
    fun `purgeExpiredRecords drops records older than the max age window`() {
        val now = 1_000_000_000_000L
        val stale = DownloadRecord("2026-07-01", "/b.mp3", now - DOWNLOAD_MAX_AGE_MILLIS - 1)

        val kept = purgeExpiredRecords(mapOf("2026-07-01" to stale), now, DOWNLOAD_MAX_AGE_MILLIS)

        assertTrue(kept.isEmpty())
    }
}
