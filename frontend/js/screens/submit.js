/* Submission flow -- the core loop.
   Quest detail -> photo + description + time -> POST /submissions -> score. */

import { api, ApiError, getLocation, setSession, state } from "../api.js";
import {
  deedIcon, directionsUrl, distanceLabel, esc, h, icon, prettyCategory, setupPhotoInput,
  statusbar, toast,
} from "../ui.js";
import { go } from "../router.js";
import { celebrate, companionSvg, stageFor } from "../companion.js";


/** Straight-line metres between a fix and a quest. Mirrors the server's
 *  haversine so the button and the API agree about "close enough". */
function metresAway(loc, quest) {
  const R = 6371000, toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(quest.lat - loc.lat), dLng = toRad(quest.lng - loc.lng);
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(loc.lat)) * Math.cos(toRad(quest.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

const formatAway = (m) => (m < 1000 ? `${Math.round(m)}m` : `${(m / 1000).toFixed(1)}km`);

/** Quest detail: the "why you can trust this" screen before starting. */
export function renderQuest(root, { quest }) {
  if (!quest) return go("quests");
  const pts = quest.estimated_points ?? 0;

  root.innerHTML = `
    ${statusbar()}
    <div class="appbar">
      <button data-back aria-label="Back">‹</button>
      <h3>Quest details</h3>
      <span></span>
    </div>
    <div class="pad stack">
      <div class="panel panel-yellow" style="height:180px;display:grid;place-items:center;position:relative">
        <div style="font-size:72px">${icon(quest.category)}</div>
        <span class="chip chip-dark" style="position:absolute;top:14px;right:14px">★ +${pts}</span>
      </div>

      <div>
        ${quest.verified ? `<div class="verified">✓ Verified nonprofit</div>` : `<div class="tiny">Unverified listing</div>`}
        <h2 style="margin:4px 0">${esc(prettyCategory(quest.category))} volunteering</h2>
        <p class="muted">${esc(quest.org_name)}</p>
      </div>

      <div class="meta-row">
        <span class="chip chip-quiet">⌖ ${distanceLabel(quest.distance_km)}</span>
        <span class="chip chip-quiet">◷ ${quest.quest_type === "monthly" ? "Monthly" : "Daily"}</span>
        <span class="chip chip-quiet">${esc(prettyCategory(quest.category))}</span>
      </div>

      <a class="btn-directions full" data-directions target="_blank" rel="noopener noreferrer">
        <span style="font-size:16px">🧭</span> Get directions in Google Maps
      </a>

      <div class="card">
        <h3>Where to go</h3>
        <p class="muted" style="margin-top:6px">${esc(quest.address || "Address on file")}</p>
        <hr class="divider">
        <h3>What you'll do</h3>
        <p class="muted" style="margin-top:6px">
          Head to ${esc(quest.org_name)}, help out, then photograph what you worked on.
          Check in with staff when you arrive.
        </p>
      </div>

      <div class="card">
        <h3>Why you can trust this</h3>
        <div style="margin-top:10px">
          <div class="list-row">
            <span class="grow muted">Legitimacy score</span>
            <strong>${(quest.legitimacy_score ?? 0).toFixed(2)} / 1.00</strong>
          </div>
          <div class="list-row">
            <span class="grow muted">Listing</span>
            <strong>${quest.verified ? "Verified nonprofit" : "Unverified"}</strong>
          </div>
          <div class="list-row">
            <span class="grow muted">Estimated reward</span>
            <strong>+${pts} pts</strong>
          </div>
        </div>
      </div>

      <div class="panel panel-blue">
        <p style="font-size:14px;font-weight:700">
          🛡️ Check in only when you reach the staffed entrance. Never share private information.
        </p>
      </div>

      <button class="btn btn-primary" data-start disabled>Checking where you are…</button>
      <p class="tiny center" id="startnote">
        You can start this quest once you're at the site. The clock then runs
        automatically — no typing in how long you stayed.
      </p>
    </div>`;

  root.querySelector("[data-back]").onclick = () => history.back();
  root.querySelector("[data-directions]").href = directionsUrl(quest.lat, quest.lng);

  const startBtn = root.querySelector("[data-start]");
  const note = root.querySelector("#startnote");

  // Proximity gate. The server enforces this too -- this is only so the
  // button explains itself instead of failing with a 403 after a tap.
  (async () => {
    const loc = await getLocation();
    const away = metresAway(loc, quest);
    const limit = 200; // matches CHECKIN_RADIUS_M

    if (away <= limit) {
      startBtn.disabled = false;
      startBtn.textContent = "I'm here — start the clock";
      note.textContent = "The clock runs while you're on site and stops if you leave.";
    } else {
      startBtn.disabled = true;
      startBtn.textContent = `Get closer to start (${formatAway(away)} away)`;
      note.textContent = `You need to be within ${limit}m of ${quest.org_name}. Tap Directions to head over.`;
    }
  })();

  startBtn.onclick = async () => {
    startBtn.disabled = true;
    startBtn.textContent = "Starting…";
    try {
      const loc = await getLocation();
      const session = await api.startCheckin({
        org_name: quest.org_name,
        org_lat: quest.lat,
        org_lng: quest.lng,
        lat: loc.lat,
        lng: loc.lng,
        category: quest.category,
        quest_type: quest.quest_type,
      });
      go("active", { checkin: session });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Couldn't start the quest";
      note.textContent = msg;
      toast(msg, true);
      startBtn.disabled = false;
      startBtn.textContent = "Try again";
    }
  };
}

/** The submission form itself. */
export async function renderSubmit(root, { quest, checkin, deedType } = {}) {
  const orgName = quest?.org_name || "";
  const measured = checkin && checkin.elapsed_minutes >= 0 ? checkin : null;

  // Types come from the server so the picker, the required fields and the
  // AI rubric can never disagree about what a deed needs.
  const types = await api.deedTypes();
  // A timed check-in is by definition in-person volunteering.
  let spec = types.find((t) => t.key === (measured ? "volunteer" : deedType)) || types[0];
  root.innerHTML = `
    ${statusbar()}
    <div class="appbar">
      <button data-back aria-label="Back">‹</button>
      <h3>Add proof</h3>
      <span></span>
    </div>
    <div class="pad stack">
      <div class="panel panel-dark">
        <div class="eyebrow" style="color:var(--yellow-deep)">Quest in progress</div>
        <h3 style="margin-top:4px">${esc(orgName || "Log a good deed")}</h3>
      </div>

      ${measured ? "" : `
        <div>
          <h3>What kind of good deed?</h3>
          <p class="muted" style="margin-top:6px">Each kind is checked differently.</p>
        </div>
        <div class="deed-grid" id="deed-grid">
          ${types.map((t) => `
            <button type="button" class="deed-tile" data-deed="${esc(t.key)}"
                    aria-selected="${t.key === spec.key}">
              <span class="deed-ico">${t.icon}</span>
              <span class="deed-label">${esc(t.label)}</span>
              <span class="deed-blurb">${esc(t.blurb)}</span>
            </button>`).join("")}
        </div>`}

      <div id="deed-fields"></div>

      ${measured
        ? `<div class="panel panel-mint">
             <div class="row-between">
               <div>
                 <strong style="font-size:14px">✓ ${measured.elapsed_minutes} minutes, verified</strong>
                 <p class="tiny" style="margin-top:3px">
                   Timed on site. Nothing to type in, and worth more than a self-reported shift.
                 </p>
               </div>
             </div>
             <input type="hidden" id="mins" value="${measured.elapsed_minutes}">
           </div>`
        : `<label class="field">
             <span>Time spent (minutes)</span>
             <input type="number" id="mins" min="0" max="600" step="5" value="45">
             <p class="tiny" style="margin-top:6px">
               Self-reported. Starting from the quest screen times it for you and scores higher.
             </p>
           </label>`}

      <div class="panel panel-yellow">
        <p style="font-size:13px;font-weight:700">
          AI checks the task, place and safety — not your identity.
        </p>
      </div>

      <p class="err" id="formerr" hidden></p>
      <button class="btn btn-primary" id="send">Submit deed</button>
    </div>`;

  const errEl = root.querySelector("#formerr");
  const sendBtn = root.querySelector("#send");
  const fieldsEl = root.querySelector("#deed-fields");
  let photoDataUrl = null;

  root.querySelector("[data-back]").onclick = () => history.back();

  /** Re-render the inputs for the selected deed type.
   *  Fields are driven by the spec rather than hardcoded, so a receipt
   *  upload never asks "how long did you stay". */
  function renderFields() {
    photoDataUrl = null;
    const needsPhoto = spec.photo_required;
    const needsTime = spec.time_required && !measured;
    const wantsOrg = spec.key !== "kindness" && spec.key !== "advocacy";

    fieldsEl.innerHTML = `
      <div class="panel panel-mint" style="margin-bottom:var(--s3)">
        <strong style="font-size:14px">${spec.icon} ${esc(spec.label)}</strong>
        <p class="tiny" style="margin-top:4px">
          ${esc(spec.evidence)} · up to ${spec.max_points} pts
        </p>
      </div>

      <label class="dropzone" id="dropzone">
        <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" id="photo">
        <div class="guide" id="guide">
          ${esc(spec.evidence)}
          <span style="display:block;font-weight:600;opacity:.75;margin-top:6px">
            ${needsPhoto ? "Required · JPEG or PNG" : "Optional for this kind of deed"}
          </span>
        </div>
      </label>

      ${wantsOrg ? `
        <label class="field" style="margin-top:var(--s3)">
          <span>Organization or cause</span>
          <input type="text" id="org" value="${esc(orgName)}" placeholder="e.g. Maryland Food Bank">
        </label>` : ""}

      <label class="field" style="margin-top:var(--s3)">
        <span>${spec.key === "kindness" ? "What did you do?" : "Tell us about it"}</span>
        <textarea id="desc" placeholder="Be specific — what you did, who for, what it looked like."></textarea>
      </label>

      ${measured ? `
        <div class="panel panel-mint">
          <strong style="font-size:14px">✓ ${measured.elapsed_minutes} minutes, verified</strong>
          <p class="tiny" style="margin-top:3px">
            Timed on site. Nothing to type in, and worth more than a self-reported shift.
          </p>
          <input type="hidden" id="mins" value="${measured.elapsed_minutes}">
        </div>`
        : needsTime ? `
        <label class="field">
          <span>Time spent (minutes)</span>
          <input type="number" id="mins" min="0" max="600" step="5" value="45">
          <p class="tiny" style="margin-top:6px">
            Self-reported. Starting from a quest times it for you and scores higher.
          </p>
        </label>`
        : `<input type="hidden" id="mins" value="0">`}
    `;

    setupPhotoInput({
      dropzone: fieldsEl.querySelector("#dropzone"),
      input: fieldsEl.querySelector("#photo"),
      guide: fieldsEl.querySelector("#guide"),
      onPhoto: (dataUrl) => { photoDataUrl = dataUrl; },
      onError: (message) => {
        errEl.textContent = message || "";
        errEl.hidden = !message;
      },
    });
  }

  root.querySelectorAll("[data-deed]").forEach((tile) => {
    tile.onclick = () => {
      spec = types.find((t) => t.key === tile.dataset.deed) || spec;
      root.querySelectorAll("[data-deed]").forEach((t) =>
        t.setAttribute("aria-selected", String(t.dataset.deed === spec.key)));
      errEl.hidden = true;
      renderFields();
    };
  });

  renderFields();

  sendBtn.onclick = async () => {
    const org = fieldsEl.querySelector("#org")?.value.trim() || "";
    const description = fieldsEl.querySelector("#desc").value.trim();
    const minutes = parseInt(fieldsEl.querySelector("#mins")?.value, 10) || 0;

    const problem =
      spec.photo_required && !photoDataUrl ? `This kind of deed needs evidence: ${spec.evidence.toLowerCase()}.`
      : description.length < 10 ? "Add a sentence or two about what you did."
      : spec.time_required && !measured && minutes <= 0 ? "Enter how many minutes you spent."
      : null;
    if (problem) {
      errEl.textContent = problem;
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;

    sendBtn.disabled = true;
    sendBtn.textContent = "Checking…";
    try {
      const loc = await getLocation();
      const result = await api.submit({
        deed_type: spec.key,
        org_name: org,
        photo_url: photoDataUrl || "",
        description,
        time_spent_minutes: minutes,
        lat: loc.lat,
        lng: loc.lng,
        submitted_at: new Date().toISOString(),
        // The server ignores the minutes above when this is present and
        // uses what it measured instead.
        checkin_id: measured ? measured.checkin_id : undefined,
      });
      if (state.user) {
        setSession(state.token, {
          ...state.user,
          tier: result.user_tier,
          tier_points: result.user_tier_points,
          current_streak: result.current_streak,
        });
      }
      go("result", { result });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Couldn't reach the server. Try again.";
      errEl.textContent = msg;
      errEl.hidden = false;
      toast(msg, true);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "Submit deed";
    }
  };
}

/** Result screen. Handles both the awarded and the rejected case -- a
 *  zero-point result is a normal outcome, not an error, and the rationale is
 *  the most useful thing on the screen when it happens. */
export function renderResult(root, { result }) {
  if (!result) return go("map");
  const awarded = (result.points ?? 0) > 0;
  const confidence = Math.round((result.authenticity_confidence ?? 0) * 100);

  root.innerHTML = `
    ${statusbar()}
    <div class="pad stack center" style="padding-top:28px">
      <div id="result-companion">
        ${companionSvg(result.user_tier_points ?? 0, {
          mood: awarded ? "happy" : "sleepy", size: 150,
        })}
      </div>
      <div class="eyebrow">AI review complete</div>
      <h1>${awarded ? "Good deed verified!" : "We couldn't verify this"}</h1>
      <p class="muted">${esc(result.rationale || "")}</p>

      <div class="card" style="text-align:left">
        <div class="center" style="font-size:44px;font-weight:800;color:${awarded ? "var(--green-press)" : "var(--ink-faint)"}">
          ${awarded ? "+" : ""}${result.points ?? 0} points
        </div>
        <div class="scorelines" style="margin-top:10px">
          <div><span>Kind of deed</span><span>${deedIcon(result.deed_type)} ${esc(prettyCategory(result.deed_type))}</span></div>
          <div><span>Toward your tier</span><span>+${result.tier_points ?? 0}</span></div>
          <div><span>Authenticity confidence</span><span>${confidence}%</span></div>
          <div>
            <span>Time logged</span>
            <span>${result.time_spent_minutes ?? 0} min${result.verified_presence ? " ✓ verified" : ""}</span>
          </div>
        </div>
      </div>

      ${result.is_personal_best
        ? `<div class="panel panel-yellow row-between"><span>🔥 ${result.current_streak}-day streak!</span><span class="chip chip-yellow">Personal best</span></div>`
        : result.current_streak
          ? `<div class="panel panel-yellow">🔥 ${result.current_streak}-day streak</div>`
          : ""}

      <div class="panel panel-mint row-between">
        <span style="font-weight:800">Your tier</span>
        <span>${esc(result.user_tier || "Bronze")} · ${result.user_tier_points ?? 0} pts</span>
      </div>

      ${awarded ? "" : `<p class="tiny">Nothing was deducted. Retake the photo at the site and submit again.</p>`}

      <button class="btn btn-primary" data-again>${awarded ? "Back to map" : "Try again"}</button>
      <button class="btn btn-ghost" data-map>Back to map</button>
    </div>`;

  if (awarded) {
    const before = stageFor((result.user_tier_points ?? 0) - (result.tier_points ?? 0)).key;
    const evolved = before !== stageFor(result.user_tier_points ?? 0).key;
    celebrate(root.querySelector("#result-companion .companion"), { evolved });
  }

  root.querySelector("[data-again]").onclick = () => go(awarded ? "today" : "submit", {});
  root.querySelector("[data-map]").onclick = () => go("map");
}
