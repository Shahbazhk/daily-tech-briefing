package com.shahbaz.dailytechupdates

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PlayerManagerTest {

    @Test
    fun `nextIndex returns the index toward index 0 (newer)`() {
        assertEquals(1, nextIndex(2, 5))
    }

    @Test
    fun `nextIndex returns null at index 0 (nothing newer)`() {
        assertNull(nextIndex(0, 5))
    }

    @Test
    fun `previousIndex returns the index toward the end (older)`() {
        assertEquals(3, previousIndex(2, 5))
    }

    @Test
    fun `previousIndex returns null at the last index (nothing older)`() {
        assertNull(previousIndex(4, 5))
    }

    @Test
    fun `clampSeek keeps a normal seek within bounds unchanged`() {
        assertEquals(45_000L, clampSeek(30_000L, 15_000L, 120_000L))
    }

    @Test
    fun `clampSeek clamps to zero when seeking before the start`() {
        assertEquals(0L, clampSeek(10_000L, -20_000L, 120_000L))
    }

    @Test
    fun `clampSeek clamps to duration when seeking past the end`() {
        assertEquals(120_000L, clampSeek(110_000L, 15_000L, 120_000L))
    }

    @Test
    fun `clampSeek does not clamp the upper bound when duration is unknown`() {
        assertEquals(25_000L, clampSeek(10_000L, 15_000L, -1L))
    }

    @Test
    fun `formatTime formats zero as 00 00`() {
        assertEquals("00:00", formatTime(0L))
    }

    @Test
    fun `formatTime formats over a minute correctly`() {
        assertEquals("01:05", formatTime(65_000L))
    }

    @Test
    fun `formatTime shows a placeholder for a negative (unknown) value`() {
        assertEquals("--:--", formatTime(-1L))
    }
}
