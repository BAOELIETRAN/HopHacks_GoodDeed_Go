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
import { esc, h, icon, statusbar, toast } from "../ui.js";
import { go } from "../router.js";

const HEARTBEAT_MS = 30_000;
const TICK_MS = 1000;

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

  let session = passed || (await api.activeCheckin().catch(() => null));
  if (!session || session.status !== "active") {
    return go("map");
  }

  root.innerHTML = `
    ${statusbar()}
    <div class="appbar"><span></span><h3>Quest in progress</h3><span></span></div>
    <div class="pad stack">
      <div class="panel panel-dark center" style="padding:var(--s6) var(--s4)">
        <div class="eyebrow" style="color:var(--green)">Timing your shift</div>
        <div id="clock" style="font-size:56px;font-weight:800;letter-spacing:-2px;margin:6px 0;
                               font-variant-numeric:tabular-nums">0:00</div>
        <div class="tiny" id="clocknote">The clock is kept by the server, not this phone.</div>
      </div>

      <div class="card">
        <div class="row">
          <div class="thumb">${icon(session.category)}</div>
          <div class="grow">
            <h3 class="truncate">${esc(session.org_name)}</h3>
            <p class="tiny">${session.quest_type === "monthly" ? "Monthly" : "Daily"} quest ·
               up to +${session.estimated_points} pts</p>
          </div>
        </div>
      </div>

      <div class="panel panel-mint" id="presence">
        <div class="row-between">
          <strong style="font-size:14px">You're at the site</strong>
          <span class="chip chip-quiet" id="dist">—</span>
        </div>
        <p class="tiny" style="margin-top:6px">
          Stay within ${session.leave_radius_m}m. Walk further and the timer stops
          automatically — you keep the minutes you were actually there.
        </p>
      </div>

      <button class="btn btn-primary" id="finish">Finish &amp; add proof</button>
      <button class="btn btn-ghost" id="cancel">Cancel this quest</button>
      <p class="tiny center">
        Verified sessions are worth more than typed-in time.
      </p>
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
    presenceEl.className = `panel ${nearLimit ? "panel-coral" : "panel-mint"}`;
    presenceEl.querySelector("strong").textContent =
      nearLimit ? "Head back — you're drifting" : "You're at the site";

    try {
      const updated = await api.heartbeat(session.checkin_id, loc.lat, loc.lng);
      baseSeconds = updated.elapsed_seconds;
      baseAt = Date.now();
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
