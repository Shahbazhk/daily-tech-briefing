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
