/* Weekly recap: shown once a week, on open.
 *
 * "Once a week" is tracked per ISO week in localStorage rather than by a
 * timer, so it survives reloads, doesn't fire twice on a refresh, and
 * appears on the first open of a new week whenever that happens to be.
 *
 * Failure mode matters more than the happy path here: if the recap can't
 * load, nothing should appear at all. A broken modal blocking the app is a
 * far worse outcome than a missed summary.
 */

import { api } from "./api.js";
import { deedIcon, esc, h, ico, prettyCategory } from "./ui.js";

const KEY = "gdg_recap_seen_week";

/** ISO week key, e.g. "2026-W38". Weeks start Monday. */
function weekKey(d = new Date()) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;          // Sunday counts as 7
  t.setUTCDate(t.getUTCDate() + 4 - day);  // nearest Thursday
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
  return `${t.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

function alreadySeen() {
  try {
    return localStorage.getItem(KEY) === weekKey();
  } catch {
    return true; // storage blocked: never nag rather than nag every load
  }
}

function markSeen() {
  try { localStorage.setItem(KEY, weekKey()); } catch { /* fine */ }
}

/** Show the recap if this week's hasn't been seen. Safe to call on any load. */
export async function maybeShowRecap() {
  if (alreadySeen()) return;
  let data;
  try {
    data = await api.weeklyRecap();
  } catch {
    return; // never block the app on a summary
  }
  if (!data) return;
  markSeen();
  showRecap(data);
}

export function showRecap(data) {
  const zero = data.deed_count === 0 && data.micro_deed_count === 0;

  const overlay = h(`
    <div class="recap-overlay" role="dialog" aria-modal="true" aria-label="Your week">
      <div class="recap-card">
        <div class="eyebrow">Your week</div>
        <h2 class="recap-headline">${esc(data.headline)}</h2>
        <p class="recap-sub">${esc(data.subline)}</p>

        ${zero ? "" : `
          <div class="recap-stats">
            <div><strong>${data.points}</strong><span>points</span></div>
            <div><strong>${data.deed_count + data.micro_deed_count}</strong><span>deeds</span></div>
            <div><strong>${data.current_streak}</strong><span>day streak</span></div>
          </div>

          ${data.top_deed_type ? `
            <p class="recap-line">
              ${deedIcon(data.top_deed_type, { size: 16 })} Mostly ${esc(prettyCategory(data.top_deed_type)).toLowerCase()}
            </p>` : ""}
          ${data.friend_rank && data.friend_count > 1 ? `
            <p class="recap-line">${ico("trophy", { size: 16 })} ${data.friend_rank} of ${data.friend_count} on your team</p>` : ""}
        `}

        <div class="recap-tier">
          <div class="row-between" style="margin-bottom:6px">
            <strong style="font-size:13px">${esc(data.tier)}</strong>
            <span class="tiny">${
              data.points_to_next_tier == null
                ? "Top tier"
                : `${data.points_to_next_tier} pts to go`
            }</span>
          </div>
          <div class="bar"><i style="width:${tierPct(data)}%"></i></div>
        </div>

        <button class="btn btn-primary" data-close>
          ${zero ? "Let's fix that" : "Keep going"}
        </button>
      </div>
    </div>`);

  const close = () => overlay.remove();
  overlay.querySelector("[data-close]").onclick = close;
  // Click the backdrop or press Escape to dismiss -- a weekly summary
  // should never feel like something you have to fight past.
  overlay.onclick = (e) => { if (e.target === overlay) close(); };
  const onKey = (e) => {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); }
  };
  document.addEventListener("keydown", onKey);

  (document.getElementById("app") || document.body).appendChild(overlay);
  return overlay;
}

function tierPct(d) {
  if (d.points_to_next_tier == null) return 100;
  const span = d.tier_points + d.points_to_next_tier;
  if (!span) return 2;
  return Math.min(99, Math.max(2, Math.round((d.tier_points / span) * 100)));
}

export const _test = { weekKey, KEY };
