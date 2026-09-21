/* Submission flow -- the core loop.
   Quest detail -> photo + description + time -> POST /submissions -> score. */

import { api, ApiError, setSession, state } from "../api.js";
import { REASON_TEXT, getLocation, isDeviceFix } from "../location.js";
import {
  deedIcon, directionsUrl, distanceLabel, esc, h, ico, icon, orgLink, prettyCategory,
  setupPhotoInput, stamp, stampDate, toast,
} from "../ui.js";
import { go } from "../router.js";
import { celebrate, companionSvg, stageFor } from "../companion.js";
import { tierBar } from "../celebrate.js";


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
    <div class="appbar">
      <button data-back aria-label="Back">${ico("back", { size: 22 })}</button>
      <h3>Quest details</h3>
      <span></span>
    </div>
    <div class="pad stack">
      <div class="row" style="align-items:flex-start;gap:var(--s4)">
        <div class="thumb" style="width:64px;height:64px">${icon(quest.category, { size: 30 })}</div>
        <div class="grow">
          ${quest.verified
            ? `<span class="verified">${ico("shield", { size: 15 })} Verified nonprofit</span>`
            : `<span class="tiny">Unverified listing</span>`}
          <h2 style="margin-top:4px">${esc(quest.org_name)}</h2>
          <p class="muted">${esc(prettyCategory(quest.category))} volunteering</p>
        </div>
      </div>

      <div class="meta-row">
        <span class="chip chip-quiet">${ico("locate", { size: 14 })} ${distanceLabel(quest.distance_km) || "Nearby"}</span>
        <span class="chip chip-quiet">${ico("clock", { size: 14 })} ${quest.quest_type === "monthly" ? "Monthly" : "Daily"}</span>
        <span class="chip chip-yellow">Up to +${pts} pts</span>
      </div>

      <div class="btn-row" style="gap:10px">
        <a class="btn-directions" data-directions target="_blank" rel="noopener noreferrer">
          ${ico("directions", { size: 16 })} Directions
        </a>
        <a class="btn-directions" data-website target="_blank" rel="noopener noreferrer">
          ${ico("link", { size: 16 })} ${quest.website ? "Their website" : "Look them up"}
        </a>
      </div>

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
        <div class="facts" style="margin-top:6px">
          <div><span>Legitimacy score</span><span>${(quest.legitimacy_score ?? 0).toFixed(2)} / 1.00</span></div>
          <div><span>Listing</span><span>${quest.verified ? "Verified nonprofit" : "Unverified"}</span></div>
          <div><span>Estimated reward</span><span>+${pts} pts</span></div>
        </div>
      </div>

      <div class="note note-brand">
        ${ico("shield", { size: 18 })}
        <span>Only check in once you're at the staffed entrance, and never share private information.</span>
      </div>

      <button class="btn btn-primary" data-start disabled>Checking where you are…</button>
      <p class="tiny" id="startnote">
        You can start once you're at the site. The clock then runs on its own,
        so there's no typing in how long you stayed.
      </p>
    </div>`;

  root.querySelector("[data-back]").onclick = () => history.back();
  root.querySelector("[data-directions]").href = directionsUrl(quest.lat, quest.lng);
  // Places knows a website for most orgs. When it doesn't, a search for the
  // name and address beats a dead link -- people still want to check the
  // place is real before walking there.
  root.querySelector("[data-website]").href = orgLink(quest);

  const startBtn = root.querySelector("[data-start]");
  const note = root.querySelector("#startnote");

  // Proximity gate. The server enforces this too -- this is only so the
  // button explains itself instead of failing with a 403 after a tap.
  (async () => {
    const loc = await getLocation({ fresh: true });
    const limit = 200; // matches CHECKIN_RADIUS_M

    // Only a live fix from the device can answer "am I standing there". A
    // remembered fix or a typed-in city would either lock out someone who is
    // genuinely on site or wave through someone who is not -- and the distance
    // it produced ("Get closer to start (2,400km away)") was nonsense anyway,
    // which is how a quietly defaulted location looked from the outside.
    if (!isDeviceFix(loc)) {
      startBtn.disabled = true;
      startBtn.textContent = "Can't tell where you are";
      note.textContent = `${REASON_TEXT[loc.reason] || "Your device didn't give us a location."} Starting the clock needs a live fix.`;
      return;
    }

    const away = metresAway(loc, quest);

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
      const loc = await getLocation({ fresh: true });
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
    <div class="appbar">
      <button data-back aria-label="Back">${ico("back", { size: 22 })}</button>
      <h3>Add proof</h3>
      <span></span>
    </div>
    <div class="pad stack">
      <div>
        <p class="eyebrow">${orgName ? "Your quest" : "New deed"}</p>
        <h2>${esc(orgName || "Log a good deed")}</h2>
      </div>

      ${measured ? "" : `
        <div id="deed-choose">
          <div class="form-section">
            <h3>What kind of good deed?</h3>
            <p class="muted">Each kind is checked differently.</p>
          </div>
          <div class="deed-grid" id="deed-grid">
            ${types.map((t) => `
              <button type="button" class="deed-tile" data-deed="${esc(t.key)}"
                      aria-selected="${t.key === spec.key}">
                <span class="deed-ico">${deedIcon(t.key, { size: 22 })}</span>
                <span class="deed-label">${esc(t.label)}</span>
                <span class="deed-blurb">${esc(t.blurb)}</span>
              </button>`).join("")}
          </div>
        </div>
        <div id="deed-chosen" hidden></div>`}

      <div id="deed-fields"></div>

      <p class="tiny">AI checks the task and the evidence, not who you are.</p>

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
      <div class="form-section">
        <label class="field-label" for="photo">${esc(spec.evidence)}</label>
        <label class="dropzone" id="dropzone">
          <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" id="photo">
          <div class="guide" id="guide">
            <span class="guide-icon">${deedIcon(spec.key, { size: 30 })}</span>
            ${needsPhoto ? "Add a photo" : "Add a photo (optional for this one)"}
            <span class="guide-hint">JPEG or PNG</span>
          </div>
        </label>
      </div>

      ${wantsOrg ? `
        <div class="form-section">
          <label class="field-label" for="org">Organization or cause</label>
          <input type="text" id="org" value="${esc(orgName)}" placeholder="e.g. Maryland Food Bank">
        </div>` : ""}

      <div class="form-section">
        <label class="field-label" for="desc">
          ${spec.key === "kindness" ? "What did you do?" : "Tell us about it"}
        </label>
        <textarea id="desc" placeholder="Be specific — what you did, who for, what it looked like."></textarea>
      </div>

      ${measured ? `
        <div class="form-section">
          <div class="verified-time">
            <strong>${ico("check", { size: 16 })} ${measured.elapsed_minutes} ${measured.elapsed_minutes === 1 ? "minute" : "minutes"}, timed</strong>
            <span>Measured on site, so there's nothing to type in.</span>
            <button type="button" class="btn-link" data-adjust-time>That's not right</button>
            <div data-adjust-box hidden>
              <label class="field-label" for="mins" style="margin-top:10px">
                Actual time on the deed (minutes)
              </label>
              <input type="number" id="mins" min="0" max="${measured.elapsed_minutes}"
                     step="5" value="${measured.elapsed_minutes}">
              <p class="field-hint">
                You can only lower this. If the timer ran through a break, trim it.
              </p>
            </div>
          </div>
        </div>`
        : needsTime ? `
        <div class="form-section">
          <div class="untimed-note">
            <strong>Not timed</strong>
            <span>
              This one scores on the deed itself. Next time, open the quest and
              tap “I'm here”. The app times it for you, and it's worth more.
            </span>
          </div>
        </div>`
        : ""}
    `;

    const adjustBtn = fieldsEl.querySelector("[data-adjust-time]");
    if (adjustBtn) {
      adjustBtn.onclick = () => {
        const box = fieldsEl.querySelector("[data-adjust-box]");
        box.hidden = !box.hidden;
        adjustBtn.textContent = box.hidden ? "That's not right" : "Never mind";
      };
    }

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

  const chooseEl = root.querySelector("#deed-choose");
  const chosenEl = root.querySelector("#deed-chosen");

  /** Collapse the eight-tile grid to a single confirmation row.
   *  Leaving the grid open pushed the actual form below the fold, and
   *  repeating the choice as a second full card directly under an
   *  identical-looking tile read as a rendering bug. */
  function showChosen() {
    if (!chooseEl || !chosenEl) return;
    chooseEl.hidden = true;
    chosenEl.hidden = false;
    chosenEl.innerHTML = `
      <div class="chosen-row">
        <span class="chosen-ico">${deedIcon(spec.key, { size: 22 })}</span>
        <span class="grow">
          <strong>${esc(spec.label)}</strong>
          <em>up to ${spec.max_points} pts</em>
        </span>
        <button type="button" class="btn-link" data-change>Change</button>
      </div>`;
    chosenEl.querySelector("[data-change]").onclick = () => {
      chooseEl.hidden = false;
      chosenEl.hidden = true;
    };
  }

  root.querySelectorAll("[data-deed]").forEach((tile) => {
    tile.onclick = () => {
      spec = types.find((t) => t.key === tile.dataset.deed) || spec;
      root.querySelectorAll("[data-deed]").forEach((t) =>
        t.setAttribute("aria-selected", String(t.dataset.deed === spec.key)));
      errEl.hidden = true;
      showChosen();
      renderFields();
    };
  });

  renderFields();

  sendBtn.onclick = async () => {
    const org = fieldsEl.querySelector("#org")?.value.trim() || "";
    const description = fieldsEl.querySelector("#desc").value.trim();
    const minutesEl = fieldsEl.querySelector("#mins");
    const minutes = minutesEl ? parseInt(minutesEl.value, 10) || 0 : 0;

    const problem =
      spec.photo_required && !photoDataUrl ? `This kind of deed needs evidence: ${spec.evidence.toLowerCase()}.`
      : description.length < 10 ? "Add a sentence or two about what you did."
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
        // uses what it measured instead -- unless the user trimmed it.
        checkin_id: measured ? measured.checkin_id : undefined,
        adjusted_minutes:
          measured && minutes < measured.elapsed_minutes ? minutes : undefined,
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
 *  the most useful thing on the screen when it happens.
 *
 *  The payoff is the ink stamp thumping down on the entry, not confetti. */
export function renderResult(root, { result }) {
  if (!result) return go("map");
  const awarded = (result.points ?? 0) > 0;
  const confidence = Math.round((result.authenticity_confidence ?? 0) * 100);

  root.innerHTML = `
    <div class="pad stack" style="padding-top:var(--s7)">
      <div>
        <p class="eyebrow">Review complete</p>
        <h1>${awarded ? "That one counts." : "We couldn't verify this one."}</h1>
      </div>

      <div class="card" style="padding:var(--s5)">
        <div class="row-between" style="align-items:flex-start">
          <div>
            <div class="figure" style="font-size:60px;line-height:1;color:${awarded ? "var(--brand-ink)" : "var(--ink-3)"}">
              ${awarded ? "+" : ""}${result.points ?? 0}
            </div>
            <div class="tiny" style="margin-top:4px">points</div>
          </div>
          ${stamp(awarded ? "Verified" : "Not verified", {
            sub: stampDate(result.submitted_at), tone: awarded ? "ok" : "no",
            seed: `${result.submission_id ?? ""}${result.rationale ?? ""}`, slam: true,
          })}
        </div>
        <p class="muted" style="margin-top:var(--s4)">${esc(result.rationale || "")}</p>
        <hr class="divider">
        <div class="scorelines">
          <div><span>Kind of deed</span><span>${esc(prettyCategory(result.deed_type))}</span></div>
          <div><span>Toward your tier</span><span>+${result.tier_points ?? 0}</span></div>
          <div><span>Authenticity confidence</span><span>${confidence}%</span></div>
          <div>
            <span>Time logged</span>
            <span>${result.time_spent_minutes ?? 0} min${result.verified_presence ? " \u00b7 timed on site" : ""}</span>
          </div>
        </div>
      </div>

      ${result.is_personal_best
        ? `<div class="note note-brand">${ico("flame", { size: 18 })}<span class="grow"><strong>${result.current_streak}-day streak.</strong> That's your longest yet.</span></div>`
        : result.current_streak
          ? `<div class="note note-brand">${ico("flame", { size: 18 })}<span>${result.current_streak}-day streak. Keep it going tomorrow.</span></div>`
          : ""}

      <div class="card companion-card">
        <div id="result-companion">
          ${companionSvg(result.user_tier_points ?? 0, {
            mood: awarded ? "happy" : "sleepy", size: 104,
          })}
        </div>
        <div class="companion-body" id="tier-slot"></div>
      </div>

      ${awarded ? "" : `<p class="tiny">Nothing was deducted. If the photo didn't show the work, retake it and submit again.</p>`}

      <button class="btn btn-primary" data-again>${awarded ? "Back to Today" : "Try again"}</button>
      <button class="btn btn-ghost" data-map>${awarded ? "See the map" : "Back to map"}</button>
    </div>`;

  // XP bar animates up from the pre-submission total, so the points just
  // earned are visible as movement rather than a number that was already there.
  const earned = result.tier_points ?? 0;
  const after = result.user_tier_points ?? 0;
  root.querySelector("#tier-slot").replaceChildren(
    tierBar(after, { animateFrom: Math.max(0, after - earned) }),
  );

  if (awarded) {
    const beforeStage = stageFor(after - earned).key;
    const evolved = beforeStage !== stageFor(after).key;
    celebrate(root.querySelector("#result-companion .companion"), { evolved });
  }

  root.querySelector("[data-again]").onclick = () => go(awarded ? "today" : "submit", {});
  root.querySelector("[data-map]").onclick = () => go("map");
}
