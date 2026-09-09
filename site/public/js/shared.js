async function fetchManifest(showKey) {
  const response = await fetch(`data/${showKey}.json`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function fetchAllManifests() {
  const [tech, pm] = await Promise.all([fetchManifest("tech"), fetchManifest("pm")]);
  return { tech, pm };
}

function formatDate(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  if (isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}

function excerpt(script, maxLen = 160) {
  const clean = (script || "").replace(/\s+/g, " ").trim();
  if (clean.length <= maxLen) return clean;
  return clean.slice(0, maxLen).trim() + "…";
}
