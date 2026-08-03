package com.shahbaz.dailytechupdates

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Reads the latest episode straight from GitHub Releases published by
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
        val assets = chosen.getJSONArray("assets")

        var audioUrl = ""
        var transcriptUrl = ""
        for (i in 0 until assets.length()) {
            val asset = assets.getJSONObject(i)
            val name = asset.getString("name")
            val url = asset.getString("browser_download_url")
            if (name.endsWith(".mp3")) audioUrl = url
            if (name.startsWith("transcript_") && name.endsWith(".json")) transcriptUrl = url
        }
        if (audioUrl.isEmpty()) return@withContext null

        var date = chosen.optString("tag_name", "").removePrefix("episode-")
        var script = ""
        var topics = emptyList<String>()
        if (transcriptUrl.isNotEmpty()) {
            val transcript = JSONObject(httpGet(transcriptUrl))
            date = transcript.optString("date", date)
            script = transcript.optString("script", "")
            transcript.optJSONArray("topics_covered")?.let { topicsArray ->
                topics = (0 until topicsArray.length()).map {
                    topicsArray.getJSONObject(it).optString("topic")
                }
            }
        }

        Episode(date = date, audioUrl = audioUrl, topicsCovered = topics, script = script)
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
