/* Profile: tier progress, streak, badges. */

import { api, ApiError, clearSession, state } from "../api.js";
import { esc, h, ico, tierBadge, toast } from "../ui.js";
import { go } from "../router.js";
import { stopLiveActivity } from "../live.js";
import { companionSvg, nextStage, stageFor, stageProgress, STAGES } from "../companion.js";
import { tierBar } from "../celebrate.js";

const ALL_BADGES = [
  { code: "first_shift", label: "First shift", icon: "badge_first" },
  { code: "ten_day_streak", label: "10-day streak", icon: "badge_streak" },
  { code: "trusted_10", label: "Trusted 10", icon: "badge_trusted" },
];

export async function renderProfile(root) {
  const user = (await api.me()) || state.user || {};
  const earned = new Set((user.badges || []).map((b) => b.code));
  const points = user.tier_points ?? 0;
  const stage = stageFor(points);
  const next = nextStage(points);
  const ring = (user.frames || []).filter((f) => f.unlocked).slice(-1)[0]?.ring || "#b9b09a";

  // The store is optional, and the profile must render with or without it --
  // an unreachable store costs you the collection line, not the screen.
  const portfolio = await api.portfolio().catch(() => null);
  const worn = (portfolio?.items || []).find(
    (i) => i.kind === "avatar" && i.code === (portfolio?.equipped_avatar ?? user.equipped_avatar),
  );
  const collected = portfolio?.animals_total
    ? `${portfolio.animals_collected}/${portfolio.animals_total} animals`
    : "";

  root.innerHTML = `
    <div class="appbar">
      <span></span><h3>Profile</h3>
      <button data-out aria-label="Sign out" title="Sign out">${ico("signout", { size: 20 })}</button>
    </div>
    <div class="pad stack">
      <div class="row" style="gap:var(--s4)">
        <span class="avatar framed" style="width:64px;height:64px;font-size:24px;--frame-ring:${esc(ring)}">
          ${worn
            ? `<span class="worn-avatar" title="${esc(worn.label)}">${worn.emoji}</span>`
            : user.avatar_url
              ? `<img src="${esc(user.avatar_url)}" alt="">`
              : esc((user.name || "?").slice(0, 1).toUpperCase())}
        </span>
        <div class="grow">
          <h2 style="font-size:26px">${esc(user.name || "You")}</h2>
          <p class="tiny">${user.username ? "@" + esc(user.username) : ""}${user.username && user.city ? " · " : ""}${user.city ? esc(user.city) : ""}</p>
        </div>
      </div>

      <div class="stats-strip">
        <div><strong>${user.current_streak ?? 0}</strong><span>day streak</span></div>
        <div><strong>${points}</strong><span>points</span></div>
        <div><strong>${esc(user.tier || "Bronze")}</strong><span>tier</span></div>
      </div>

      <button class="card coin-row" data-store>
        <span class="coin-mark" aria-hidden="true">${ico("coins", { size: 20 })}</span>
        <span class="grow" style="text-align:left">
          <strong class="coin-amount">${(user.coins ?? 0).toLocaleString()}</strong>
          <span class="muted tiny"> coins${collected ? ` · ${collected}` : ""}</span>
        </span>
        <span class="tiny" style="font-weight:600">Store ${ico("arrow", { size: 14 })}</span>
      </button>

      <div class="card" id="tier-slot"></div>

      <div class="section-title"><h3>Your companion</h3></div>
      <div class="card">
        <div class="companion-card">
          ${companionSvg(points, { mood: (user.current_streak ?? 0) > 0 ? "idle" : "sleepy", size: 116 })}
          <div class="companion-body">
            <div class="companion-name">${esc(stage.name)}</div>
            <p class="companion-blurb">${esc(stage.blurb)}</p>
            ${next ? `
              <div class="bar"><i style="width:${Math.round(stageProgress(points) * 100)}%"></i></div>
              <p class="companion-next">${next.at - points} pts to ${esc(next.name)}</p>`
              : `<p class="companion-next">Fully grown.</p>`}
          </div>
        </div>
        <div class="stage-track">
          ${STAGES.map((st) => `
            <div class="stage-dot ${points >= st.at ? "reached" : ""}" title="${esc(st.name)} at ${st.at} pts">
              <i></i>
              <em>${esc(st.name)}</em>
            </div>`).join("")}
        </div>
      </div>

      <div class="section-title"><h3>Profile frames</h3></div>
      <div class="card">
        <p class="tiny" style="margin-bottom:var(--s3)">Unlocked by total points. Purely cosmetic.</p>
        <div class="frame-grid">
          ${(user.frames || []).map((f) => `
            <div class="frame-tile ${f.unlocked ? "unlocked" : "locked"}">
              <span class="frame-ring" style="--frame-ring:${esc(f.ring)}">
                ${f.unlocked ? ico("check", { size: 18 }) : ico("lock", { size: 16 })}
              </span>
              <em>${esc(f.label)}</em>
              <span class="tiny">${f.at === 0 ? "default" : f.at + " pts"}</span>
            </div>`).join("")}
        </div>
      </div>

      <div class="section-title"><h3>Badges</h3></div>
      <div class="row" style="gap:10px;flex-wrap:wrap;align-items:stretch">
        ${ALL_BADGES.map((b) => `
          <div class="card badge-tile ${earned.has(b.code) ? "" : "locked"}">
            ${ico(b.icon, { size: 24 })}
            <span style="font-weight:600;font-size:14px">${esc(b.label)}</span>
            <span class="tiny">${earned.has(b.code) ? "Earned" : "Not yet"}</span>
          </div>`).join("")}
      </div>

      <div class="section-title"><h3>Your team</h3></div>
      <div class="card">
        <p class="muted">
          Everyone on a team shows up on each other's leaderboard.
          One person shares a code, everyone else enters it.
        </p>

        <hr class="divider">

        <h3>Start a team</h3>
        <p class="tiny" style="margin:4px 0 12px">Makes a code for others to join with.</p>
        <button class="btn btn-ghost" data-invite>Get my invite code</button>
        <div id="invite-out"></div>

        <hr class="divider">

        <h3>Join a team</h3>
        <p class="tiny" style="margin:4px 0 12px">Paste the code a teammate sent you.</p>
        <label class="field">
          <span class="sr-only">Team code</span>
          <input type="text" id="join-code" placeholder="e.g. 7QK4M2"
                 autocapitalize="characters" autocomplete="off" maxlength="16"
                 style="text-transform:uppercase;letter-spacing:.14em;font-weight:600">
        </label>
        <p class="err" id="join-err" hidden style="margin-top:8px"></p>
        <button class="btn btn-primary" id="join-btn" style="margin-top:12px">Join team</button>
        <div id="join-out"></div>
      </div>

      <button class="btn btn-ghost" data-signout style="margin-top:var(--s6)">Sign out</button>
    </div>`;

  root.querySelector("#tier-slot").replaceChildren(tierBar(points));

  const inviteBtn = root.querySelector("[data-invite]");
  inviteBtn.onclick = async () => {
    inviteBtn.disabled = true;
    try {
      const { invite_code } = await api.invite();
      const box = h(`
        <div style="margin-top:var(--s3);padding:var(--s4);background:var(--brand-tint);border-radius:var(--r-md)">
          <div class="tiny" style="color:var(--ink-2)">Share this code</div>
          <div class="figure" style="font-size:34px;letter-spacing:.14em;margin:4px 0 var(--s3)">${esc(invite_code)}</div>
          <button class="btn btn-ghost btn-sm" data-copy>${ico("copy", { size: 15 })} Copy code</button>
        </div>`);
      box.querySelector("[data-copy]").onclick = async () => {
        try {
          await navigator.clipboard.writeText(invite_code);
          toast("Code copied");
        } catch {
          // Clipboard needs a secure context; selecting the text still works.
          toast("Copy it by hand: " + invite_code);
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
        h(`<div class="note note-brand" style="margin-top:var(--s3)">
             ${ico("check-circle", { size: 18 })}
             <span><strong>You're on the team.</strong>
             ${group.member_count} member${group.member_count === 1 ? "" : "s"} so far. Check the leaderboard.</span>
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

  const signOut = () => { stopLiveActivity(); clearSession(); go("welcome"); };
  root.querySelector("[data-signout]").onclick = signOut;
  root.querySelector("[data-out]").onclick = signOut;
  root.querySelector("[data-store]").onclick = () => go("store");
}
