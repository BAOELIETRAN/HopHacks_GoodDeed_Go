/* Leaderboard: Friends / Nearby, daily / weekly, tier badges per user. */

import { api, state } from "../api.js";
import { deedIcon, empty, esc, initials, spinner, statusbar, tierBadge } from "../ui.js";

let scope = "nearby";
let period = "weekly";

/** The backend returns points per period, not cumulative tier points, so a
 *  row's tier is derived from the contract thresholds for display only. */
function tierFor(points) {
  if (points >= 500) return "Gold";
  if (points >= 100) return "Silver";
  return "Bronze";
}

export async function renderLeaderboard(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="appbar"><span></span><h3>Leaderboards</h3><span></span></div>
    <div class="pad stack">
      <div class="segmented" id="scope">
        <button data-v="nearby" aria-selected="${scope === "nearby"}">Nearby</button>
        <button data-v="friends" aria-selected="${scope === "friends"}">Friends</button>
      </div>
      <div class="pills center" id="period" style="justify-content:center">
        <button data-v="daily" aria-selected="${period === "daily"}">Daily</button>
        <button data-v="weekly" aria-selected="${period === "weekly"}">Weekly</button>
      </div>
    </div>
    <div class="pad" style="padding-top:4px">
      <div class="card" style="padding:var(--s4)" id="board">${spinner()}</div>
    </div>
    <p class="tiny center" style="padding:0 20px 20px">
      Only verified completions count. Exact locations stay private.
    </p>`;

  const board = root.querySelector("#board");

  const load = async () => {
    board.innerHTML = spinner();
    const rows = await api.leaderboard(scope, period);
    if (!rows.length) {
      board.innerHTML = empty(
        "🏅",
        scope === "friends" ? "No friends yet" : "No ranked deeds yet",
        scope === "friends"
          ? "Share an invite code from your profile to start a group."
          : `Nobody nearby has logged a verified deed ${period === "daily" ? "today" : "this week"}. Be first.`,
      );
      return;
    }
    board.innerHTML = renderBoard(rows);
  };

  const wire = (id, set) =>
    root.querySelectorAll(`#${id} button`).forEach((btn) => {
      btn.onclick = () => {
        set(btn.dataset.v);
        root.querySelectorAll(`#${id} button`).forEach((b) =>
          b.setAttribute("aria-selected", String(b.dataset.v === (id === "scope" ? scope : period))));
        load();
      };
    });
  wire("scope", (v) => { scope = v; });
  wire("period", (v) => { period = v; });

  load();
}

function renderBoard(rows) {
  const [first, second, third] = rows;
  // A podium with one real person and two blanks looks broken; only show it
  // once three people have actually scored.
  const ranked = rows.filter((r) => r.points > 0);
  const podium = ranked.length >= 3 ? `
    <div class="podium" style="margin-bottom:16px">
      <div class="slot p2">
        <div class="medal">🥈</div><div class="nm">${esc(second.name)}</div>
        <div class="pts">${second.points}</div>
      </div>
      <div class="slot p1">
        <div class="medal">🏆</div><div class="nm">${esc(first.name)}</div>
        <div class="pts">${first.points}</div>
        <span class="chip chip-yellow" style="margin-top:6px;font-size:11px">${first.deed_count} quests</span>
      </div>
      <div class="slot p3">
        <div class="medal">🥉</div><div class="nm">${esc(third.name)}</div>
        <div class="pts">${third.points}</div>
      </div>
    </div>` : "";

  const rest = rows.slice(ranked.length >= 3 ? 3 : 0).map((r) => `
    <div class="lb-row ${r.is_you ? "you" : ""}">
      <span class="rank">${r.rank}</span>
      <span class="avatar">${esc(initials(r.name))}</span>
      <span class="grow truncate" style="font-weight:800">
        ${esc(r.name)} ${r.is_you ? `<span class="tiny">YOU</span>` : ""}
        ${(r.deed_types || []).length
          ? `<span class="deed-badge" title="Kinds of deed logged">${
              (r.deed_types || []).map((d) => deedIcon(d)).join("")
            }</span>` : ""}
      </span>
      ${tierBadge(tierFor(r.points))}
      <span style="font-weight:800;color:var(--green-press)">${r.points}</span>
    </div>`).join("");

  return podium + rest;
}
