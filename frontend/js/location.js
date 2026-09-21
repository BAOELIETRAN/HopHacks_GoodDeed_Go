/* Where the user is.

   Every screen that asks "what's around me" comes through here.

   This used to live in api.js as a six-line helper that resolved a hardcoded
   Baltimore coordinate whenever the browser did not hand back a fix. That made
   four unrelated failures -- insecure origin, denied permission, timeout, no
   hardware -- look identical to a working app that simply happened to be in
   Baltimore. Nothing said otherwise except one toast on the map screen, so
   somebody standing in Chicago got confidently told about Maryland food banks.

   Order of preference, most trustworthy first:

     1. a place the user set by hand   -- stays until they clear it
     2. a live fix from the device     -- remembered for next time
     3. the last real fix we ever saw  -- their actual city, just stale
     4. the built-in default           -- always labelled as a guess

   Every result carries `source` and `approximate`, so a caller can refuse to
   act on a guess. Pinning a community report or starting a timed check-in at a
   coordinate nobody verified is worse than not doing it at all.

   No DOM in here: the notice that puts all of this on screen lives in
   locationbar.js, driven by the `gdg:location` event this module fires.
*/

import { LAST_RESORT_LOCATION } from "./config.js";

const MANUAL_KEY = "gdg_manual_location";
const LAST_FIX_KEY = "gdg_last_fix";

/* How long one resolved position is reused across screens. Walking map ->
   quests -> community must not re-acquire GPS three times over, but a position
   held for minutes is exactly how "I moved and nothing changed" happens. */
const MEMORY_MS = 45_000;

/* A cold GPS chip outdoors regularly takes 10-20 seconds. The old 6s timeout
   gave up while the phone was still working on it, and the giving-up path was
   the hardcoded default. */
const PRECISE_TIMEOUT_MS = 20_000;
const COARSE_TIMEOUT_MS = 8_000;

let memory = null;   // { at, loc } -- the cross-screen reuse window
let inFlight = null; // one acquisition at a time, however many screens ask

const readJson = (key) => {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; }
};

const writeJson = (key, value) => {
  // Private browsing throws on write. Losing the memory is survivable; the
  // app still works off a live fix each time.
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
};

const isCoord = (v) =>
  !!v && Number.isFinite(v.lat) && Number.isFinite(v.lng) && (v.lat !== 0 || v.lng !== 0);

/** Browsers refuse geolocation on an insecure origin and report it as a plain
 *  permission denial, with nothing to say it was the URL's fault. `run.sh`
 *  prints a bare http:// LAN address for testing on a phone, which lands
 *  precisely here, so this case is worth detecting by name. */
export const geoBlockedByOrigin = () =>
  !!navigator.geolocation && typeof window.isSecureContext === "boolean" && !window.isSecureContext;

/** Why we haven't got a real position. Shown to the user, so each one names
 *  the thing they can actually do something about. */
export const REASON_TEXT = {
  insecure:
    "This page is served over http://, and browsers only allow location on https:// or localhost. "
    + "Set your location by hand, or open the app over https.",
  unsupported: "This browser can't report a location. Set where you are by hand.",
  denied:
    "Location is turned off for this site. Enable it in your browser's site settings, or set where you are by hand.",
  unavailable: "Your device couldn't get a position fix. Set where you are by hand.",
  timeout: "Getting a position fix took too long. Try again, or set where you are by hand.",
};

const codeToReason = (err) =>
  ({ 1: "denied", 2: "unavailable", 3: "timeout" })[err?.code] || "unavailable";

function fix(options) {
  return new Promise((resolve, reject) =>
    navigator.geolocation.getCurrentPosition(resolve, reject, options));
}

async function livePosition() {
  // `maximumAge: 0` is the whole point of the first attempt. A cached fix is
  // exactly what a browser hands back after you have travelled, and it is the
  // wrong answer -- the previous code accepted one up to five minutes old.
  try {
    return await fix({ enableHighAccuracy: true, timeout: PRECISE_TIMEOUT_MS, maximumAge: 0 });
  } catch (err) {
    if (err?.code === 1) throw err; // denied: asking again only re-annoys
    // No satellite fix. Wifi and cell positioning are coarse, but they land in
    // the right city, which is all a 10-mile search radius needs.
    return await fix({ enableHighAccuracy: false, timeout: COARSE_TIMEOUT_MS, maximumAge: 60_000 });
  }
}

/** Let the shell redraw its location notice without every screen having to
 *  remember to tell it. */
function publish(loc) {
  window.dispatchEvent(new CustomEvent("gdg:location", { detail: loc }));
  return loc;
}

let warned = null;
function warnOnce(reason) {
  if (warned === reason) return;
  warned = reason;
  console.warn(`[gdg] no device location (${reason}): ${REASON_TEXT[reason] || reason}`);
}

/**
 * The user's position.
 *
 * @param {{fresh?: boolean}} opts `fresh` skips the cross-screen reuse window.
 *   Pass it where the answer must be current rather than recent: a presence
 *   heartbeat, or a proximity check about to gate a button.
 * @returns {Promise<{lat:number, lng:number, source:"manual"|"device"|"remembered"|"default",
 *   approximate:boolean, accuracyM?:number|null, label?:string|null, reason?:string|null}>}
 */
export function getLocation({ fresh = false } = {}) {
  // A place the user set by hand outranks everything. They know where they
  // are, and silently overriding them would be the original bug again.
  const manual = readManualLocation();
  if (manual) return Promise.resolve(publish(manual));

  if (!fresh && memory && Date.now() - memory.at < MEMORY_MS) {
    return Promise.resolve(publish(memory.loc));
  }
  if (inFlight) return inFlight;
  inFlight = acquire().finally(() => { inFlight = null; });
  return inFlight;
}

async function acquire() {
  let reason = null;

  if (!navigator.geolocation) reason = "unsupported";
  else if (geoBlockedByOrigin()) reason = "insecure";
  else {
    try {
      const pos = await livePosition();
      const loc = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracyM: Number.isFinite(pos.coords.accuracy) ? Math.round(pos.coords.accuracy) : null,
        source: "device",
        approximate: false,
        at: Date.now(),
        reason: null,
      };
      writeJson(LAST_FIX_KEY, { lat: loc.lat, lng: loc.lng, accuracyM: loc.accuracyM, at: loc.at });
      memory = { at: Date.now(), loc };
      return publish(loc);
    } catch (err) {
      reason = codeToReason(err);
    }
  }

  warnOnce(reason);

  // A stale real fix beats the built-in default every time: it is the user's
  // own city, and this app is entirely about what is near them. Still flagged
  // approximate, so nothing that needs a verified position acts on it.
  const last = readJson(LAST_FIX_KEY);
  const loc = isCoord(last)
    ? { ...last, source: "remembered", approximate: true, reason }
    : { ...LAST_RESORT_LOCATION, source: "default", approximate: true, reason, at: Date.now() };

  memory = { at: Date.now(), loc };
  return publish(loc);
}

/** A place the user typed, or null. */
export function readManualLocation() {
  const saved = readJson(MANUAL_KEY);
  if (!isCoord(saved)) return null;
  return { ...saved, source: "manual", approximate: false, reason: null };
}

export function setManualLocation({ lat, lng, label = null }) {
  const loc = { lat, lng, label, at: Date.now() };
  writeJson(MANUAL_KEY, loc);
  memory = null;
  return publish({ ...loc, source: "manual", approximate: false, reason: null });
}

/** Hand control back to the device. Returns the position that replaces it. */
export function clearManualLocation() {
  try { localStorage.removeItem(MANUAL_KEY); } catch { /* ignore */ }
  memory = null;
  warned = null;
  return getLocation({ fresh: true });
}

/** Throw away the reuse window so the next call measures again. */
export function forgetCachedLocation() {
  memory = null;
  warned = null;
}

/** True only for a position the device itself measured just now.
 *
 *  Two things are gated on this rather than on `!approximate`: starting a
 *  presence-verified check-in, and pinning a community report on the public
 *  map. Both make a claim about a physical place, and a typed-in city is not
 *  evidence of standing there.
 */
export const isDeviceFix = (loc) => loc?.source === "device" && !loc?.approximate;
