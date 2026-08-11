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
