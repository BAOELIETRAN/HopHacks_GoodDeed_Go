/* Submission flow -- the core loop.
   Quest detail -> photo + description + time -> POST /submissions -> score. */

import { api, ApiError, getLocation, setSession, state } from "../api.js";
import {
  compressImage, directionsUrl, distanceLabel, esc, h, icon, prettyCategory,
  statusbar, toast,
} from "../ui.js";
import { go } from "../router.js";

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

      <button class="btn btn-primary" data-start>Start quest</button>
      <p class="tiny center">Points are awarded after an AI authenticity check.</p>
    </div>`;

  root.querySelector("[data-back]").onclick = () => history.back();
  root.querySelector("[data-start]").onclick = () => go("submit", { quest });
  root.querySelector("[data-directions]").href = directionsUrl(quest.lat, quest.lng);
}

/** The submission form itself. */
export function renderSubmit(root, { quest } = {}) {
  const orgName = quest?.org_name || "";
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

      <div>
        <h3>Add completion proof</h3>
        <p class="muted" style="margin-top:6px">
          Photograph what you worked on. Avoid faces and personal details.
        </p>
      </div>

      <label class="dropzone" id="dropzone">
        <input type="file" accept="image/*" capture="environment" id="photo">
        <div class="guide" id="guide">Tap to add a photo<br><span style="font-weight:600">Fit the completed work inside</span></div>
      </label>

      <label class="field">
        <span>Organization</span>
        <input type="text" id="org" value="${esc(orgName)}" placeholder="e.g. Maryland Food Bank" required>
      </label>

      <label class="field">
        <span>What did you do?</span>
        <textarea id="desc" placeholder="Be specific — what you did, who with, what it looked like."></textarea>
      </label>

      <label class="field">
        <span>Time spent (minutes)</span>
        <input type="number" id="mins" min="0" max="600" step="5" value="45">
      </label>

      <div class="panel panel-yellow">
        <p style="font-size:13px;font-weight:700">
          AI checks the task, place and safety — not your identity.
        </p>
      </div>

      <p class="err" id="formerr" hidden></p>
      <button class="btn btn-primary" id="send">Use this photo</button>
    </div>`;

  const fileInput = root.querySelector("#photo");
  const guide = root.querySelector("#guide");
  const dropzone = root.querySelector("#dropzone");
  const errEl = root.querySelector("#formerr");
  const sendBtn = root.querySelector("#send");
  let photoDataUrl = null;

  root.querySelector("[data-back]").onclick = () => history.back();

  fileInput.onchange = async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      photoDataUrl = await compressImage(file);
      dropzone.querySelector("img")?.remove();
      dropzone.appendChild(h(`<img src="${photoDataUrl}" alt="Your proof photo">`));
      guide.style.display = "none";
    } catch (err) {
      toast(err.message || "Could not read that image", true);
    }
  };

  sendBtn.onclick = async () => {
    const org = root.querySelector("#org").value.trim();
    const description = root.querySelector("#desc").value.trim();
    const minutes = parseInt(root.querySelector("#mins").value, 10);

    const problem =
      !photoDataUrl ? "Add a photo of what you did."
      : !org ? "Which organization was this for?"
      : description.length < 10 ? "Add a sentence or two about what you did."
      : !Number.isFinite(minutes) || minutes < 0 ? "Enter how many minutes you spent."
      : null;
    if (problem) {
      errEl.textContent = problem;
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;

    sendBtn.disabled = true;
    sendBtn.textContent = "Checking your photo…";
    try {
      const loc = await getLocation();
      const result = await api.submit({
        org_name: org,
        photo_url: photoDataUrl,
        description,
        time_spent_minutes: minutes,
        lat: loc.lat,
        lng: loc.lng,
        submitted_at: new Date().toISOString(),
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
      sendBtn.textContent = "Use this photo";
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
      <div class="mascot"><div class="eyes"><i class="eye"></i><i class="eye"></i></div></div>
      <div class="eyebrow">AI review complete</div>
      <h1>${awarded ? "Good deed verified!" : "We couldn't verify this"}</h1>
      <p class="muted">${esc(result.rationale || "")}</p>

      <div class="card" style="text-align:left">
        <div class="center" style="font-size:44px;font-weight:800;color:${awarded ? "var(--green-press)" : "var(--ink-faint)"}">
          ${awarded ? "+" : ""}${result.points ?? 0} points
        </div>
        <div class="scorelines" style="margin-top:10px">
          <div><span>Toward your tier</span><span>+${result.tier_points ?? 0}</span></div>
          <div><span>Authenticity confidence</span><span>${confidence}%</span></div>
          <div><span>Time logged</span><span>${result.time_spent_minutes ?? 0} min</span></div>
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

  root.querySelector("[data-again]").onclick = () => go(awarded ? "map" : "submit", {});
  root.querySelector("[data-map]").onclick = () => go("map");
}
