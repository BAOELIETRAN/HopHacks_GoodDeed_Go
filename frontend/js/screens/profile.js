/* Profile: tier progress, streak, badges. */

import { api, ApiError, clearSession, state } from "../api.js";
import { esc, h, statusbar, tierBadge, toast } from "../ui.js";
import { go } from "../router.js";
import { companionSvg, nextStage, stageFor, stageProgress, STAGES } from "../companion.js";

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
        <span class="avatar" style="width:58px;height:58px;font-size:20px;overflow:hidden">
          ${user.avatar_url
            ? `<img src="${esc(user.avatar_url)}" alt="" style="width:100%;height:100%;object-fit:cover">`
            : esc((user.name || "?").slice(0, 1).toUpperCase())}
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
        <div class="row-between tiny" style="margin-top:8px">
          <span>Bronze 0</span><span>Silver 100</span><span>Gold 500</span>
        </div>
      </div>

      <div class="section-title"><h3>Your companion</h3></div>
      <div class="card companion-card">
        ${companionSvg(user.tier_points ?? 0, {
          mood: (user.current_streak ?? 0) > 0 ? "idle" : "sleepy", size: 170,
        })}
        <div class="companion-name">${esc(stageFor(user.tier_points ?? 0).name)}</div>
        <p class="companion-blurb">${esc(stageFor(user.tier_points ?? 0).blurb)}</p>
        ${nextStage(user.tier_points ?? 0) ? `
          <div class="bar on-light" style="margin-top:12px">
            <i style="width:${Math.round(stageProgress(user.tier_points ?? 0) * 100)}%"></i>
          </div>
          <p class="companion-next">
            ${nextStage(user.tier_points ?? 0).at - (user.tier_points ?? 0)} pts to
            ${esc(nextStage(user.tier_points ?? 0).name)}
          </p>` : `<p class="companion-next">Fully grown.</p>`}

        <div class="stage-track">
          ${STAGES.map((st) => `
            <div class="stage-dot ${(user.tier_points ?? 0) >= st.at ? "reached" : ""}"
                 title="${esc(st.name)} at ${st.at} pts">
              <span>${(user.tier_points ?? 0) >= st.at ? "●" : "○"}</span>
              <em>${esc(st.name)}</em>
            </div>`).join("")}
        </div>
      </div>

      <div class="section-title"><h3>Badges</h3></div>
      <div>
        <div class="row" style="gap:10px;flex-wrap:wrap">
          ${ALL_BADGES.map((b) => `
            <div class="card" style="flex:1;min-width:88px;text-align:center;padding:12px 8px;opacity:${earned.has(b.code) ? 1 : .35}">
              <div style="font-size:26px">${b.emoji}</div>
              <div class="tiny" style="font-weight:800;margin-top:4px">${esc(b.label)}</div>
            </div>`).join("")}
        </div>
      </div>

      <div class="section-title"><h3>Your team</h3></div>
      <div class="card">
        <p class="muted" style="font-size:14px">
          Everyone on a team shows up on each other's Friends leaderboard.
          One person shares a code, everyone else enters it.
        </p>

        <hr class="divider">

        <strong style="font-size:14px">Start a team</strong>
        <p class="tiny" style="margin:4px 0 10px">Generates a code for others to join with.</p>
        <button class="btn btn-ghost" data-invite>Get my invite code</button>
        <div id="invite-out"></div>

        <hr class="divider">

        <strong style="font-size:14px">Join a team</strong>
        <p class="tiny" style="margin:4px 0 10px">Paste the code a teammate sent you.</p>
        <label class="field">
          <input type="text" id="join-code" placeholder="e.g. 7QK4M2"
                 autocapitalize="characters" autocomplete="off" maxlength="16"
                 style="text-transform:uppercase;letter-spacing:.14em;font-weight:800;text-align:center">
        </label>
        <p class="err" id="join-err" hidden></p>
        <button class="btn btn-primary" id="join-btn" style="margin-top:10px">Join team</button>
        <div id="join-out"></div>
      </div>

      <button class="btn btn-ghost" data-signout>Sign out</button>
    </div>`;

  const inviteBtn = root.querySelector("[data-invite]");
  inviteBtn.onclick = async () => {
    inviteBtn.disabled = true;
    try {
      const { invite_code } = await api.invite();
      const box = h(`
        <div class="panel panel-mint" style="margin-top:12px;text-align:center">
          <div class="tiny">Share this code</div>
          <div style="font-size:28px;font-weight:800;letter-spacing:.18em;margin:6px 0">${esc(invite_code)}</div>
          <button class="btn btn-ghost btn-sm" data-copy>Copy code</button>
        </div>`);
      box.querySelector("[data-copy]").onclick = async () => {
        try {
          await navigator.clipboard.writeText(invite_code);
          toast("Code copied");
        } catch {
          // Clipboard needs a secure context; selecting the text still works.
          toast("Copy it manually: " + invite_code);
        }
      };
      root.querySelector("#invite-out").replaceChildren(box);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't get a code", true);
    } finally {
      inviteBtn.disabled = false;
    }
  };

  const joinBtn = root.querySelector("#join-btn");
  const joinErr = root.querySelector("#join-err");
  const joinInput = root.querySelector("#join-code");

  joinInput.addEventListener("keydown", (e) => { if (e.key === "Enter") joinBtn.click(); });

  joinBtn.onclick = async () => {
    const code = joinInput.value.trim().toUpperCase();
    if (!code) {
      joinErr.textContent = "Enter the code a teammate sent you.";
      joinErr.hidden = false;
      return;
    }
    joinErr.hidden = true;
    joinBtn.disabled = true;
    joinBtn.textContent = "Joining…";
    try {
      const group = await api.join(code);
      root.querySelector("#join-out").replaceChildren(
        h(`<div class="panel panel-mint" style="margin-top:12px;text-align:center">
             <strong>You're on the team</strong>
             <p class="tiny" style="margin-top:4px">${group.member_count} member${group.member_count === 1 ? "" : "s"} · check the Friends leaderboard</p>
           </div>`));
      joinInput.value = "";
      toast("Joined the team");
    } catch (err) {
      joinErr.textContent = err instanceof ApiError ? err.message : "Couldn't join with that code";
      joinErr.hidden = false;
    } finally {
      joinBtn.disabled = false;
      joinBtn.textContent = "Join team";
    }
  };

  const signOut = () => { clearSession(); go("welcome"); };
  root.querySelector("[data-signout]").onclick = signOut;
  root.querySelector("[data-out]").onclick = signOut;
}
