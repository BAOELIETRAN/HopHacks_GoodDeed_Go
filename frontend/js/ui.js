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

export const DEED_ICON = {
  volunteer: "🙌", donation_money: "💳", donation_item: "📦", fundraising: "🎽",
  kindness: "💛", remote: "💻", advocacy: "📣", blood_donation: "🩸",
};
export const deedIcon = (key) => DEED_ICON[key] || DEED_ICON.volunteer;

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

/** A link to find out more about an organization.
 *
 *  Their own site when Places knows one, otherwise a search for the name
 *  and address. A dead "learn more" is worse than a search: people use
 *  this to check a place is real before travelling to it.
 */
export function orgLink(org) {
  const url = (org?.website || "").trim();
  if (url) return /^https?:\/\//i.test(url) ? url : `https://${url}`;
  const q = [org?.org_name, org?.address].filter(Boolean).join(" ");
  return `https://www.google.com/search?q=${encodeURIComponent(q)}`;
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


/** A "quest running" bar, shown wherever the user happens to be. */
export async function activeSessionBanner(mount) {
  if (!mount) return;
  const { api } = await import("./api.js");
  const { go } = await import("./router.js");
  let session;
  try {
    session = await api.activeCheckin();
  } catch {
    return;
  }
  if (!session || session.status !== "active") {
    mount.replaceChildren();
    return;
  }

  const started = new Date(session.started_at).getTime();
  const el = h(`
    <div class="pad" style="padding-top:0">
      <button class="session-banner">
        <span class="pulse"></span>
        <span class="grow" style="text-align:left">
          <strong>Quest running</strong>
          <em>${esc(session.org_name)}</em>
        </span>
        <span class="session-clock" data-clock>0:00</span>
      </button>
    </div>`);

  const clock = el.querySelector("[data-clock]");
  const tick = () => {
    const secs = session.elapsed_seconds + Math.max(0, (Date.now() - started) / 1000 - session.elapsed_seconds);
    const s = Math.floor(secs);
    clock.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  tick();
  const timer = setInterval(tick, 1000);
  // Stop when the banner leaves the page, so a stale interval doesn't keep
  // writing to a detached node.
  new MutationObserver((_, obs) => {
    if (!document.contains(el)) { clearInterval(timer); obs.disconnect(); }
  }).observe(document.body, { childList: true, subtree: true });

  el.querySelector(".session-banner").onclick = () => go("active", { checkin: session });
  mount.replaceChildren(el);
}

/** Ask before destroying something.
 *
 *  Deletion here removes points and, for a community post, work other
 *  people can see. A misplaced tap should not be able to do that silently,
 *  and an undo would be more machinery than a confirm is worth.
 */
export function confirmDelete({ title, body, confirmLabel = "Delete" }) {
  return new Promise((resolve) => {
    const sheet = h(`
      <div class="sheet-overlay" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="sheet">
          <div class="confirm-head">
            <strong>${esc(title)}</strong>
            ${body ? `<span>${esc(body)}</span>` : ""}
          </div>
          <button class="sheet-item danger" data-yes>${esc(confirmLabel)}</button>
          <button class="sheet-item cancel" data-no>Keep it</button>
        </div>
      </div>`);
    const done = (answer) => { sheet.remove(); resolve(answer); };
    sheet.querySelector("[data-yes]").onclick = () => done(true);
    sheet.querySelector("[data-no]").onclick = () => done(false);
    sheet.onclick = (e) => { if (e.target === sheet) done(false); };
    document.addEventListener("keydown", function esc2(e) {
      if (e.key === "Escape") { document.removeEventListener("keydown", esc2); done(false); }
    });
    (document.getElementById("app") || document.body).appendChild(sheet);
  });
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

/* The mock phone status bar is gone: this is a web app, and drawing a
   fake 9:41 and battery icon above the browser's own chrome just looked
   like a rendering error. Kept as a no-op so every screen needn't change. */
export const statusbar = () => "";

/* Photo capture (upload or camera, preview, retake) lives in photo.js so the
   pure parts can be tested without a DOM. Re-exported so every screen keeps
   importing from here. */
export { compressImage, fileToDataUrl, setupPhotoInput } from "./photo.js";
