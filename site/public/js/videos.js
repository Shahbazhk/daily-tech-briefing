function buildVideoCard(episode, showLabel) {
  const card = document.createElement("div");
  card.className = "video-card";

  const thumbWrap = document.createElement("div");
  thumbWrap.className = "video-thumb-wrap";

  const thumb = document.createElement("div");
  thumb.className = "video-thumb";
  thumb.style.backgroundImage = `url(https://img.youtube.com/vi/${episode.video_id}/hqdefault.jpg)`;
  thumb.setAttribute("role", "button");
  thumb.setAttribute("tabindex", "0");
  thumb.setAttribute("aria-label", `Play video for ${formatDate(episode.date)}`);

  const playIcon = document.createElement("span");
  playIcon.className = "play-icon";
  playIcon.setAttribute("aria-hidden", "true");
  playIcon.textContent = "▶";
  thumb.appendChild(playIcon);

  const playVideo = () => {
    const iframe = document.createElement("iframe");
    iframe.src = `https://www.youtube.com/embed/${episode.video_id}?autoplay=1`;
    iframe.title = `${episode.date} video`;
    iframe.allowFullscreen = true;
    iframe.allow = "autoplay; encrypted-media";
    thumbWrap.replaceChildren(iframe);
    thumbWrap.classList.add("playing");
  };
  thumb.addEventListener("click", playVideo);
  thumb.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      playVideo();
    }
  });

  thumbWrap.appendChild(thumb);

  const caption = document.createElement("p");
  caption.className = "video-caption";
  caption.textContent = `${showLabel} · ${formatDate(episode.date)}`;

  card.appendChild(thumbWrap);
  card.appendChild(caption);
  return card;
}

async function loadVideos() {
  const grid = document.getElementById("videos-grid");
  grid.innerHTML = '<p class="status">Loading videos…</p>';
  try {
    const { tech, pm } = await fetchAllManifests();
    const combined = [
      ...tech.episodes.filter((e) => e.video_id).map((e) => ({ episode: e, showLabel: tech.show_label })),
      ...pm.episodes.filter((e) => e.video_id).map((e) => ({ episode: e, showLabel: pm.show_label })),
    ];
    combined.sort((a, b) => (a.episode.date < b.episode.date ? 1 : -1));

    if (combined.length === 0) {
      grid.innerHTML = '<p class="status">No videos yet — check back after the next episode.</p>';
      return;
    }
    grid.innerHTML = "";
    for (const { episode, showLabel } of combined) {
      grid.appendChild(buildVideoCard(episode, showLabel));
    }
  } catch (err) {
    grid.innerHTML = `<p class="status error">Couldn't load videos (${err.message}).</p>`;
  }
}

loadVideos();
