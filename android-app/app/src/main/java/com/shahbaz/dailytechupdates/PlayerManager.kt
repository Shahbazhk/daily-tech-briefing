package com.shahbaz.dailytechupdates

/**
 * The queue is newest-first (index 0 = today). "Next" means chronologically newer
 * (toward index 0); "Previous" means chronologically older (toward the end of the list).
 * Both return null at their respective boundary rather than wrapping around.
 */
fun nextIndex(currentIndex: Int, size: Int): Int? =
    if (currentIndex > 0) currentIndex - 1 else null

fun previousIndex(currentIndex: Int, size: Int): Int? =
    if (currentIndex < size - 1) currentIndex + 1 else null

/**
 * Clamps a seek to [0, durationMs]. If durationMs is unknown (negative, e.g. ExoPlayer's
 * C.TIME_UNSET before metadata loads), only the lower bound is enforced.
 */
fun clampSeek(currentMs: Long, deltaMs: Long, durationMs: Long): Long {
    val target = currentMs + deltaMs
    val upperBound = if (durationMs >= 0) durationMs else Long.MAX_VALUE
    return target.coerceIn(0, upperBound)
}

/** mm:ss. A negative `ms` (used as the "unknown" sentinel for duration) renders as "--:--". */
fun formatTime(ms: Long): String {
    if (ms < 0) return "--:--"
    val totalSeconds = ms / 1000
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return "%02d:%02d".format(minutes, seconds)
}
