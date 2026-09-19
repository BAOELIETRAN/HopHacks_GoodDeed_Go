/* Small shared UI helpers. No framework -- these keep the screens declarative
   without pulling in a build step. */

import { hasIcon, ico } from "./icons.js";

export { ico };

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

/** The app's mark: a map pin with a tick in it, on the brand green. Drawn here, not
 *  an emoji, so it matches the favicon and scales cleanly. */
export const logoMark = (size = 28) => `
  <svg width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <rect width="32" height="32" rx="8" style="fill:var(--brand)"/>
    <g fill="none" stroke="#fdfbf5" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M25 13.5c0 6.2-6.9 12.7-9.2 14.7a1.3 1.3 0 0 1-1.6 0C11.9 26.2 5 19.7 5 13.5a10 10 0 0 1 20 0"/>
      <path d="m11.5 13.5 3 3 5-5.5"/>
    </g>
  </svg>`;

/* --- Icons ------------------------------------------------------------------
   The server sends emoji for a few things (a deed type's icon, an everyday deed's
   icon). Those are ignored: everything is drawn from the one icon family in
   icons.js, keyed by the server's own stable ids. */

/** A quest's category icon. */
export const icon = (category, opts) => ico(hasIcon(category) ? category : "other", opts);

/** A deed type's icon (volunteer, donation_money, ...). */
export const deedIcon = (key, opts) => ico(hasIcon(key) ? key : "volunteer", opts);

/** An everyday good deed's icon, by its id. */
export const microIcon = (id, opts) => ico(hasIcon(id) ? id : "kindness", opts);

/** A community report's category icon. */
export const reportIcon = (category, opts) => ico(hasIcon(category) ? category : "pin", opts);

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

/* --- The ink stamp -----------------------------------------------------------
   Marks a verified deed. It sits a little crooked, and each one differently:
   the tilt is derived from a seed (a report id, a date), so the same item always
   lands the same way but two items never line up. */

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "19 SEP 2026" -- the date as a rubber stamp would print it. */
export function stampDate(iso) {
  const d = iso ? new Date(iso) : new Date();
  if (!isFinite(d.getTime())) return "";
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** A stable tilt in degrees, between 2 and 8 either way, from any string. */
export function tiltFor(seed = "") {
  let n = 0;
  for (const ch of String(seed)) n = (n * 31 + ch.charCodeAt(0)) >>> 0;
  const magnitude = 2 + (n % 60) / 10;
  return (n & 64 ? 1 : -1) * magnitude;
}

/** Stamp markup. `tone` is "ok" (green) or "no" (red); `slam` plays the thump-down once. */
export function stamp(label, { sub = "", tone = "ok", seed = label, slam = false, small = false } = {}) {
  const cls = `stamp${tone === "no" ? " stamp-no" : ""}${small ? " stamp-sm" : ""}${slam ? " slam" : ""}`;
  return `<span class="${cls}" style="--tilt:${tiltFor(seed).toFixed(1)}deg">${esc(label)}${
    sub ? `<small>${esc(sub)}</small>` : ""}</span>`;
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
    sheet.querySelector("[data-no]").focus();
  });
}

let toastTimer;
export function toast(message, isError = false) {
  document.querySelector(".toast")?.remove();
  // Errors interrupt a screen reader; everything else waits its turn.
  const el = h(`<div class="toast${isError ? " error" : ""}" role="${isError ? "alert" : "status"}">${esc(message)}</div>`);
  document.body.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 3800);
}

/* --- Loading and empty states ---------------------------------------------------
   A blank screen or a spinner tells you nothing. A loading state keeps the shape of
   what is coming, and an empty state says what the place is for and what to do next. */

/** Placeholder rows shaped like a card, shown while a list loads. */
export const skeleton = (count = 3) => `
  <div class="sk-list" aria-hidden="true">
    ${Array.from({ length: count }, () => `
      <div class="sk-card">
        <div class="sk sk-block"></div>
        <div class="sk-lines">
          <div class="sk sk-line w40"></div>
          <div class="sk sk-line w85"></div>
          <div class="sk sk-line w60"></div>
        </div>
      </div>`).join("")}
  </div>
  <span class="sr-only" role="status">Loading</span>`;

/** An empty list, with a reason and (usually) a next step.
 *  `action` is `{ label, onClick }`; returns an element so the handler can be attached. */
export function emptyState({ icon: name = "inbox", title, body = "", action = null }) {
  const el = h(`
    <div class="empty-state">
      <div class="empty-art">${ico(name, { size: 28 })}</div>
      <h3>${esc(title)}</h3>
      ${body ? `<p>${esc(body)}</p>` : ""}
      ${action ? `<button class="btn btn-ghost" data-empty-action>${esc(action.label)}</button>` : ""}
    </div>`);
  if (action) el.querySelector("[data-empty-action]").onclick = action.onClick;
  return el;
}

/* Photo capture (upload or camera, preview, retake) lives in photo.js so the
   pure parts can be tested without a DOM. Re-exported so every screen keeps
   importing from here. */
export { compressImage, fileToDataUrl, setupPhotoInput } from "./photo.js";
