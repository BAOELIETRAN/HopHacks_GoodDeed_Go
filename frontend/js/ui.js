/* Small shared UI helpers. No framework -- these keep the screens declarative
   without pulling in a build step. */

export const h = (html) => {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
};

/** Escape text before it goes anywhere near innerHTML. Org names, user
 *  descriptions and report text are all user- or third-party-controlled. */
export const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const tierBadge = (tier) =>
  `<span class="tier-badge tier-${esc(tier)}">${esc(tier)}</span>`;

export const CATEGORY_ICON = {
  food_bank: "🥕", homeless_shelter: "🏠", animal_shelter: "🐾", environmental: "🌿",
  community_cleanup: "🧹", education: "📚", healthcare: "🩺", senior_care: "🌻",
  youth_program: "⭐", crisis_support: "💛", veterans: "🎖️", disability_services: "🤝",
  refugee_services: "🕊️", arts_culture: "🎨", disaster_relief: "🚨",
  thrift_donation: "👕", religious: "🕊️", community_center: "🏛️", other: "✨",
};
export const icon = (category) => CATEGORY_ICON[category] || CATEGORY_ICON.other;

export const REPORT_ICON = {
  litter: "🗑️", illegal_dumping: "🚮", graffiti: "🎨", broken_infrastructure: "🔧",
  overgrowth: "🌳", hazard: "⚠️", abandoned_item: "📦", other: "📍",
};

export const prettyCategory = (c) =>
  String(c || "other").replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());

export function distanceLabel(km) {
  if (km == null) return "";
  const miles = km * 0.621371;
  return miles < 0.1 ? "nearby" : `${miles.toFixed(1)} mi`;
}

export function timeAgo(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (!isFinite(mins)) return "";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

export const initials = (name) =>
  String(name || "?").split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();

/** A Google Maps directions link to a coordinate.
 *
 *  Uses the universal Maps URL scheme, which hands off to the native Maps
 *  app on iOS and Android and falls back to the website on desktop.
 *  Coordinates rather than the org name: a name is a search that can resolve
 *  to the wrong branch, coordinates always land on the right door.
 */
export function directionsUrl(lat, lng, travelmode = "walking") {
  const params = new URLSearchParams({
    api: "1",
    destination: `${lat},${lng}`,
    travelmode,
  });
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

/** Countdown text for an expiring claim, e.g. "2h 14m left". */
export function timeLeft(iso) {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (!isFinite(ms) || ms <= 0) return "expired";
  const mins = Math.round(ms / 60000);
  if (mins < 60) return `${mins}m left`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m left`;
}

let toastTimer;
export function toast(message, isError = false) {
  document.querySelector(".toast")?.remove();
  const el = h(`<div class="toast${isError ? " error" : ""}">${esc(message)}</div>`);
  document.body.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 3400);
}

export const spinner = () => `<div class="spinner"></div>`;

export const empty = (emoji, title, sub = "") => `
  <div class="empty">
    <div class="big">${emoji}</div>
    <h3>${esc(title)}</h3>
    ${sub ? `<p class="muted" style="margin-top:8px">${esc(sub)}</p>` : ""}
  </div>`;

export const statusbar = () => `
  <div class="statusbar">
    <span>9:41</span>
    <span><span class="dot"></span>100%</span>
  </div>`;

/** Read a File into a data: URL. The backend stores photo_url as a string and
 *  the AI agent accepts data URLs, so the demo needs no file storage. */
export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Could not read that image"));
    reader.readAsDataURL(file);
  });
}

/** Shrink a photo before upload. Phone cameras produce 3-6MB JPEGs; sending
 *  those as base64 JSON is slow and can exceed request limits. */
export async function compressImage(file, maxEdge = 1024, quality = 0.82) {
  const dataUrl = await fileToDataUrl(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("bad image"));
      i.src = dataUrl;
    });
    const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
    if (scale === 1 && dataUrl.length < 900_000) return dataUrl;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", quality);
  } catch {
    return dataUrl; // HEIC or similar the canvas can't decode -- send as-is
  }
}
