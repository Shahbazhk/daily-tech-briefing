package com.shahbaz.dailytechupdates

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class HistoryCacheTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    @Test
    fun `serialize then parse round-trips topics for multiple dates`() {
        val cache = mapOf(
            "2026-08-10" to listOf("Java", "Kafka", "Docker"),
            "2026-08-09" to listOf("Rust", "WASM")
        )
        val json = serializeHistoryCache(cache)
        assertEquals(cache, parseHistoryCache(json))
    }

    @Test
    fun `parseHistoryCache returns empty map for blank input`() {
        assertTrue(parseHistoryCache("").isEmpty())
    }

    @Test
    fun `mergeHistoryCache overwrites cached entries with fresh values for the same date`() {
        val cached = mapOf("2026-08-10" to listOf("stale"))
        val fresh = mapOf("2026-08-10" to listOf("Java", "Kafka"))

        val merged = mergeHistoryCache(cached, fresh)

        assertEquals(listOf("Java", "Kafka"), merged["2026-08-10"])
    }

    @Test
    fun `mergeHistoryCache keeps cached-only entries when fresh data is missing them`() {
        val cached = mapOf("2026-08-08" to listOf("Old topic"))
        val fresh = emptyMap<String, List<String>>()

        val merged = mergeHistoryCache(cached, fresh)

        assertEquals(listOf("Old topic"), merged["2026-08-08"])
    }

    @Test
    fun `HistoryCache persists a merge to disk and reads it back`() {
        val file = File(tempFolder.root, "history_cache.json")
        val store = HistoryCache(file)

        store.merge(mapOf("2026-08-10" to listOf("Java", "Kafka")))

        assertEquals(mapOf("2026-08-10" to listOf("Java", "Kafka")), store.readAll())
    }
}
