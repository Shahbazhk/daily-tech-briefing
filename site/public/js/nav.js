const NAV_LINKS = [
  { href: "index.html", label: "Home" },
  { href: "tech.html", label: "Tech Briefing" },
  { href: "pm.html", label: "PM Room" },
  { href: "articles.html", label: "Articles" },
  { href: "videos.html", label: "Videos" },
  { href: "about.html", label: "About" },
];

function currentPageName() {
  const path = window.location.pathname;
  const file = path.substring(path.lastIndexOf("/") + 1);
  return file === "" ? "index.html" : file;
}

function renderNav() {
  const mount = document.getElementById("site-header");
  if (!mount) return;
  const current = currentPageName();

  const linksHtml = NAV_LINKS.map(
    (link) => `<a href="${link.href}" class="nav-link${link.href === current ? " active" : ""}">${link.label}</a>`
  ).join("");

  mount.innerHTML = `
    <div class="nav-inner">
      <a href="index.html" class="brand">The Daily Standup</a>
      <button id="nav-toggle" class="nav-toggle" aria-label="Toggle menu" aria-expanded="false">☰</button>
      <nav id="nav-links" class="nav-links">${linksHtml}</nav>
    </div>
  `;

  const toggle = document.getElementById("nav-toggle");
  const links = document.getElementById("nav-links");
  toggle.addEventListener("click", () => {
    const isOpen = links.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(isOpen));
  });
}

renderNav();
