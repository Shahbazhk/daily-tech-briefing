# Episode History and Offline Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Android app browse every past episode (not just the latest) and optionally save a chosen episode to the device for offline playback, auto-expiring saved episodes after 30 days.

**Architecture:** `EpisodeRepository` gains a paginated `getEpisodeHistory()` backed by a local JSON cache of topics (so the list is browsable offline too). A new `DownloadStore` wraps Android's system `DownloadManager` plus a JSON record of completed downloads, with pure parse/serialize/purge logic split out for unit testing. A new `HistoryActivity` + `RecyclerView` lists episodes with a play/download/downloaded status icon per row; both it and `MainActivity` resolve playback through one shared `resolvePlaybackUri()` helper that prefers a local file over streaming.

**Tech Stack:** Kotlin, AndroidX (`RecyclerView`, `ConstraintLayout`, `Media3`/ExoPlayer — all already or newly present), Android's built-in `DownloadManager` and `SharedPreferences`, `org.json` (already used in this codebase), JUnit 4 for new unit tests.

**Spec:** `docs/superpowers/specs/2026-08-11-episode-history-and-offline-downloads-design.md`

## Global Constraints

- $0/month, no new paid services (from project-wide constraint, restated in the spec).
- No new third-party runtime dependencies beyond standard Android/Jetpack components already established as acceptable in this codebase: `DownloadManager` and `SharedPreferences` are platform APIs (no dependency at all); `androidx.recyclerview` is a standard Jetpack component in the same family as the `androidx.constraintlayout`/`androidx.appcompat` already in `app/build.gradle.kts` — approved as part of this plan, not a new external service. `junit` and `org.json:json` are `testImplementation`-only (test compile/runtime classpath), never shipped in the APK.
- Persist local records (history cache, download records) using the same raw `org.json`-over-file/`SharedPreferences` style already used by `EpisodeRepository.kt` — no Room, no DataStore, no new JSON library.
- Downloaded episodes auto-expire after exactly 30 days (`DOWNLOAD_MAX_AGE_MILLIS = 30L * 24 * 60 * 60 * 1000`), checked on every `MainActivity`/`HistoryActivity` open.
- `minSdk = 26`, `compileSdk = 34`, `targetSdk = 34`, Kotlin/JVM target 17, `viewBinding = true` — all already set in `app/build.gradle.kts`; do not change them.
- This environment has no committed Gradle wrapper and no fully-configured local Android SDK matching `compileSdk 34` (only `android-37.0`/`build-tools 36.0.0` are present locally, and no `sdkmanager`/`cmdline-tools` to fetch platform 34). Each task still specifies the correct `gradle testDebugUnitTest` command to run — if a properly configured `gradle` isn't available in the executing environment, note that in the task report as a concern rather than skipping the step, and rely on Task 7's new CI workflow as the authoritative pass/fail signal once pushed.

---

### Task 1: Shared playback-source resolution + JVM test infra

**Files:**
- Modify: `android-app/app/build.gradle.kts`
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlaybackSource.kt`
- Test: `android-app/app/src/test/java/com/shahbaz/dailytechupdates/PlaybackSourceTest.kt`

**Interfaces:**
- Consumes: nothing from earlier tasks (first task).
- Produces: `fun resolvePlaybackUri(audioUrl: String, localPath: String?): String` — used by Task 4's `HistoryActivity` and Task 6's `MainActivity`.

- [ ] **Step 1: Add JUnit test infrastructure to `app/build.gradle.kts`**

Add to the existing `dependencies { ... }` block (after the last `implementation(...)` line):

```kotlin
    testImplementation("junit:junit:4.13.2")
    // android.jar's org.json classes are stubs in local unit tests (throw "not mocked");
    // this pulls in the real reference implementation for the JVM test classpath.
    testImplementation("org.json:json:20240303")
```

- [ ] **Step 2: Write the failing test**

Create `android-app/app/src/test/java/com/shahbaz/dailytechupdates/PlaybackSourceTest.kt`:

```kotlin
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
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `android-app/`): `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.PlaybackSourceTest"`
Expected: FAIL to compile — `resolvePlaybackUri` is unresolved.

- [ ] **Step 4: Write the implementation**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlaybackSource.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import java.io.File

/**
 * Deliberately builds the file:// string by hand instead of using android.net.Uri: this
 * function must stay callable from plain JVM unit tests (no Android framework, no
 * Robolectric), and android.net.Uri is a stub there.
 */
fun resolvePlaybackUri(audioUrl: String, localPath: String?): String {
    if (localPath != null && File(localPath).exists()) {
        return "file://$localPath"
    }
    return audioUrl
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.PlaybackSourceTest"`
Expected: PASS, 3 tests.

- [ ] **Step 6: Commit**

```bash
git add android-app/app/build.gradle.kts android-app/app/src/main/java/com/shahbaz/dailytechupdates/PlaybackSource.kt android-app/app/src/test/java/com/shahbaz/dailytechupdates/PlaybackSourceTest.kt
git commit -m "Add resolvePlaybackUri to prefer a local file over streaming"
```

---

### Task 2: Local history cache (topics, offline-browsable)

**Files:**
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryCache.kt`
- Test: `android-app/app/src/test/java/com/shahbaz/dailytechupdates/HistoryCacheTest.kt`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `fun parseHistoryCache(json: String): Map<String, List<String>>`, `fun serializeHistoryCache(cache: Map<String, List<String>>): String`, `fun mergeHistoryCache(cached: Map<String, List<String>>, fresh: Map<String, List<String>>): Map<String, List<String>>`, and `class HistoryCache(cacheFile: File) { fun readAll(): Map<String, List<String>>; fun merge(fresh: Map<String, List<String>>) }` with `companion object { fun forContext(context: Context): HistoryCache }` — all used by Task 4's `EpisodeRepository.getEpisodeHistory()`.

- [ ] **Step 1: Write the failing test**

Create `android-app/app/src/test/java/com/shahbaz/dailytechupdates/HistoryCacheTest.kt`:

```kotlin
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.HistoryCacheTest"`
Expected: FAIL to compile — none of `parseHistoryCache`/`serializeHistoryCache`/`mergeHistoryCache`/`HistoryCache` exist yet.

- [ ] **Step 3: Write the implementation**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryCache.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

private const val HISTORY_CACHE_FILENAME = "history_cache.json"

fun parseHistoryCache(json: String): Map<String, List<String>> {
    if (json.isBlank()) return emptyMap()
    val obj = JSONObject(json)
    val result = mutableMapOf<String, List<String>>()
    obj.keys().forEach { date ->
        val entry = obj.getJSONObject(date)
        val topicsArray = entry.getJSONArray("topicsCovered")
        result[date] = (0 until topicsArray.length()).map { topicsArray.getString(it) }
    }
    return result
}

fun serializeHistoryCache(cache: Map<String, List<String>>): String {
    val obj = JSONObject()
    cache.forEach { (date, topics) ->
        val entry = JSONObject()
        entry.put("topicsCovered", JSONArray(topics))
        obj.put(date, entry)
    }
    return obj.toString()
}

/** Fresh entries win on a shared date; a date present only in `cached` is kept as-is. */
fun mergeHistoryCache(
    cached: Map<String, List<String>>,
    fresh: Map<String, List<String>>
): Map<String, List<String>> = cached + fresh

/** Wraps the pure functions above with actual file I/O against app-private storage. */
class HistoryCache(private val cacheFile: File) {

    fun readAll(): Map<String, List<String>> =
        if (cacheFile.exists()) parseHistoryCache(cacheFile.readText()) else emptyMap()

    fun merge(fresh: Map<String, List<String>>) {
        val updated = mergeHistoryCache(readAll(), fresh)
        cacheFile.writeText(serializeHistoryCache(updated))
    }

    companion object {
        fun forContext(context: Context) = HistoryCache(File(context.filesDir, HISTORY_CACHE_FILENAME))
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.HistoryCacheTest"`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryCache.kt android-app/app/src/test/java/com/shahbaz/dailytechupdates/HistoryCacheTest.kt
git commit -m "Add local history cache for offline-browsable episode topics"
```

---

### Task 3: Download store (records + expiry + system DownloadManager wiring)

**Files:**
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/DownloadStore.kt`
- Test: `android-app/app/src/test/java/com/shahbaz/dailytechupdates/DownloadStoreTest.kt`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `data class DownloadRecord(val date: String, val localPath: String, val downloadedAtEpochMillis: Long)`, `const val DOWNLOAD_MAX_AGE_MILLIS: Long`, pure `fun parseDownloadRecords(json: String): Map<String, DownloadRecord>`, `fun serializeDownloadRecords(records: Map<String, DownloadRecord>): String`, `fun purgeExpiredRecords(records: Map<String, DownloadRecord>, nowEpochMillis: Long, maxAgeMillis: Long = DOWNLOAD_MAX_AGE_MILLIS): Map<String, DownloadRecord>`, and `class DownloadStore(context: Context) { fun localPathFor(date: String): String?; fun startDownload(date: String, audioUrl: String, onComplete: (Boolean) -> Unit); fun purgeExpired(); fun unregister() }` — used by Task 4 (`localPathFor` inside `EpisodeRepository`? no — by Task 5's `HistoryActivity` and Task 6's `MainActivity`).

- [ ] **Step 1: Write the failing test**

Create `android-app/app/src/test/java/com/shahbaz/dailytechupdates/DownloadStoreTest.kt`:

```kotlin
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.DownloadStoreTest"`
Expected: FAIL to compile — `DownloadRecord`/`parseDownloadRecords`/`serializeDownloadRecords`/`purgeExpiredRecords`/`DOWNLOAD_MAX_AGE_MILLIS` don't exist yet.

- [ ] **Step 3: Write the implementation**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/DownloadStore.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.io.File

data class DownloadRecord(val date: String, val localPath: String, val downloadedAtEpochMillis: Long)

const val DOWNLOAD_MAX_AGE_MILLIS = 30L * 24 * 60 * 60 * 1000

private const val PREFS_NAME = "downloads"
private const val PREFS_KEY = "records_json"

fun parseDownloadRecords(json: String): Map<String, DownloadRecord> {
    if (json.isBlank()) return emptyMap()
    val obj = JSONObject(json)
    val result = mutableMapOf<String, DownloadRecord>()
    obj.keys().forEach { date ->
        val entry = obj.getJSONObject(date)
        result[date] = DownloadRecord(
            date = date,
            localPath = entry.getString("localPath"),
            downloadedAtEpochMillis = entry.getLong("downloadedAtEpochMillis")
        )
    }
    return result
}

fun serializeDownloadRecords(records: Map<String, DownloadRecord>): String {
    val obj = JSONObject()
    records.forEach { (date, record) ->
        val entry = JSONObject()
        entry.put("localPath", record.localPath)
        entry.put("downloadedAtEpochMillis", record.downloadedAtEpochMillis)
        obj.put(date, entry)
    }
    return obj.toString()
}

fun purgeExpiredRecords(
    records: Map<String, DownloadRecord>,
    nowEpochMillis: Long,
    maxAgeMillis: Long = DOWNLOAD_MAX_AGE_MILLIS
): Map<String, DownloadRecord> =
    records.filterValues { nowEpochMillis - it.downloadedAtEpochMillis <= maxAgeMillis }

/**
 * Tracks completed downloads (JSON in SharedPreferences, same style as HistoryCache) and
 * wraps Android's system DownloadManager to fetch new ones. Not unit tested beyond the
 * pure functions above — this class needs a real Context/DownloadManager, consistent with
 * the rest of this codebase's Android-framework-dependent code.
 */
class DownloadStore(private val context: Context) {

    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val pendingDownloadIds = mutableMapOf<Long, String>()
    private var receiver: BroadcastReceiver? = null

    private fun readAll(): Map<String, DownloadRecord> =
        parseDownloadRecords(prefs.getString(PREFS_KEY, "") ?: "")

    private fun writeAll(records: Map<String, DownloadRecord>) {
        prefs.edit().putString(PREFS_KEY, serializeDownloadRecords(records)).apply()
    }

    fun localPathFor(date: String): String? = readAll()[date]?.localPath

    /** Enqueues a download via DownloadManager; onComplete reports success/failure once it finishes. */
    fun startDownload(date: String, audioUrl: String, onComplete: (success: Boolean) -> Unit) {
        val downloadManager = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val relativePath = "episodes/$date.mp3"
        val request = DownloadManager.Request(Uri.parse(audioUrl))
            .setDestinationInExternalFilesDir(context, null, relativePath)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setTitle("Downloading $date episode")

        val downloadId = downloadManager.enqueue(request)
        pendingDownloadIds[downloadId] = date
        ensureReceiverRegistered(downloadManager, onComplete)
    }

    private fun ensureReceiverRegistered(downloadManager: DownloadManager, onComplete: (Boolean) -> Unit) {
        if (receiver != null) return
        receiver = object : BroadcastReceiver() {
            override fun onReceive(receiverContext: Context, intent: Intent) {
                val id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
                val date = pendingDownloadIds.remove(id) ?: return
                val success = isDownloadSuccessful(downloadManager, id)
                if (success) {
                    val localFile = File(context.getExternalFilesDir(null), "episodes/$date.mp3")
                    writeAll(readAll() + (date to DownloadRecord(date, localFile.absolutePath, System.currentTimeMillis())))
                }
                onComplete(success)
            }
        }
        ContextCompat.registerReceiver(
            context,
            receiver,
            IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
    }

    private fun isDownloadSuccessful(downloadManager: DownloadManager, id: Long): Boolean {
        val query = DownloadManager.Query().setFilterById(id)
        downloadManager.query(query).use { cursor ->
            if (!cursor.moveToFirst()) return false
            val statusIndex = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS)
            return cursor.getInt(statusIndex) == DownloadManager.STATUS_SUCCESSFUL
        }
    }

    /** Deletes any downloaded file older than DOWNLOAD_MAX_AGE_MILLIS and drops its record. */
    fun purgeExpired() {
        val current = readAll()
        val kept = purgeExpiredRecords(current, System.currentTimeMillis())
        (current - kept.keys).values.forEach { File(it.localPath).delete() }
        writeAll(kept)
    }

    /** Call from onDestroy - safe to call even if startDownload was never called. */
    fun unregister() {
        receiver?.let { context.unregisterReceiver(it) }
        receiver = null
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `gradle testDebugUnitTest --tests "com.shahbaz.dailytechupdates.DownloadStoreTest"`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/DownloadStore.kt android-app/app/src/test/java/com/shahbaz/dailytechupdates/DownloadStoreTest.kt
git commit -m "Add DownloadStore: system DownloadManager wiring with 30-day expiry"
```

---

### Task 4: `EpisodeRepository.getEpisodeHistory()` + shared asset-parsing refactor

**Files:**
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeSummary.kt`
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeRepository.kt` (full file, shown below)

**Interfaces:**
- Consumes: `HistoryCache.forContext(context: Context): HistoryCache` and `HistoryCache.readAll()`/`.merge()` from Task 2.
- Produces: `data class EpisodeSummary(val date: String, val topicsCovered: List<String>, val audioUrl: String, val transcriptUrl: String)` and `suspend fun EpisodeRepository.getEpisodeHistory(context: Context): List<EpisodeSummary>` — used by Task 5's `HistoryActivity`.

No unit tests for this task: `getEpisodeHistory()` and `getLatestEpisode()` are network I/O against the real GitHub API, matching the existing untested pattern in this file (there is no seam to inject a fake HTTP client without adding new abstraction this app doesn't otherwise have — out of scope per YAGNI). Verify manually per Step 3.

- [ ] **Step 1: Create the new data class**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeSummary.kt`:

```kotlin
package com.shahbaz.dailytechupdates

data class EpisodeSummary(
    val date: String,
    val topicsCovered: List<String>,
    val audioUrl: String,
    val transcriptUrl: String
)
```

- [ ] **Step 2: Replace `EpisodeRepository.kt` with this full file**

This extracts the existing inline asset-matching and topics-parsing logic into two shared private helpers (`extractAssets`, `topicsFromTranscript`) used by both `getLatestEpisode()` (unchanged behavior/selection logic — still a single unpaged fetch, still picks the lexicographically-max `episode-` tag) and the new `getEpisodeHistory()` (paginated, cache-aware):

```kotlin
package com.shahbaz.dailytechupdates

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Reads episodes straight from GitHub Releases published by
 * pipeline/publish/publish.py's fallback path (used whenever FIREBASE_SERVICE_ACCOUNT
 * isn't configured - see BRD Section 14.5). No auth needed: the repo is public and this
 * is well under GitHub's unauthenticated rate limit for a single-user app checking once
 * in a while.
 *
 * Deliberately does NOT use GET /releases/latest: this repo also publishes an "app-latest"
 * release for APK builds (build-apk.yml) into the same release list, and GitHub's "latest"
 * is whichever release was published most recently repo-wide - not the most recent episode.
 * An APK rebuild after an episode publish would silently make /releases/latest point at the
 * APK release (no audio asset) until the next episode overtakes it. Instead, list all
 * releases and pick the newest one tagged "episode-YYYY-MM-DD" ourselves.
 *
 * TODO: once Firebase is set up (BRD open item), swap this for a Firestore-backed
 * implementation with real push notifications instead of check-on-open polling.
 */
class EpisodeRepository {

    private val releasesUrl =
        "https://api.github.com/repos/Shahbazhk/daily-tech-briefing/releases"

    suspend fun getLatestEpisode(): Episode? = withContext(Dispatchers.IO) {
        val releases = JSONArray(httpGet(releasesUrl))
        var release: JSONObject? = null
        for (i in 0 until releases.length()) {
            val candidate = releases.getJSONObject(i)
            if (candidate.optString("tag_name").startsWith("episode-")) {
                if (release == null ||
                    candidate.getString("tag_name") > release!!.getString("tag_name")
                ) {
                    release = candidate
                }
            }
        }
        val chosen = release ?: return@withContext null
        val assets = extractAssets(chosen)
        if (assets.audioUrl.isEmpty()) return@withContext null

        var date = chosen.optString("tag_name", "").removePrefix("episode-")
        var script = ""
        var topics = emptyList<String>()
        if (assets.transcriptUrl.isNotEmpty()) {
            val transcript = JSONObject(httpGet(assets.transcriptUrl))
            date = transcript.optString("date", date)
            script = transcript.optString("script", "")
            topics = topicsFromTranscript(transcript)
        }

        Episode(date = date, audioUrl = assets.audioUrl, topicsCovered = topics, script = script)
    }

    /**
     * Lists every past episode, newest first. Topics for a date already present in the
     * local history cache are reused as-is (no network call); topics for a date seen for
     * the first time are fetched from that release's transcript and written into the
     * cache, so a later call never re-fetches a transcript it already has.
     *
     * On a releases-list network failure, falls back to whatever's in the cache (audioUrl
     * empty for those entries, since the cache only ever stores topics) rather than
     * throwing, so History has something to show offline.
     */
    suspend fun getEpisodeHistory(context: Context): List<EpisodeSummary> = withContext(Dispatchers.IO) {
        val historyCache = HistoryCache.forContext(context)
        val cachedTopics = historyCache.readAll()

        val releases = try {
            fetchAllEpisodeReleases()
        } catch (e: Exception) {
            emptyList()
        }

        if (releases.isEmpty()) {
            return@withContext cachedTopics.map { (date, topics) ->
                EpisodeSummary(date = date, topicsCovered = topics, audioUrl = "", transcriptUrl = "")
            }.sortedByDescending { it.date }
        }

        val freshTopics = mutableMapOf<String, List<String>>()
        val summaries = releases.map { release ->
            val date = release.optString("tag_name", "").removePrefix("episode-")
            val assets = extractAssets(release)
            val topics = cachedTopics[date] ?: fetchTopics(assets.transcriptUrl).also { freshTopics[date] = it }
            EpisodeSummary(date = date, topicsCovered = topics, audioUrl = assets.audioUrl, transcriptUrl = assets.transcriptUrl)
        }
        if (freshTopics.isNotEmpty()) historyCache.merge(freshTopics)
        summaries.sortedByDescending { it.date }
    }

    private data class ReleaseAssets(val audioUrl: String, val transcriptUrl: String)

    private fun extractAssets(release: JSONObject): ReleaseAssets {
        val assets = release.getJSONArray("assets")
        var audioUrl = ""
        var transcriptUrl = ""
        for (i in 0 until assets.length()) {
            val asset = assets.getJSONObject(i)
            val name = asset.getString("name")
            val url = asset.getString("browser_download_url")
            if (name.endsWith(".mp3")) audioUrl = url
            if (name.startsWith("transcript_") && name.endsWith(".json")) transcriptUrl = url
        }
        return ReleaseAssets(audioUrl, transcriptUrl)
    }

    private fun fetchAllEpisodeReleases(): List<JSONObject> {
        val all = mutableListOf<JSONObject>()
        var page = 1
        while (true) {
            val pageJson = JSONArray(httpGet("$releasesUrl?per_page=100&page=$page"))
            if (pageJson.length() == 0) break
            for (i in 0 until pageJson.length()) {
                val candidate = pageJson.getJSONObject(i)
                if (candidate.optString("tag_name").startsWith("episode-")) {
                    all.add(candidate)
                }
            }
            page++
        }
        return all
    }

    private fun fetchTopics(transcriptUrl: String): List<String> {
        if (transcriptUrl.isEmpty()) return emptyList()
        return try {
            topicsFromTranscript(JSONObject(httpGet(transcriptUrl)))
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun topicsFromTranscript(transcript: JSONObject): List<String> {
        val topicsArray = transcript.optJSONArray("topics_covered") ?: return emptyList()
        return (0 until topicsArray.length()).map { topicsArray.getJSONObject(it).optString("topic") }
    }

    private fun httpGet(urlString: String): String {
        val connection = URL(urlString).openConnection() as HttpURLConnection
        connection.setRequestProperty("Accept", "application/vnd.github+json")
        connection.connectTimeout = 15_000
        connection.readTimeout = 15_000
        return try {
            connection.inputStream.bufferedReader().use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }
}
```

- [ ] **Step 3: Verify manually**

Run: `gradle testDebugUnitTest` (confirms the whole module — including Tasks 1–3's tests — still compiles and passes with this file in place; there's no new test in this task).
Expected: PASS, 12 tests total (3 + 5 + 4 from Tasks 1–3).

Then read through `getEpisodeHistory()` once against the design spec's section 3.2/3.3: confirm a date already in `cachedTopics` never reaches `fetchTopics`, and that a releases-fetch exception falls back to `cachedTopics` instead of propagating.

- [ ] **Step 4: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeSummary.kt android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeRepository.kt
git commit -m "Add EpisodeRepository.getEpisodeHistory() with cached-topics offline fallback"
```

---

### Task 5: History screen (RecyclerView, adapter, layouts)

**Files:**
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryAdapter.kt`
- Create: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt`
- Create: `android-app/app/src/main/res/layout/activity_history.xml`
- Create: `android-app/app/src/main/res/layout/item_episode_history.xml`
- Modify: `android-app/app/build.gradle.kts`
- Modify: `android-app/app/src/main/AndroidManifest.xml`
- Modify: `android-app/app/src/main/res/values/strings.xml`

**Interfaces:**
- Consumes: `EpisodeSummary` (Task 4), `EpisodeRepository.getEpisodeHistory(context)` (Task 4), `DownloadStore` (Task 3), `resolvePlaybackUri` (Task 1).
- Produces: `HistoryActivity` (launched by Task 6's `MainActivity` via `Intent(this, HistoryActivity::class.java)`).

No unit tests for this task: `RecyclerView`/`Activity` wiring has no existing test infrastructure in this app (instrumentation tests are out of scope per the spec's Section 5) — verify manually per Step 6.

- [ ] **Step 1: Add the RecyclerView dependency**

Add to `app/build.gradle.kts`'s `dependencies { ... }` block (after the `media3-ui` line):

```kotlin
    implementation("androidx.recyclerview:recyclerview:1.3.2")
```

- [ ] **Step 2: Add new strings**

Add to `android-app/app/src/main/res/values/strings.xml` (before the closing `</resources>`):

```xml
    <string name="history">History</string>
    <string name="history_unavailable">History unavailable — check your connection.</string>
```

- [ ] **Step 3: Create the row layout**

Create `android-app/app/src/main/res/layout/item_episode_history.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:orientation="horizontal"
    android:paddingVertical="12dp"
    android:paddingHorizontal="4dp"
    android:gravity="center_vertical">

    <LinearLayout
        android:layout_width="0dp"
        android:layout_height="wrap_content"
        android:layout_weight="1"
        android:orientation="vertical">

        <TextView
            android:id="@+id/rowDateText"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:textStyle="bold" />

        <TextView
            android:id="@+id/rowTopicsText"
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:textSize="14sp"
            android:textColor="?android:attr/textColorSecondary" />
    </LinearLayout>

    <TextView
        android:id="@+id/rowStatusIcon"
        android:layout_width="48dp"
        android:layout_height="48dp"
        android:gravity="center"
        android:textSize="20sp" />

</LinearLayout>
```

- [ ] **Step 4: Create the history screen layout**

Create `android-app/app/src/main/res/layout/activity_history.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="match_parent">

    <androidx.recyclerview.widget.RecyclerView
        android:id="@+id/historyList"
        android:layout_width="0dp"
        android:layout_height="0dp"
        android:padding="16dp"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintBottom_toBottomOf="parent" />

    <TextView
        android:id="@+id/emptyText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:padding="24dp"
        android:text="@string/history_unavailable"
        android:visibility="gone"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintBottom_toBottomOf="parent" />

</androidx.constraintlayout.widget.ConstraintLayout>
```

- [ ] **Step 5: Create the adapter and activity**

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryAdapter.kt`:

```kotlin
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
            RowStatus.STREAM_ONLY -> "⬇"  // ⬇
            RowStatus.DOWNLOADING -> "⏳"  // ⏳
            RowStatus.DOWNLOADED -> "✓"   // ✓
        }
        holder.binding.rowStatusIcon.setOnClickListener {
            if (status == RowStatus.STREAM_ONLY) onDownload(item)
        }
    }

    override fun getItemCount(): Int = items.size
}
```

Create `android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt`:

```kotlin
package com.shahbaz.dailytechupdates

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.recyclerview.widget.LinearLayoutManager
import com.shahbaz.dailytechupdates.databinding.ActivityHistoryBinding
import kotlinx.coroutines.launch

class HistoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoryBinding
    private lateinit var player: ExoPlayer
    private lateinit var downloadStore: DownloadStore
    private lateinit var adapter: HistoryAdapter
    private val repository = EpisodeRepository()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHistoryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        player = ExoPlayer.Builder(this).build()
        downloadStore = DownloadStore(applicationContext)
        downloadStore.purgeExpired()

        adapter = HistoryAdapter(
            onPlay = { episode -> play(episode) },
            onDownload = { episode -> download(episode) }
        )
        binding.historyList.layoutManager = LinearLayoutManager(this)
        binding.historyList.adapter = adapter

        loadHistory()
    }

    private fun loadHistory() {
        lifecycleScope.launch {
            val history = try {
                repository.getEpisodeHistory(applicationContext)
            } catch (e: Exception) {
                emptyList()
            }
            if (history.isEmpty()) {
                binding.emptyText.visibility = View.VISIBLE
                binding.historyList.visibility = View.GONE
                return@launch
            }
            binding.emptyText.visibility = View.GONE
            binding.historyList.visibility = View.VISIBLE
            val downloadedDates = history.filter { downloadStore.localPathFor(it.date) != null }.map { it.date }.toSet()
            adapter.submitList(history, downloadedDates)
        }
    }

    private fun play(episode: EpisodeSummary) {
        val uri = resolvePlaybackUri(episode.audioUrl, downloadStore.localPathFor(episode.date))
        player.setMediaItem(MediaItem.fromUri(uri))
        player.prepare()
        player.play()
    }

    private fun download(episode: EpisodeSummary) {
        if (episode.audioUrl.isEmpty()) return
        adapter.markDownloading(episode.date)
        downloadStore.startDownload(episode.date, episode.audioUrl) { success ->
            runOnUiThread { adapter.markResult(episode.date, success) }
        }
    }

    override fun onDestroy() {
        player.release()
        downloadStore.unregister()
        super.onDestroy()
    }
}
```

- [ ] **Step 6: Register the activity and verify manually**

Add to `android-app/app/src/main/AndroidManifest.xml`, inside `<application>...</application>`, after the existing `<activity android:name=".MainActivity" ...>` block:

```xml
        <activity
            android:name=".HistoryActivity"
            android:exported="false" />
```

Run: `gradle testDebugUnitTest` — confirms the module (including all Kotlin added so far) still compiles cleanly; no new tests in this task.
Expected: PASS, 12 tests (unchanged from Task 4).

If a device/emulator is available, run: `gradle installDebug`, launch the app, and manually confirm: History screen (once reachable after Task 6) lists past episodes, tapping a row plays it, tapping the ⬇ icon starts a download that becomes ✓ on completion, and re-tapping a ✓ row plays from the local file (airplane mode confirms this — turn on airplane mode and confirm a ✓ row still plays). If no device/emulator is available in this environment, note that as a concern in the task report — this is real device-dependent behavior (`DownloadManager`, `BroadcastReceiver`) that a JVM unit test can't cover.

- [ ] **Step 7: Commit**

```bash
git add android-app/app/build.gradle.kts android-app/app/src/main/res/values/strings.xml android-app/app/src/main/res/layout/item_episode_history.xml android-app/app/src/main/res/layout/activity_history.xml android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryAdapter.kt android-app/app/src/main/java/com/shahbaz/dailytechupdates/HistoryActivity.kt android-app/app/src/main/AndroidManifest.xml
git commit -m "Add HistoryActivity: browse and download past episodes"
```

---

### Task 6: Wire `MainActivity` to History + local-file playback + expiry purge

**Files:**
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt` (full file, shown below)
- Modify: `android-app/app/src/main/res/layout/activity_main.xml`

**Interfaces:**
- Consumes: `HistoryActivity` (Task 5), `DownloadStore` (Task 3), `resolvePlaybackUri` (Task 1).
- Produces: nothing new for later tasks (final integration point).

No unit tests: `MainActivity` wiring is Activity/UI code, matching the existing untested pattern for this file.

- [ ] **Step 1: Add the History button to the main layout**

Replace `android-app/app/src/main/res/layout/activity_main.xml` with:

```xml
<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:padding="24dp">

    <TextView
        android:id="@+id/dateText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:textSize="14sp"
        android:textColor="?android:attr/textColorSecondary"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent" />

    <Button
        android:id="@+id/historyButton"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="@string/history"
        android:textSize="12sp"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintEnd_toEndOf="parent" />

    <TextView
        android:id="@+id/topicsText"
        android:layout_width="0dp"
        android:layout_height="wrap_content"
        android:layout_marginTop="8dp"
        android:textSize="20sp"
        android:textStyle="bold"
        app:layout_constraintTop_toBottomOf="@id/dateText"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent" />

    <TextView
        android:id="@+id/statusText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:layout_marginTop="16dp"
        app:layout_constraintTop_toBottomOf="@id/topicsText"
        app:layout_constraintStart_toStartOf="parent" />

    <Button
        android:id="@+id/playPauseButton"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="@string/play"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent" />

</androidx.constraintlayout.widget.ConstraintLayout>
```

- [ ] **Step 2: Replace `MainActivity.kt`**

Replace `android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt` with:

```kotlin
package com.shahbaz.dailytechupdates

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import com.shahbaz.dailytechupdates.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var player: ExoPlayer
    private lateinit var downloadStore: DownloadStore
    private val repository = EpisodeRepository()
    private var isPlaying = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        player = ExoPlayer.Builder(this).build()
        downloadStore = DownloadStore(applicationContext)
        downloadStore.purgeExpired()

        binding.playPauseButton.setOnClickListener { togglePlayback() }
        binding.statusText.setOnClickListener { loadTodayEpisode() }
        binding.historyButton.setOnClickListener {
            startActivity(Intent(this, HistoryActivity::class.java))
        }

        loadTodayEpisode()
    }

    private fun loadTodayEpisode() {
        binding.statusText.text = getString(R.string.loading_episode)
        lifecycleScope.launch {
            val episode = try {
                repository.getLatestEpisode()
            } catch (e: Exception) {
                null
            }
            if (episode == null || episode.audioUrl.isEmpty()) {
                binding.statusText.text = getString(R.string.no_episode_yet)
                return@launch
            }
            binding.dateText.text = episode.date
            binding.topicsText.text = episode.topicsCovered.joinToString(" • ")
            binding.statusText.text = getString(R.string.ready_to_play)
            val uri = resolvePlaybackUri(episode.audioUrl, downloadStore.localPathFor(episode.date))
            player.setMediaItem(MediaItem.fromUri(uri))
            player.prepare()
        }
    }

    private fun togglePlayback() {
        isPlaying = !isPlaying
        if (isPlaying) {
            player.play()
            binding.playPauseButton.text = getString(R.string.pause)
        } else {
            player.pause()
            binding.playPauseButton.text = getString(R.string.play)
        }
    }

    override fun onDestroy() {
        player.release()
        downloadStore.unregister()
        super.onDestroy()
    }
}
```

- [ ] **Step 3: Verify manually**

Run: `gradle testDebugUnitTest` — confirms the whole module compiles and all prior unit tests still pass.
Expected: PASS, 12 tests.

If a device/emulator is available, run: `gradle installDebug`, launch the app, confirm today's episode still loads/plays exactly as before, and confirm the new "History" button opens `HistoryActivity`. If no device/emulator is available, note that as a concern — this is the same real-device caveat as Task 5's Step 6.

- [ ] **Step 4: Commit**

```bash
git add android-app/app/src/main/res/layout/activity_main.xml android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt
git commit -m "Wire MainActivity to History screen and local-file playback"
```

---

### Task 7: CI workflow to run the Android unit test suite

**Files:**
- Create: `.github/workflows/android-tests.yml`

**Interfaces:**
- Consumes: nothing (standalone CI workflow).
- Produces: nothing consumed by other tasks — this is the authoritative automated verification that Tasks 1–3's unit tests (and any added later) actually pass, mirroring the precedent set for the Python pipeline (`.github/workflows/pipeline-tests.yml`), given this environment has no fully-configured local Android SDK/Gradle (see Global Constraints).

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/android-tests.yml`:

```yaml
name: Android Tests

on:
  push:
    paths:
      - "android-app/**"
      - ".github/workflows/android-tests.yml"
  pull_request:
    paths:
      - "android-app/**"
      - ".github/workflows/android-tests.yml"

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"

      - name: Set up Android SDK
        uses: android-actions/setup-android@v3

      - name: Install required SDK packages
        run: |
          yes | sdkmanager --licenses > /dev/null || true
          sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

      - name: Set up Gradle
        uses: gradle/actions/setup-gradle@v4
        with:
          # No gradlew is committed (see build-apk.yml's existing comment on this) - this
          # installs Gradle itself and puts it on PATH.
          gradle-version: "8.7"

      - name: Run unit tests
        working-directory: android-app
        run: gradle testDebugUnitTest --no-daemon
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/android-tests.yml
git commit -m "Add CI workflow to run the Android unit test suite"
git push
```

- [ ] **Step 3: Verify the workflow actually runs and passes**

Run: `gh run list --workflow=android-tests.yml --limit 1` — wait for it to appear, then `gh run watch --exit-status` on that run ID (or `gh run view <id> --log` if it already finished).
Expected: the run completes successfully, showing all 12 unit tests (3 from `PlaybackSourceTest` + 5 from `HistoryCacheTest` + 4 from `DownloadStoreTest`) passing under `testDebugUnitTest`. This is the real, independent confirmation of every test written in Tasks 1–3 — treat a failure here as a genuine bug to fix, not a CI-config problem to work around, exactly as this project treated the equivalent Python pipeline CI gap earlier.

---

## Self-review notes

- **Spec coverage:** §3.1–3.2 (history data model + paginated fetch) → Task 4. §3.3 (offline-browsable cache) → Task 2 + Task 4's fallback branch. §3.4 (DownloadStore + 30-day expiry) → Task 3. §3.5 (shared playback resolution) → Task 1. §4.1 (MainActivity's History button + local-file playback) → Task 6. §4.2 (History screen: list, row states, tap-to-play/tap-to-download) → Task 5. §4.3 (error/empty states) → Task 5 (`emptyText`) and Task 3 (download-failure revert, handled by `markResult(date, false)`). §5 (testing scope: `DownloadStoreTest`, `PlaybackSourceTest`, history-cache merge logic) → Tasks 1–3; §5's explicit "not unit-tested" carve-out for Activity/RecyclerView wiring → Tasks 4–6 verified manually. §6 (non-goals: no delete-download UI, no progress percentage, no pipeline changes) → correctly absent from every task.
- **Placeholder scan:** no TBD/TODO/"add error handling"-style steps; every step has real, complete code.
- **Type consistency:** `EpisodeSummary(date, topicsCovered, audioUrl, transcriptUrl)` (Task 4) matches its use in `HistoryAdapter`/`HistoryActivity` (Task 5). `DownloadRecord(date, localPath, downloadedAtEpochMillis)` (Task 3) matches `DownloadStore.localPathFor`/`startDownload` usage in Tasks 5–6. `resolvePlaybackUri(audioUrl: String, localPath: String?): String` (Task 1) is called identically in Task 5 (`HistoryActivity.play`) and Task 6 (`MainActivity.loadTodayEpisode`).
