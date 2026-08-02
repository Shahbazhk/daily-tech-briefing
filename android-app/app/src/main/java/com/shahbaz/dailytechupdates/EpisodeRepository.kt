package com.shahbaz.dailytechupdates

import com.google.firebase.firestore.Query
import com.google.firebase.firestore.ktx.firestore
import com.google.firebase.ktx.Firebase
import kotlinx.coroutines.tasks.await

/** Reads episode metadata written by pipeline/publish/publish.py into the "episodes" Firestore collection. */
class EpisodeRepository {
    private val db = Firebase.firestore

    suspend fun getLatestEpisode(): Episode? {
        val snapshot = db.collection("episodes")
            .orderBy("date", Query.Direction.DESCENDING)
            .limit(1)
            .get()
            .await()
        return snapshot.documents.firstOrNull()?.toEpisode()
    }

    suspend fun getEpisode(date: String): Episode? {
        val doc = db.collection("episodes").document(date).get().await()
        if (!doc.exists()) return null
        return doc.toEpisode()
    }

    private fun com.google.firebase.firestore.DocumentSnapshot.toEpisode() = Episode(
        date = getString("date") ?: "",
        audioUrl = getString("audio_url") ?: "",
        topicsCovered = (get("topics_covered") as? List<*>)?.filterIsInstance<String>() ?: emptyList(),
        script = getString("script") ?: ""
    )
}
