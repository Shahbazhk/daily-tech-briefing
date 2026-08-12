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
