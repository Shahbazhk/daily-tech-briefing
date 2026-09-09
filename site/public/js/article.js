function paragraphsFromScript(script) {
  return (script || "")
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}

async function loadArticle() {
  const params = new URLSearchParams(window.location.search);
  const showKey = params.get("show");
  const date = params.get("date");
  const container = document.getElementById("article-container");

  if (!showKey || !date) {
    container.innerHTML = '<p class="status error">Missing article reference.</p>';
    return;
  }

  try {
    const manifest = await fetchManifest(showKey);
    const episode = (manifest.episodes || []).find((e) => e.date === date);
    if (!episode) {
      container.innerHTML = '<p class="status error">Article not found.</p>';
      return;
    }

    document.title = `${manifest.show_label} — ${formatDate(episode.date)} — The Daily Standup`;

    const meta = document.createElement("p");
    meta.className = "article-meta";
    meta.textContent = `${manifest.show_label} · ${formatDate(episode.date)}`;

    const title = document.createElement("h1");
    title.textContent = episode.topics && episode.topics.length > 0 ? episode.topics.join(", ") : "Episode";

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = episode.audio_url;
    audio.className = "article-audio";

    container.innerHTML = "";
    container.appendChild(meta);
    container.appendChild(title);
    container.appendChild(audio);

    if (episode.video_id) {
      const iframe = document.createElement("iframe");
      iframe.src = `https://www.youtube.com/embed/${episode.video_id}`;
      iframe.title = `${episode.date} video`;
      iframe.allowFullscreen = true;
      iframe.loading = "lazy";
      iframe.className = "article-video";
      container.appendChild(iframe);
    }

    const paragraphs = paragraphsFromScript(episode.script);
    if (paragraphs.length === 0) {
      const empty = document.createElement("p");
      empty.className = "status";
      empty.textContent = "No transcript text available for this episode.";
      container.appendChild(empty);
    } else {
      for (const paragraph of paragraphs) {
        const p = document.createElement("p");
        p.textContent = paragraph;
        container.appendChild(p);
      }
    }
  } catch (err) {
    container.innerHTML = `<p class="status error">Couldn't load this article (${err.message}).</p>`;
  }
}

loadArticle();
