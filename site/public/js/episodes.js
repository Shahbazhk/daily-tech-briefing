function buildEpisodeCard(episode, showKey) {
  const card = document.createElement("article");
  card.className = "episode-card";

  const heading = document.createElement("h2");
  heading.textContent = formatDate(episode.date);
  card.appendChild(heading);

  if (episode.topics && episode.topics.length > 0) {
    const topics = document.createElement("p");
    topics.className = "topics";
    topics.textContent = episode.topics.join(", ");
    card.appendChild(topics);
  }

  const audio = document.createElement("audio");
  audio.controls = true;
  audio.src = episode.audio_url;
  card.appendChild(audio);

  if (episode.video_id) {
    const iframe = document.createElement("iframe");
    iframe.src = `https://www.youtube.com/embed/${episode.video_id}`;
    iframe.title = `${episode.date} video`;
    iframe.allowFullscreen = true;
    iframe.loading = "lazy";
    card.appendChild(iframe);
  }

  const link = document.createElement("a");
  link.className = "read-article-link";
  link.href = `article.html?show=${showKey}&date=${episode.date}`;
  link.textContent = "Read full transcript →";
  card.appendChild(link);

  return card;
}

async function loadShowEpisodes(showKey, sectionId) {
  const section = document.getElementById(sectionId);
  section.innerHTML = '<p class="status">Loading episodes…</p>';
  try {
    const manifest = await fetchManifest(showKey);
    if (!manifest.episodes || manifest.episodes.length === 0) {
      section.innerHTML = '<p class="status">No episodes published yet.</p>';
      return;
    }
    section.innerHTML = "";
    for (const episode of manifest.episodes) {
      section.appendChild(buildEpisodeCard(episode, showKey));
    }
  } catch (err) {
    section.innerHTML = `<p class="status error">Couldn't load episodes (${err.message}).</p>`;
  }
}
