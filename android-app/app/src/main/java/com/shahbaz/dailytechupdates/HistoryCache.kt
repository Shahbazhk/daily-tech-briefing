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
