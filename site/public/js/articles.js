function buildArticleCard(episode, showKey, showLabel) {
  const card = document.createElement("a");
  card.className = "article-card";
  card.href = `article.html?show=${showKey}&date=${episode.date}`;

  const meta = document.createElement("p");
  meta.className = "article-meta";
  meta.textContent = `${showLabel} · ${formatDate(episode.date)}`;
  card.appendChild(meta);

  const title = document.createElement("h2");
  title.textContent = episode.topics && episode.topics.length > 0 ? episode.topics.join(", ") : "Episode";
  card.appendChild(title);

  const preview = document.createElement("p");
  preview.className = "article-excerpt";
  preview.textContent = excerpt(episode.script);
  card.appendChild(preview);

  return card;
}

async function loadArticles() {
  const list = document.getElementById("articles-list");
  list.innerHTML = '<p class="status">Loading articles…</p>';
  try {
    const { tech, pm } = await fetchAllManifests();
    const combined = [
      ...tech.episodes.map((e) => ({ episode: e, showKey: "tech", showLabel: tech.show_label })),
      ...pm.episodes.map((e) => ({ episode: e, showKey: "pm", showLabel: pm.show_label })),
    ];
    combined.sort((a, b) => (a.episode.date < b.episode.date ? 1 : -1));

    if (combined.length === 0) {
      list.innerHTML = '<p class="status">No articles published yet.</p>';
      return;
    }
    list.innerHTML = "";
    for (const { episode, showKey, showLabel } of combined) {
      list.appendChild(buildArticleCard(episode, showKey, showLabel));
    }
  } catch (err) {
    list.innerHTML = `<p class="status error">Couldn't load articles (${err.message}).</p>`;
  }
}

loadArticles();
