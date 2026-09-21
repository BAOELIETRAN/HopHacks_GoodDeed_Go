/* The location notice, and the sheet for setting a location by hand.

   Lives in the app shell rather than in each screen, so there is exactly one
   place that can tell you the app is guessing -- and it tells you on every
   screen, not just the map. It names the town, too: the bug this replaces
   survived as long as it did because nothing on screen ever said "Baltimore",
   it only quietly behaved like it.
*/

import { api } from "./api.js";
import {
  REASON_TEXT, clearManualLocation, getLocation, setManualLocation,
} from "./location.js";
import { esc, h, ico, toast } from "./ui.js";
import { dispatch } from "./router.js";

let latest = null;       // the last position the app resolved
let barEl = null;
const placeNames = new Map(); // "lat,lng" (3dp) -> town name, per session

const gridKey = (loc) => `${loc.lat.toFixed(3)},${loc.lng.toFixed(3)}`;

/** Ask the backend what this coordinate is called, so the notice can say it.
 *  Failure is silent: an unnamed position is still a usable position. */
async function placeName(loc) {
  const key = gridKey(loc);
  if (placeNames.has(key)) return placeNames.get(key);
  placeNames.set(key, null); // don't ask twice while the first call is out
  try {
    const { label } = await api.geoReverse(loc.lat, loc.lng);
    if (label) placeNames.set(key, label);
    return label || null;
  } catch {
    return null;
  }
}

export function mountLocationBar(el) {
  barEl = el;
  window.addEventListener("gdg:location", (e) => {
    latest = e.detail;
    render();
  });
  render();
}

function render() {
  if (!barEl) return;
  const loc = latest;
  if (!loc) { barEl.hidden = true; return; }

  const named = placeNames.get(gridKey(loc));
  const where = named || loc.label || null;

  // A device fix is the normal case and gets no banner at all -- a permanent
  // notice saying everything is fine is just noise. The one exception is the
  // first few seconds after a manual location is cleared, handled by the toast.
  if (loc.source === "device") { barEl.hidden = true; ensureName(loc); return; }

  const body = {
    manual: `Showing what's near ${where || "the place you set"}.`,
    remembered: `Using your last known location${where ? ` (${where})` : ""}. ${REASON_TEXT[loc.reason] || ""}`,
    default: `We don't know where you are, so this is ${where || "a default spot"} — not your area. ${REASON_TEXT[loc.reason] || ""}`,
  }[loc.source] || "";

  barEl.className = `banner-loc${loc.source === "default" ? " urgent" : ""}`;
  barEl.replaceChildren(h(`
    <div class="banner-loc-row">
      <span class="banner-loc-icon">${ico("pin", { size: 15 })}</span>
      <span class="grow">${esc(body.trim())}</span>
      <button class="banner-loc-btn" data-set>${loc.source === "manual" ? "Change" : "Set location"}</button>
      ${loc.source === "manual" ? '<button class="banner-loc-btn" data-clear>Use my device</button>' : ""}
    </div>`));
  barEl.hidden = false;

  barEl.querySelector("[data-set]").onclick = () => openLocationSheet();
  barEl.querySelector("[data-clear]")?.addEventListener("click", async () => {
    const next = await clearManualLocation();
    toast(next.source === "device" ? "Using your device's location" : "Couldn't get a fix from your device");
    dispatch();
  });

  ensureName(loc);
}

function ensureName(loc) {
  if (placeNames.get(gridKey(loc)) !== undefined) return;
  placeName(loc).then((name) => { if (name) render(); });
}

/** Search for a place and adopt it as "where I am". */
export function openLocationSheet() {
  const sheet = h(`
    <div class="sheet-overlay" role="dialog" aria-modal="true" aria-label="Set your location">
      <div class="sheet loc-sheet">
        <div class="confirm-head">
          <strong>Where are you?</strong>
          <span>A city, a postcode or an address. Everything nearby is found around this point.</span>
        </div>
        <button class="btn btn-primary" data-device>${ico("pin", { size: 16 })} Use my device's location</button>
        <div class="loc-or"><span>or search</span></div>
        <form class="loc-form" data-form>
          <input type="search" id="loc-q" placeholder="e.g. Chicago, or 21218" autocomplete="off"
                 enterkeyhint="search" aria-label="Search for a place">
          <button class="btn btn-ghost btn-sm" type="submit" data-go>Search</button>
        </form>
        <p class="tiny" data-msg hidden></p>
        <div class="loc-results" data-results></div>
        <button class="sheet-item cancel" data-close>Cancel</button>
      </div>
    </div>`);

  const msg = sheet.querySelector("[data-msg]");
  const results = sheet.querySelector("[data-results]");
  const input = sheet.querySelector("#loc-q");
  const close = () => sheet.remove();

  const say = (text, isError = false) => {
    msg.textContent = text;
    msg.className = isError ? "err" : "tiny";
    msg.hidden = !text;
  };

  sheet.querySelector("[data-close]").onclick = close;
  sheet.onclick = (e) => { if (e.target === sheet) close(); };
  document.addEventListener("keydown", function onEsc(e) {
    if (e.key === "Escape") { document.removeEventListener("keydown", onEsc); close(); }
  });

  sheet.querySelector("[data-device]").onclick = async () => {
    say("Asking your device…");
    const next = await clearManualLocation();
    if (next.source === "device") {
      close();
      toast("Using your device's location");
      dispatch();
      return;
    }
    // Say which of the four failures it was; each has a different fix.
    say(REASON_TEXT[next.reason] || "Your device didn't give us a location.", true);
  };

  sheet.querySelector("[data-form]").onsubmit = async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (q.length < 2) return say("Type at least two characters.", true);

    say("Searching…");
    results.replaceChildren();
    let places;
    try {
      places = await api.geoSearch(q);
    } catch (err) {
      return say(err?.message || "Couldn't search for that place.", true);
    }
    if (!places.length) return say(`Nothing found for "${q}". Try a nearby city or a postcode.`, true);

    say("");
    results.replaceChildren(...places.map((p) => {
      const row = h(`<button class="loc-result"><strong>${esc(p.label.split(",")[0])}</strong><span>${esc(p.label)}</span></button>`);
      row.onclick = () => {
        setManualLocation({ lat: p.lat, lng: p.lng, label: p.label.split(",").slice(0, 2).join(",").trim() });
        close();
        toast(`Showing what's near ${p.label.split(",")[0]}`);
        dispatch();
      };
      return row;
    }));
  };

  (document.getElementById("app") || document.body).appendChild(sheet);
  input.focus();
}

/** Kick off a resolution so the banner has something to say on first paint. */
export function primeLocation() {
  getLocation().catch(() => { /* acquire() never rejects; belt and braces */ });
}
