const SHOWS = ["tech", "pm"];

function buildEpisodeCard(episode) {
  const card = document.createElement("article");
  card.className = "episode-card";

  const heading = document.createElement("h2");
  heading.textContent = episode.date;
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

  return card;
}

function renderEpisodes(section, manifest) {
  if (!manifest.episodes || manifest.episodes.length === 0) {
    section.innerHTML = '<p class="status">No episodes published yet.</p>';
    return;
  }
  section.innerHTML = "";
  for (const episode of manifest.episodes) {
    section.appendChild(buildEpisodeCard(episode));
  }
}

async function loadShow(showKey) {
  const section = document.getElementById(`section-${showKey}`);
  section.innerHTML = '<p class="status">Loading episodes…</p>';
  try {
    const response = await fetch(`data/${showKey}.json`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = await response.json();
    renderEpisodes(section, manifest);
  } catch (err) {
    section.innerHTML = `<p class="status error">Couldn't load episodes (${err.message}).</p>`;
  }
}

function switchTab(showKey) {
  for (const key of SHOWS) {
    document.getElementById(`section-${key}`).hidden = key !== showKey;
    document.getElementById(`tab-${key}`).classList.toggle("active", key === showKey);
  }
}

document.getElementById("tab-tech").addEventListener("click", () => switchTab("tech"));
document.getElementById("tab-pm").addEventListener("click", () => switchTab("pm"));

for (const key of SHOWS) {
  loadShow(key);
}
