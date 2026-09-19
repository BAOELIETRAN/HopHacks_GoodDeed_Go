/* Community feed: open reports, claim, submit proof, poster confirms done. */

import { api, ApiError, getLocation } from "../api.js";
import { radiusKm } from "../config.js";
import {
  confirmDelete, directionsUrl, empty, esc, h, REPORT_ICON, setupPhotoInput,
  spinner, statusbar, timeAgo, timeLeft, toast,
} from "../ui.js";
import { go } from "../router.js";

let tab = "nearby";

export async function renderCommunity(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="appbar"><span></span><h3>Community</h3><span></span></div>
    <div class="pad stack">
      <div class="panel panel-coral">
        <h3>Spot a place that needs care?</h3>
        <p style="font-size:14px;margin-top:6px;opacity:.95">
          Post a public-space need. Never enter private property or handle hazardous waste.
        </p>
      </div>
      <div class="pills" id="tabs">
        <button data-v="nearby" aria-selected="${tab === "nearby"}">Nearby</button>
        <button data-v="open" aria-selected="${tab === "open"}">Unclaimed</button>
        <button data-v="mine" aria-selected="${tab === "mine"}">Claimed by you</button>
        <button data-v="done" aria-selected="${tab === "done"}">Completed</button>
      </div>
    </div>
    <div class="pad" style="padding-top:4px"><div id="feed" class="grid-2">${spinner()}</div></div>
    <div class="pad" style="padding-top:0">
      <button class="btn btn-dark" id="report-btn">Report a community need</button>
    </div>`;

  const feed = root.querySelector("#feed");
  const loc = await getLocation();

  const load = async () => {
    feed.innerHTML = spinner();
    // "mine" isn't a server status -- it's a filter over everything I'm
    // involved in, whether I posted it or claimed it.
    const status = tab === "nearby" || tab === "mine" ? null : tab;
    let rows = await api.reports(loc.lat, loc.lng, radiusKm(), status);
    if (tab === "mine") rows = rows.filter((r) => r.claimed_by_me || r.is_mine);

    if (!rows.length) {
      const blank = {
        done: ["✅", "No completed needs yet", "Finished cleanups show up here."],
        mine: ["🙌", "You haven't claimed anything", "Tap \u201cI'll help\u201d on a need to claim it."],
        open: ["🌱", "Nothing unclaimed nearby", "Every nearby need already has someone on it."],
        nearby: ["🌱", "No needs nearby", "Be the first to post one."],
      }[tab];
      feed.innerHTML = empty(...blank);
      return;
    }
    feed.replaceChildren(...rows.map((r) => reportCard(r, load)));
  };

  root.querySelectorAll("#tabs button").forEach((btn) => {
    btn.onclick = () => {
      tab = btn.dataset.v;
      root.querySelectorAll("#tabs button").forEach((b) =>
        b.setAttribute("aria-selected", String(b.dataset.v === tab)));
      load();
    };
  });
  root.querySelector("#report-btn").onclick = () => go("report");

  load();
}

function reportCard(r, reload) {
  const iClaimed = r.claimed_by_me;
  const mine = r.is_mine;

  let action = "";
  if (r.status === "done") action = `<span class="status-pill status-done">✓ Done</span>`;
  else if (mine && r.awaiting_confirmation)
    action = `<button class="btn btn-primary btn-sm" data-act="complete">Confirm &amp; remove</button>`;
  else if (mine) action = `<span class="tiny">Your post</span>`;
  else if (iClaimed && r.awaiting_confirmation) action = `<span class="tiny">Waiting on the poster</span>`;
  else if (iClaimed) action = `<button class="btn btn-primary btn-sm" data-act="proof">Add proof</button>`;
  else if (r.is_full) action = `<span class="tiny">Spots full</span>`;
  else action = `<button class="btn btn-primary btn-sm" data-act="claim">I'll help</button>`;

  const left = timeLeft(r.claim_expires_at);
  const urgent = left && !left.includes("h");

  const card = h(`
    <div class="card">
      <div class="row" style="align-items:flex-start">
        <div class="thumb">${r.photo_url
          ? `<img src="${esc(r.photo_url)}" alt="">`
          : REPORT_ICON.other}</div>
        <div class="grow">
          <div class="meta-row" style="margin-bottom:5px">
            <span class="status-pill status-${esc(r.status)}">${esc(r.status)}</span>
            ${iClaimed ? `<span class="status-pill status-claimed">You joined</span>` : ""}
            ${(r.total_slots || 1) > 1
              ? `<span class="slot-pill ${r.is_full ? "full" : ""}">
                   ${r.filled_slots}/${r.total_slots} helpers
                 </span>` : ""}
            ${left ? `<span class="countdown ${urgent ? "urgent" : ""}">⏱ ${esc(left)}</span>` : ""}
          </div>
          <h3>${esc(r.description || "Community need")}</h3>
          <p class="tiny" style="margin-top:3px">
            ${esc(r.reported_by_name || "A neighbour")} · ${timeAgo(r.created_at)} · ${
              // Once it's done, show what was actually awarded. Showing the
              // estimate on a finished post is how "no points were credited"
              // looked like a bug when the photo had simply scored low.
              r.status === "done"
                ? (r.points_awarded ? `+${r.points_awarded} pts awarded` : "no points awarded")
                : `+${r.estimated_points ?? 20} pts`
            }
          </p>
        </div>
      </div>
      ${iClaimed && left
        ? `<p class="tiny" style="margin-top:10px">Add proof before the timer runs out or this returns to the feed.</p>`
        : ""}
      ${r.status === "done" && r.award_rationale
        ? `<p class="tiny rationale" style="margin-top:8px">${esc(r.award_rationale)}</p>`
        : ""}
      <div class="row-between" style="margin-top:12px;gap:10px">
        <a class="btn-directions" data-directions target="_blank" rel="noopener noreferrer">🧭 Directions</a>
        <span class="row" style="gap:6px">
          ${mine ? `<button class="delete-btn" data-delete>Delete</button>` : ""}
          <span data-slot>${action}</span>
        </span>
      </div>
    </div>`);

  card.querySelector("[data-directions]").href = directionsUrl(r.lat, r.lng);

  const del = card.querySelector("[data-delete]");
  if (del) {
    del.onclick = async () => {
      const yes = await confirmDelete({
        title: "Delete this post?",
        body: r.filled_slots
          ? `${r.filled_slots} ${r.filled_slots === 1 ? "person has" : "people have"} already joined. They keep any points they earned.`
          : "It'll be removed for everyone.",
      });
      if (!yes) return;
      try {
        await api.deleteReport(r.report_id);
        toast("Post deleted");
        reload();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Couldn't delete that", true);
      }
    };
  }

  const btn = card.querySelector("[data-act]");
  if (btn) {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        if (btn.dataset.act === "claim") {
          await api.claimReport(r.report_id);
          toast("You're in — head over, then add proof");
        } else if (btn.dataset.act === "complete") {
          await api.completeReport(r.report_id);
          toast("Confirmed and removed from the feed");
        } else if (btn.dataset.act === "proof") {
          return go("proof", { report: r });
        }
        reload();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "That didn't work — try again", true);
        btn.disabled = false;
      }
    };
  }
  return card;
}

/** Post a new community need. */
export function renderReportForm(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="appbar">
      <button data-back aria-label="Back">‹</button><h3>Report a need</h3><span></span>
    </div>
    <div class="pad stack">
      <div class="panel panel-coral">
        <p style="font-size:14px;font-weight:700">
          Public spaces only. Never enter private property or handle hazardous waste.
        </p>
      </div>

      <div class="card">
        <strong style="font-size:14px">What counts as a community need</strong>
        <p class="tiny" style="margin-top:8px;line-height:1.7">
          ✓ Litter, illegal dumping, an overflowing bin<br>
          ✓ Graffiti or a damaged bench, sign or fence<br>
          ✓ Overgrown planting, a blocked path<br>
          <span style="opacity:.75">
          ✗ Anything needing emergency services or a professional crew<br>
          ✗ Favours, requests for help, or anything not in a public space
          </span>
        </p>
      </div>

      <label class="dropzone" id="dropzone">
        <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" capture="environment" id="photo">
        <div class="guide" id="guide">
          Tap to photograph the problem
          <span style="display:block;font-weight:600;opacity:.75;margin-top:6px">
            JPEG or PNG. Show the problem clearly.
          </span>
        </div>
      </label>

      <div class="form-section">
        <label class="field-label" for="desc">What needs fixing?</label>
        <textarea id="desc" placeholder="e.g. Overflowing bins at the corner of 3rd and Maple"></textarea>
      </div>

      <div class="form-section">
        <label class="field-label" for="slots">How many people are needed?</label>
        <select id="slots">
          ${[1,2,3,4,5,6,7,8,9,10].map((n) =>
            `<option value="${n}">${n} ${n === 1 ? "person" : "people"}</option>`).join("")}
        </select>
        <p class="field-hint">
          The post stops accepting helpers once that many have joined.
        </p>
      </div>

      <p class="err" id="formerr" hidden></p>
      <button class="btn btn-primary" id="send">Post to the feed</button>
      <p class="tiny center">An AI check filters spam before this appears publicly.</p>
    </div>`;

  const fileInput = root.querySelector("#photo");
  const dropzone = root.querySelector("#dropzone");
  const guide = root.querySelector("#guide");
  const errEl = root.querySelector("#formerr");
  const sendBtn = root.querySelector("#send");
  let photo = null;

  root.querySelector("[data-back]").onclick = () => history.back();
  setupPhotoInput({
    dropzone,
    input: fileInput,
    guide,
    onPhoto: (dataUrl) => { photo = dataUrl; },
    onError: (message) => {
      errEl.textContent = message || "";
      errEl.hidden = !message;
    },
  });

  sendBtn.onclick = async () => {
    const description = root.querySelector("#desc").value.trim();
    if (!photo) {
      errEl.textContent = "Add a photo of the problem.";
      errEl.hidden = false;
      return;
    }
    if (description.length < 5) {
      errEl.textContent = "Describe what needs fixing, and roughly where.";
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;
    sendBtn.disabled = true;
    sendBtn.textContent = "Checking…";
    try {
      const loc = await getLocation();
      await api.createReport({
        photo_url: photo,
        description,
        lat: loc.lat,
        lng: loc.lng,
        total_slots: parseInt(root.querySelector("#slots").value, 10) || 1,
      });
      toast("Posted to the community feed");
      go("community");
    } catch (err) {
      // A rejected report is a normal outcome, not a crash: the triage said
      // no and explained why. Show that reason rather than a status code.
      const msg = err instanceof ApiError ? err.message : "Couldn't post that — check your connection and try again.";
      errEl.textContent = msg;
      errEl.hidden = false;
      errEl.scrollIntoView({ block: "center", behavior: "smooth" });
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "Post to the feed";
    }
  };
}

/** Proof-of-cleanup for a report you claimed. */
export function renderProof(root, { report }) {
  if (!report) return go("community");
  root.innerHTML = `
    ${statusbar()}
    <div class="appbar">
      <button data-back aria-label="Back">‹</button><h3>Add cleanup proof</h3><span></span>
    </div>
    <div class="pad stack">
      <div class="panel panel-mint">
        <h3 style="font-size:16px">${esc(report.description || "Community need")}</h3>
        <p class="tiny">Community report${
          (report.total_slots || 1) > 1 ? ` · ${report.filled_slots}/${report.total_slots} helpers` : ""}</p>
      </div>
      <label class="dropzone" id="dropzone">
        <input type="file" accept="image/*" capture="environment" id="photo">
        <div class="guide" id="guide">Photograph the finished work</div>
      </label>
      <label class="field">
        <span>What did you do?</span>
        <textarea id="desc" placeholder="e.g. Collected 2 bags; glass marked for city pickup."></textarea>
      </label>
      <label class="field">
        <span>Time spent (minutes)</span>
        <input type="number" id="mins" min="0" max="600" step="5" value="30">
      </label>
      <p class="err" id="formerr" hidden></p>
      <button class="btn btn-primary" id="send">Submit proof</button>
      <p class="tiny center">
        The person who posted it confirms completion before it leaves the feed.
      </p>
    </div>`;

  const fileInput = root.querySelector("#photo");
  const dropzone = root.querySelector("#dropzone");
  const guide = root.querySelector("#guide");
  const errEl = root.querySelector("#formerr");
  const sendBtn = root.querySelector("#send");
  let photo = null;

  root.querySelector("[data-back]").onclick = () => history.back();
  setupPhotoInput({
    dropzone,
    input: fileInput,
    guide,
    onPhoto: (dataUrl) => { photo = dataUrl; },
    onError: (message) => {
      errEl.textContent = message || "";
      errEl.hidden = !message;
    },
  });

  sendBtn.onclick = async () => {
    const description = root.querySelector("#desc").value.trim();
    const minutes = parseInt(root.querySelector("#mins").value, 10) || 0;
    if (!photo) {
      errEl.textContent = "Add an after photo.";
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;
    sendBtn.disabled = true;
    sendBtn.textContent = "Submitting…";
    try {
      await api.submitProof(report.report_id, {
        photo_url: photo, description, time_spent_minutes: minutes,
      });
      toast("Proof submitted — waiting on the reporter");
      go("community");
    } catch (err) {
      errEl.textContent = err instanceof ApiError ? err.message : "Couldn't submit that";
      errEl.hidden = false;
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "Submit proof";
    }
  };
}
