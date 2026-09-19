/* Profile: tier progress, streak, badges. */

import { api, clearSession, state } from "../api.js";
import { esc, h, statusbar, tierBadge, toast } from "../ui.js";
import { go } from "../router.js";

const ALL_BADGES = [
  { code: "first_shift", label: "First Shift", emoji: "🥕" },
  { code: "ten_day_streak", label: "10-Day Streak", emoji: "🔥" },
  { code: "trusted_10", label: "Trusted 10", emoji: "🛡️" },
];

export async function renderProfile(root) {
  const user = (await api.me()) || state.user || {};
  const earned = new Set((user.badges || []).map((b) => b.code));

  // Progress toward the next tier, derived from what the backend reports
  // rather than hardcoded thresholds, so tuning the economy needs no UI change.
  const toNext = user.points_to_next_tier;
  const pct = toNext == null ? 100
    : Math.max(4, Math.round((user.tier_points / (user.tier_points + toNext)) * 100));

  root.innerHTML = `
    ${statusbar()}
    <div class="appbar"><span></span><h3>Profile</h3><button data-out aria-label="Sign out">⚙</button></div>
    <div class="pad stack">
      <div class="row">
        <span class="avatar" style="width:58px;height:58px;font-size:19px;background:#c4bdf5">
          ${esc((user.name || "?").slice(0, 1).toUpperCase())}
        </span>
        <div class="grow">
          <h2 style="font-size:22px">${esc(user.name || "You")}</h2>
          <p class="tiny">${user.username ? "@" + esc(user.username) : ""}${user.city ? " · " + esc(user.city) : ""}</p>
        </div>
      </div>

      <div class="row" style="gap:8px">
        <span class="chip chip-flame">🔥 ${user.current_streak ?? 0} days</span>
        <span class="chip chip-yellow">★ ${user.tier_points ?? 0}</span>
        ${tierBadge(user.tier || "Bronze")}
      </div>

      <div class="panel panel-dark">
        <div class="row-between">
          <strong style="letter-spacing:.06em;text-transform:uppercase;color:var(--yellow-deep)">
            ${esc(user.tier || "Bronze")} helper
          </strong>
          <span style="font-size:13px;opacity:.9">
            ${toNext == null ? "Top tier reached" : `${toNext} to next tier`}
          </span>
        </div>
        <div class="bar" style="margin-top:12px"><i style="width:${pct}%"></i></div>
        <div class="row-between tiny" style="margin-top:8px;color:rgba(255,255,255,.75)">
          <span>Bronze 0</span><span>Silver 100</span><span>Gold 500</span>
        </div>
      </div>

      <div>
        <h3>Badges</h3>
        <div class="row" style="gap:10px;margin-top:10px;flex-wrap:wrap">
          ${ALL_BADGES.map((b) => `
            <div class="card" style="flex:1;min-width:88px;text-align:center;padding:12px 8px;opacity:${earned.has(b.code) ? 1 : .35}">
              <div style="font-size:26px">${b.emoji}</div>
              <div class="tiny" style="font-weight:800;margin-top:4px">${esc(b.label)}</div>
            </div>`).join("")}
        </div>
      </div>

      <div class="card">
        <div class="row-between">
          <div>
            <strong>Invite friends</strong>
            <p class="tiny">Share a code to compare on the Friends board.</p>
          </div>
          <button class="btn btn-primary btn-sm" data-invite>Get code</button>
        </div>
        <div id="invite-out"></div>
      </div>

      <button class="btn btn-ghost" data-signout>Sign out</button>
    </div>`;

  root.querySelector("[data-invite]").onclick = async () => {
    try {
      const { invite_code } = await api.invite();
      root.querySelector("#invite-out").replaceChildren(
        h(`<div class="panel panel-mint" style="margin-top:12px;text-align:center">
             <div class="tiny">Your invite code</div>
             <div style="font-size:26px;font-weight:800;letter-spacing:.14em">${esc(invite_code)}</div>
           </div>`));
    } catch {
      toast("Couldn't get a code — is the backend running?", true);
    }
  };

  const signOut = () => { clearSession(); go("welcome"); };
  root.querySelector("[data-signout]").onclick = signOut;
  root.querySelector("[data-out]").onclick = signOut;
}
