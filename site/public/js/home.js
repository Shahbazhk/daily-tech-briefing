function buildTeaserCard(episode, showKey, showLabel) {
  const card = document.createElement("a");
  card.className = "teaser-card";
  card.href = `article.html?show=${showKey}&date=${episode.date}`;

  const label = document.createElement("span");
  label.className = "teaser-label";
  label.textContent = showLabel;

  const date = document.createElement("h3");
  date.textContent = formatDate(episode.date);

  const topics = document.createElement("p");
  topics.textContent = episode.topics && episode.topics.length > 0 ? episode.topics.join(", ") : "";

  card.appendChild(label);
  card.appendChild(date);
  card.appendChild(topics);
  return card;
}

async function loadLatest() {
  const mount = document.getElementById("latest-episodes");
  if (!mount) return;
  try {
    const { tech, pm } = await fetchAllManifests();
    mount.innerHTML = "";
    if (tech.episodes[0]) mount.appendChild(buildTeaserCard(tech.episodes[0], "tech", tech.show_label));
    if (pm.episodes[0]) mount.appendChild(buildTeaserCard(pm.episodes[0], "pm", pm.show_label));
    if (!tech.episodes[0] && !pm.episodes[0]) {
      mount.innerHTML = '<p class="status">No episodes published yet.</p>';
    }
  } catch (err) {
    mount.innerHTML = `<p class="status error">Couldn't load latest episodes (${err.message}).</p>`;
  }
}

loadLatest();
