/* The running quest: a live clock the server owns.

   The elapsed time shown here is not counted by this screen -- it is
   whatever the server last returned. The local ticker only interpolates
   between heartbeats so the display doesn't freeze for 30 seconds at a
   time. If the two ever disagree, the server wins, because the server's
   number is the one that becomes points.

   The screen also watches distance: drifting past the leave radius ends the
   session server-side, so it warns before that happens rather than letting
   someone lose an hour of credit silently.
*/

import { api, ApiError, getLocation } from "../api.js";
import { esc, h, ico, icon, toast } from "../ui.js";
import { go } from "../router.js";

const HEARTBEAT_MS = 30_000;
const TICK_MS = 1000;

/* A local mirror of the running session.
 *
 * The server owns the clock -- this only exists so a reload shows the
 * timer immediately instead of a blank screen while /checkins/active
 * round-trips. Whatever the server says next always wins. */
const CACHE_KEY = "gdg_active_session";

function cacheSession(session) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ ...session, cached_at: Date.now() }));
  } catch { /* private mode; the server copy is the real one */ }
}

function cachedSession() {
  try {
    const raw = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
    if (!raw || raw.status !== "active") return null;
    // Anything older than a day is stale beyond usefulness; the server
    // would have swept the session long before this.
    if (Date.now() - (raw.cached_at || 0) > 86_400_000) return null;
    return raw;
  } catch {
    return null;
  }
}

export function clearCachedSession() {
  try { localStorage.removeItem(CACHE_KEY); } catch { /* fine */ }
}

let timers = [];

function clearTimers() {
  timers.forEach(clearInterval);
  timers = [];
}

/** Stop the loops when the user navigates away from this screen. */
export function teardownActive() {
  clearTimers();
}

const mmss = (totalSeconds) => {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h2 = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h2
    ? `${h2}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
};

const metresBetween = (a, b, c, d) => {
  const R = 6371000, toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(c - a), dLng = toRad(d - b);
  const h2 = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a)) * Math.cos(toRad(c)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h2));
};

export async function renderActive(root, { checkin: passed } = {}) {
  clearTimers();

  // Paint from the local mirror first so a reload shows the running clock
  // straight away, then reconcile with the server.
  let session = passed || cachedSession();
  const fromServer = await api.activeCheckin().catch(() => null);
  if (fromServer && fromServer.status === "active") {
    session = fromServer;
  } else if (fromServer !== null || !session) {
    // The server says there is no active session. Its word is final.
    clearCachedSession();
    return go("today");
  }
  cacheSession(session);

  root.innerHTML = `
    <div class="appbar"><span></span><h3>Quest in progress</h3><span></span></div>
    <div class="pad stack">
      <div class="clock-face">
        <p class="eyebrow">Timing your shift</p>
        <div class="clock" id="clock">0:00</div>
        <p class="tiny" id="clocknote">The clock is kept by the server, not this phone.</p>
      </div>

      <div class="card">
        <div class="row">
          <div class="thumb">${icon(session.category, { size: 24 })}</div>
          <div class="grow">
            <h3 class="truncate">${esc(session.org_name)}</h3>
            <p class="tiny">${session.quest_type === "monthly" ? "Monthly" : "Daily"} quest ·
               up to +${session.estimated_points} pts</p>
          </div>
        </div>
      </div>

      <div class="note note-brand" id="presence">
        ${ico("locate", { size: 18 })}
        <div class="grow">
          <div class="row-between">
            <strong>You're at the site</strong>
            <span class="chip" id="dist">…</span>
          </div>
          <p class="tiny" style="margin-top:6px;color:var(--ink-2)">
            Stay within ${session.leave_radius_m}m. If you walk further the timer stops
            by itself, and you keep the minutes you were actually there.
          </p>
        </div>
      </div>

      <button class="btn btn-primary" id="finish">Finish and add proof</button>
      <button class="btn btn-ghost" id="cancel">Cancel this quest</button>
      <p class="tiny">Timed sessions are worth more than typed-in time.</p>
    </div>`;

  const clockEl = root.querySelector("#clock");
  const distEl = root.querySelector("#dist");
  const presenceEl = root.querySelector("#presence");
  const noteEl = root.querySelector("#clocknote");

  // Interpolate between heartbeats so the display moves every second.
  let baseSeconds = session.elapsed_seconds;
  let baseAt = Date.now();
  const paint = () => {
    clockEl.textContent = mmss(baseSeconds + (Date.now() - baseAt) / 1000);
  };
  paint();
  timers.push(setInterval(paint, TICK_MS));

  const ended = (result) => {
    clearTimers();
    clearCachedSession();
    const why = {
      left_area: "You moved too far from the site, so the timer stopped.",
      timed_out: "We lost your location for a while, so the timer stopped.",
      too_long: "That session ran unusually long and was closed automatically.",
    }[result.end_reason] || "Session ended.";
    toast(why, result.end_reason !== "completed");
    if (result.elapsed_minutes >= 2) {
      go("submit", { quest: sessionToQuest(session), checkin: result });
    } else {
      go("map");
    }
  };

  const beat = async () => {
    let loc;
    try {
      loc = await getLocation();
    } catch {
      return; // one failed fix is not worth ending a session over
    }

    const away = metresBetween(loc.lat, loc.lng, session.org_lat, session.org_lng);
    distEl.textContent = `${Math.round(away)}m away`;

    // Warn before the server acts, so leaving is never a silent loss.
    const nearLimit = away > session.leave_radius_m * 0.7;
    presenceEl.className = `note ${nearLimit ? "note-alert" : "note-brand"}`;
    presenceEl.querySelector("strong").textContent =
      nearLimit ? "Head back, you're drifting" : "You're at the site";

    try {
      const updated = await api.heartbeat(session.checkin_id, loc.lat, loc.lng);
      baseSeconds = updated.elapsed_seconds;
      baseAt = Date.now();
      cacheSession(updated);
      noteEl.textContent = "The clock is kept by the server, not this phone.";
      if (updated.status !== "active") return ended(updated);
      session = { ...session, ...updated };
    } catch (err) {
      // Keep ticking locally through a blip; the server reconciles on the
      // next successful beat and its number is the one that counts.
      noteEl.textContent = "Reconnecting…";
      if (err instanceof ApiError && err.status === 404) go("map");
    }
  };

  beat();
  timers.push(setInterval(beat, HEARTBEAT_MS));

  root.querySelector("#finish").onclick = async () => {
    clearTimers();
    try {
      const done = await api.stopCheckin(session.checkin_id);
      clearCachedSession();
      if (done.elapsed_minutes < 2) {
        toast("That was under 2 minutes — not enough to log a quest", true);
        return go("map");
      }
      go("submit", { quest: sessionToQuest(session), checkin: done });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't finish that session", true);
    }
  };

  root.querySelector("#cancel").onclick = async () => {
    clearTimers();
    try { await api.stopCheckin(session.checkin_id); } catch { /* best effort */ }
    clearCachedSession();
    toast("Quest cancelled");
    go("map");
  };
}

function sessionToQuest(session) {
  return {
    org_name: session.org_name,
    lat: session.org_lat,
    lng: session.org_lng,
    category: session.category,
    quest_type: session.quest_type,
    estimated_points: session.estimated_points,
    address: "",
    legitimacy_score: 1,
    verified: true,
    distance_km: 0,
  };
}
