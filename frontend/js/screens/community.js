/* Community feed: open reports, claim, submit proof, poster confirms done. */

import { api, ApiError, getLocation, setSession, state } from "../api.js";
import { radiusKm } from "../config.js";
import { completionMessage, creditLabel } from "../credit.js";
import {
  confirmDelete, directionsUrl, emptyState, esc, h, ico, reportIcon, setupPhotoInput,
  skeleton, stamp, timeAgo, timeLeft, toast,
} from "../ui.js";
import { go } from "../router.js";

let tab = "nearby";

export async function renderCommunity(root) {
  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Your neighbourhood</p>
        <h2>Community</h2>
        <p class="muted">Jobs your neighbours posted. Pick one up, or post your own.</p>
      </div>
      <div class="head-actions">
        <button class="btn btn-primary btn-sm" id="report-btn">${ico("plus", { size: 16 })} Report a need</button>
      </div>
    </div>
    <div class="pad" style="padding-bottom:var(--s2)">
      <div class="pills" id="tabs">
        <button data-v="nearby" aria-selected="${tab === "nearby"}">Nearby</button>
        <button data-v="open" aria-selected="${tab === "open"}">Unclaimed</button>
        <button data-v="mine" aria-selected="${tab === "mine"}">Claimed by you</button>
        <button data-v="done" aria-selected="${tab === "done"}">Completed</button>
      </div>
    </div>
    <div class="pad" style="padding-top:var(--s3)"><div id="feed" class="grid-2">${skeleton(3)}</div></div>
    <div class="pad" style="padding-top:0">
      <p class="tiny">Public spaces only. Never enter private property or handle hazardous waste.</p>
    </div>`;

  const feed = root.querySelector("#feed");
  const loc = await getLocation();
  const selectTab = (v) => root.querySelector(`#tabs [data-v="${v}"]`).click();

  let latest = 0; // only the newest request may paint (see market.js)
  const load = async () => {
    const mine = ++latest;
    feed.innerHTML = skeleton(3);
    // "mine" isn't a server status -- it's a filter over everything I'm
    // involved in, whether I posted it or claimed it.
    const status = tab === "nearby" || tab === "mine" ? null : tab;
    let rows = await api.reports(loc.lat, loc.lng, radiusKm(), status);
    if (mine !== latest) return;
    if (tab === "mine") rows = rows.filter((r) => r.claimed_by_me || r.is_mine);

    if (!rows.length) {
      const blank = {
        done: {
          icon: "check-circle", title: "Nothing finished yet",
          body: "Cleanups appear here once the person who posted them confirms the work.",
        },
        mine: {
          icon: "community", title: "You haven't picked up a job",
          body: "Tap “I'll help” on any job to claim it. Jobs you post show up here too.",
          action: { label: "Browse nearby jobs", onClick: () => selectTab("nearby") },
        },
        open: {
          icon: "sprout", title: "Every nearby job has someone on it",
          body: "Check back later, or report something you've spotted.",
          action: { label: "Report a need", onClick: () => go("report") },
        },
        nearby: {
          icon: "pin", title: "Nothing reported nearby",
          body: "Litter, a broken bench, an overgrown path? Be the first to post it.",
          action: { label: "Report a need", onClick: () => go("report") },
        },
      }[tab];
      feed.replaceChildren(emptyState(blank));
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
  if (r.status === "done") action = stamp("Fixed", { seed: r.report_id, small: true });
  else if (mine && r.awaiting_confirmation)
    action = `<button class="btn btn-primary btn-sm" data-act="complete">Confirm it's done</button>`;
  else if (mine) action = `<span class="tiny">Your post</span>`;
  else if (iClaimed && r.awaiting_confirmation) action = `<span class="tiny">Waiting on the poster</span>`;
  else if (iClaimed) action = `<button class="btn btn-primary btn-sm" data-act="proof">Add proof</button>`;
  else if (r.is_full) action = `<span class="tiny">All spots taken</span>`;
  else action = `<button class="btn btn-primary btn-sm" data-act="claim">I'll help</button>`;

  const left = timeLeft(r.claim_expires_at);
  const urgent = left && !left.includes("h");

  const card = h(`
    <div class="card">
      <div class="row" style="align-items:flex-start">
        <div class="thumb">${r.photo_url
          ? `<img src="${esc(r.photo_url)}" alt="">`
          : reportIcon("other", { size: 24 })}</div>
        <div class="grow">
          <div class="meta-row" style="margin-bottom:6px">
            <span class="status-pill status-${esc(r.status)}">${esc(r.status)}</span>
            ${iClaimed ? `<span class="status-pill status-claimed">You joined</span>` : ""}
            ${(r.total_slots || 1) > 1
              ? `<span class="slot-pill ${r.is_full ? "full" : ""}">
                   ${r.filled_slots}/${r.total_slots} helpers
                 </span>` : ""}
            ${left ? `<span class="countdown ${urgent ? "urgent" : ""}">${ico("clock", { size: 13 })} ${esc(left)}</span>` : ""}
          </div>
          <h3>${esc(r.description || "Community need")}</h3>
          <p class="tiny" style="margin-top:4px">
            ${esc(r.reported_by_name || "A neighbour")} · ${timeAgo(r.created_at)} · ${
              // Once it's done, show what was actually paid to whoever is
              // looking (the helper or the poster), not the pre-job estimate.
              esc(creditLabel(r))
            }
          </p>
        </div>
      </div>
      ${iClaimed && left
        ? `<p class="tiny" style="margin-top:12px">Add proof before the timer runs out, or this goes back to the feed.</p>`
        : ""}
      ${r.status === "done" && r.award_rationale
        ? `<p class="tiny rationale" style="margin-top:10px">${esc(r.award_rationale)}</p>`
        : ""}
      <div class="row-between" style="margin-top:var(--s4);gap:10px">
        <a class="btn-directions" data-directions target="_blank" rel="noopener noreferrer">${ico("directions", { size: 16 })} Directions</a>
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
          toast("You're in. Head over, then add proof.");
        } else if (btn.dataset.act === "complete") {
          const done = await api.completeReport(r.report_id);
          toast(completionMessage(done));
          // The poster just earned points; refresh the cached profile so the
          // rest of the app shows them without a reload.
          api.me().then((me) => { if (me && state.token) setSession(state.token, me); }).catch(() => {});
        } else if (btn.dataset.act === "proof") {
          return go("proof", { report: r });
        }
        reload();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "That didn't work. Try again.", true);
        btn.disabled = false;
      }
    };
  }
  return card;
}

/** Post a new community need. */
export function renderReportForm(root) {
  root.innerHTML = `
    <div class="appbar">
      <button data-back aria-label="Back">${ico("back", { size: 22 })}</button><h3>Report a need</h3><span></span>
    </div>
    <div class="pad stack">
      <div class="note note-alert">
        ${ico("alert", { size: 18 })}
        <span>Public spaces only. Never enter private property or handle hazardous waste.</span>
      </div>

      <div class="card">
        <h3>What counts as a community need</h3>
        <ul class="checklist" style="margin-top:10px">
          <li>${ico("check", { size: 16 })}Litter, illegal dumping, an overflowing bin</li>
          <li>${ico("check", { size: 16 })}Graffiti, or a damaged bench, sign or fence</li>
          <li>${ico("check", { size: 16 })}Overgrown planting, a blocked path</li>
          <li class="no">${ico("close", { size: 16 })}Anything that needs emergency services or a professional crew</li>
          <li class="no">${ico("close", { size: 16 })}Favours, requests for help, or anything not in a public space</li>
        </ul>
      </div>

      <div>
        <label class="dropzone" id="dropzone">
          <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" id="photo">
          <div class="guide" id="guide">
            <span class="guide-icon">${ico("camera", { size: 30 })}</span>
            Add a photo of the problem
            <span class="guide-hint">JPEG or PNG. Show the problem clearly.</span>
          </div>
        </label>
      </div>

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
          The post stops taking helpers once that many have joined.
        </p>
      </div>

      <p class="err" id="formerr" hidden></p>
      <button class="btn btn-primary" id="send">Post to the feed</button>
      <p class="tiny">An AI check filters out spam before your post appears publicly.</p>
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
      const msg = err instanceof ApiError ? err.message : "Couldn't post that. Check your connection and try again.";
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
    <div class="appbar">
      <button data-back aria-label="Back">${ico("back", { size: 22 })}</button><h3>Add cleanup proof</h3><span></span>
    </div>
    <div class="pad stack">
      <div class="card">
        <p class="eyebrow" style="margin-bottom:6px">The job</p>
        <h3>${esc(report.description || "Community need")}</h3>
        <p class="tiny" style="margin-top:4px">Community job${
          (report.total_slots || 1) > 1 ? ` · ${report.filled_slots}/${report.total_slots} helpers` : ""}</p>
      </div>
      <div>
        <label class="dropzone" id="dropzone">
          <input type="file" accept="image/*" id="photo">
          <div class="guide" id="guide">
            <span class="guide-icon">${ico("camera", { size: 30 })}</span>
            Add a photo of the finished work
            <span class="guide-hint">Same spot as the original, if you can.</span>
          </div>
        </label>
      </div>
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
      <p class="tiny">
        The person who posted it confirms the work before it leaves the feed.
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
      toast("Proof sent. Now it's up to the poster to confirm.");
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
