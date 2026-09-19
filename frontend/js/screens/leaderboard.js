/* Leaderboard: Friends / Nearby, daily / weekly, tier badges per user. */

import { api } from "../api.js";
import { go } from "../router.js";
import { emptyState, esc, initials, skeleton, tierBadge } from "../ui.js";

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
    <div class="page-head">
      <div>
        <p class="eyebrow">Your team</p>
        <h2>Leaderboard</h2>
        <p class="muted">Only verified deeds count. Exact locations stay private.</p>
      </div>
    </div>
    <div class="pad" style="padding-bottom:0">
      <div class="segmented" id="period" role="tablist">
        <button data-v="daily" role="tab" aria-selected="${period === "daily"}">Today</button>
        <button data-v="weekly" role="tab" aria-selected="${period === "weekly"}">This week</button>
      </div>
    </div>
    <div class="pad" style="padding-top:var(--s3)">
      <div id="board">${skeleton(4)}</div>
    </div>`;

  const board = root.querySelector("#board");

  let latest = 0; // only the newest request may paint
  const load = async () => {
    const mine = ++latest;
    board.innerHTML = skeleton(4);
    const rows = await api.leaderboard("friends", period);
    if (mine !== latest) return;
    if (!rows.length) {
      board.replaceChildren(emptyState({
        icon: "trophy",
        title: period === "daily" ? "Nobody's logged a deed today" : "A quiet week so far",
        body: "Nobody on your team has logged anything yet. Be the first on the board.",
        action: { label: "Find a deed to do", onClick: () => go("today") },
      }));
      return;
    }
    board.innerHTML = `<div class="card" style="padding:var(--s2) var(--s2)">${renderBoard(rows)}</div>`;
  };

  root.querySelectorAll("#period button").forEach((btn) => {
    btn.onclick = () => {
      period = btn.dataset.v;
      root.querySelectorAll("#period button").forEach((b) =>
        b.setAttribute("aria-selected", String(b.dataset.v === period)));
      load();
    };
  });

  load();
}

/** One ranked list, everyone the same shape. The top three are marked by weight
 *  (a darker serif numeral), not by medals. Tier and deed count sit under the name
 *  so a long name never gets squeezed out on a phone. */
function renderBoard(rows) {
  return rows.map((r) => `
    <div class="lb-row ${r.is_you ? "you" : ""} ${r.rank <= 3 && r.points > 0 ? "top" : ""}">
      <span class="rank">${r.rank}</span>
      <span class="avatar">${esc(initials(r.name))}</span>
      <span class="grow">
        <span class="lb-name truncate" style="display:block">${esc(r.name)}${r.is_you ? ` <span class="tiny">(you)</span>` : ""}</span>
        <span class="lb-sub">
          ${tierBadge(tierFor(r.points))}
          ${r.deed_count ? `<span>${r.deed_count} deed${r.deed_count === 1 ? "" : "s"}</span>` : ""}
        </span>
      </span>
      <span class="lb-points">${r.points}<em>pts</em></span>
    </div>`).join("");
}
