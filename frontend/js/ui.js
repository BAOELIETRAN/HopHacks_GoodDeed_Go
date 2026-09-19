/* Small shared UI helpers. No framework -- these keep the screens declarative
   without pulling in a build step. */

import { getRadiusMiles, RADIUS_CHOICES_MI, setRadiusMiles } from "./config.js";

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

/** Radius picker. Returns an element; calls onChange(miles) on selection. */
export function radiusPicker(onChange) {
  const el = h(`
    <div class="radius-picker">
      <span class="tiny" style="font-weight:800">Search within</span>
      <div class="pills" id="radius-pills"></div>
    </div>`);
  const pills = el.querySelector("#radius-pills");

  const paint = () => {
    const current = getRadiusMiles();
    pills.replaceChildren(...RADIUS_CHOICES_MI.map((mi) => {
      const b = h(`<button aria-selected="${mi === current}">${mi} mi</button>`);
      b.onclick = () => {
        setRadiusMiles(mi);
        paint();
        onChange?.(mi);
      };
      return b;
    }));
  };
  paint();
  return el;
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

/** Wire up a photo dropzone: pick → preview → report problems.
 *
 *  Written once and shared because the same bug appeared in three forms: the
 *  <img> was appended but never rendered, leaving the alt text on screen and
 *  no indication of what went wrong. Almost always an iPhone HEIC the
 *  browser cannot decode.
 *
 *  Guarantees:
 *   - the placeholder is only hidden once the image has actually decoded
 *   - a decode failure restores the placeholder and reports a real reason
 *   - object URLs are revoked when replaced, so picking ten photos doesn't
 *     leak ten blobs
 */
export function setupPhotoInput({ dropzone, input, guide, onPhoto, onError }) {
  let objectUrl = null;

  const release = () => {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  };

  const showPlaceholder = () => {
    dropzone.querySelector("img")?.remove();
    if (guide) guide.style.display = "";
    release();
  };

  const fail = (message) => {
    console.warn("[gdg] photo:", message);
    showPlaceholder();
    onPhoto?.(null);
    onError?.(message);
  };

  /* Two inputs, not one.
   *
   * `capture="environment"` is a hint that tells a phone to open the
   * camera directly; without it the same input opens the photo library.
   * You cannot have both from one element, and toggling the attribute
   * after a user gesture is unreliable across browsers -- so there are two
   * inputs and a small chooser decides which one to click.
   *
   * Desktop has no camera capture, so the button is hidden there rather
   * than opening a file dialog that pretends to be a camera. */
  const cameraInput = input.cloneNode();
  cameraInput.id = `${input.id || "photo"}-camera`;
  cameraInput.setAttribute("capture", "environment");
  input.removeAttribute("capture");
  input.parentNode.insertBefore(cameraInput, input);

  const handle = async (file) => {
    if (!file) return;
    console.info(
      "[gdg] photo selected:",
      file.name, file.type || "(no type)", `${Math.round(file.size / 1024)}KB`,
    );
    onError?.(null);

    let dataUrl;
    try {
      dataUrl = await compressImage(file);
    } catch (err) {
      return fail(err?.message || "Couldn't read that image.");
    }

    // Preview from an object URL: cheaper than decoding a multi-megabyte
    // base64 string, and it reveals a format the browser cannot render
    // before the user waits on an upload that would fail.
    release();
    objectUrl = URL.createObjectURL(file);

    const img = new Image();
    img.alt = "Your photo";
    const show = (el) => {
      dropzone.querySelector("img")?.remove();
      dropzone.appendChild(el);
      if (guide) guide.style.display = "none";
      onPhoto?.(dataUrl);
    };
    img.onload = () => show(img);
    img.onerror = () => {
      // The compressed copy can still be fine when the original is a
      // format the browser will not preview.
      const fallback = new Image();
      fallback.alt = "Your photo";
      fallback.onload = () => show(fallback);
      fallback.onerror = () =>
        fail(
          "This device saved that photo in a format browsers can't show (usually HEIC). " +
          "On iPhone: Settings › Camera › Formats › Most Compatible, then retake.",
        );
      fallback.src = dataUrl;
    };
    img.src = objectUrl;
  };

  input.onchange = () => handle(input.files?.[0]);
  cameraInput.onchange = () => handle(cameraInput.files?.[0]);

  // The dropzone is a <label>; without this every tap would also trigger
  // its bound input and bypass the chooser entirely.
  dropzone.addEventListener("click", (e) => {
    if (e.target === cameraInput || e.target === input) return;
    e.preventDefault();
    openChooser();
  });

  function openChooser() {
    if (!hasCamera()) return input.click();   // desktop: straight to files

    const sheet = h(`
      <div class="sheet-overlay" role="dialog" aria-modal="true" aria-label="Add a photo">
        <div class="sheet">
          <button class="sheet-item" data-cam><span>📷</span> Take photo</button>
          <button class="sheet-item" data-file><span>🖼️</span> Choose from files</button>
          <button class="sheet-item cancel" data-cancel>Cancel</button>
        </div>
      </div>`);
    const close = () => sheet.remove();
    sheet.querySelector("[data-cam]").onclick = () => { close(); cameraInput.click(); };
    sheet.querySelector("[data-file]").onclick = () => { close(); input.click(); };
    sheet.querySelector("[data-cancel]").onclick = close;
    sheet.onclick = (e) => { if (e.target === sheet) close(); };
    document.addEventListener("keydown", function esc(e) {
      if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
    });
    (document.getElementById("app") || document.body).appendChild(sheet);
  }

  return { reset: showPlaceholder, release, openChooser };
}

/** Is there a camera worth offering?
 *
 *  Coarse on purpose. enumerateDevices needs permission before it will
 *  name devices, and asking for camera access just to decide whether to
 *  draw a button is worse than occasionally showing it on a laptop that
 *  has a webcam anyway. */
export function hasCamera() {
  if (typeof navigator === "undefined") return false;
  // Touch plus a coarse pointer is the honest signal for "this is a phone
  // or tablet". The earlier version also tested `"capture" in input`, but
  // that IDL property is not reflected everywhere the *attribute* works,
  // so it produced false negatives on devices that do have a camera.
  const touch = navigator.maxTouchPoints > 0 || "ontouchstart" in globalThis;
  const coarse =
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function" ||
    window.matchMedia("(pointer: coarse)").matches;
  return Boolean(touch && coarse);
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
