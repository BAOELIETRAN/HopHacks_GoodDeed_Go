/* Everyday good deeds: the low-friction half of the app.
 *
 * Quests need you to travel somewhere and photograph it. This is the list
 * for the other 23 hours -- hold a door, pick up three bits of litter, tell
 * someone they did a good job. One tap, no upload, no waiting on a vision
 * model.
 *
 * It is also the only route to the full deed form (donations, fundraising,
 * blood), which previously could only be reached by finishing a timed
 * check-in at an organization -- so most deed types were unloggable.
 */

import { api, ApiError, setSession, state } from "../api.js";
import { confirmDelete, esc, h, spinner, statusbar, toast } from "../ui.js";
import { go } from "../router.js";
import { quoteOfTheDay } from "../quotes.js";
import { activeSessionBanner } from "../ui.js";
import { celebrate, companionSvg, nextStage, stageFor, stageProgress } from "../companion.js";

export async function renderToday(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="hero" style="display:block">
      <div class="eyebrow">Today</div>
      <h2>Small things count</h2>
      <p class="muted" style="margin-top:4px">
        Quick, everyday good. No photo, no check-in — just do it and tap.
      </p>
    </div>
    <div class="pad" style="padding-top:0" id="companion-slot"></div>
    <div id="session-slot"></div>
    ${quoteCard()}
    <div class="pad" id="tasks" style="padding-top:0">${spinner()}</div>
    <div class="pad" style="padding-top:0">
      <div class="section-title"><h3>Something bigger?</h3></div>
      <button class="btn btn-ghost" id="log-deed">Log a donation, fundraiser or other deed</button>
      <p class="tiny center" style="margin-top:8px">
        Donations, goods, fundraising, remote help, blood, advocacy.
      </p>
    </div>`;

  root.querySelector("#log-deed").onclick = () => go("submit", {});

  const list = root.querySelector("#tasks");
  const companionSlot = root.querySelector("#companion-slot");

  const paintCompanion = () => {
    const points = state.user?.tier_points ?? 0;
    const stage = stageFor(points);
    const next = nextStage(points);
    // A broken streak makes it sleepy -- the nudge is the point.
    const mood = (state.user?.current_streak ?? 0) > 0 ? "idle" : "sleepy";
    companionSlot.innerHTML = `
      <div class="card companion-card">
        ${companionSvg(points, { mood, size: 168 })}
        <div class="companion-name">${stage.name}
          <span class="chip chip-quiet" style="font-size:11px">${points} pts</span>
        </div>
        <p class="companion-blurb">${esc(stage.blurb)}</p>
        ${next ? `
          <div class="bar on-light" style="margin-top:12px">
            <i style="width:${Math.round(stageProgress(points) * 100)}%"></i>
          </div>
          <p class="companion-next">${next.at - points} pts to ${next.name}</p>`
          : `<p class="companion-next">Fully grown. Nothing left to prove.</p>`}
      </div>`;
  };
  paintCompanion();

  // If a quest is running, say so here too. Someone who backgrounded the
  // app and came back to the home screen should not have to remember.
  activeSessionBanner(root.querySelector("#session-slot"));

  const load = async () => {
    const data = await api.todaysTasks();
    const pct = Math.min(100, Math.round((data.points_today / data.daily_cap) * 100));

    list.replaceChildren(
      h(`<div class="panel panel-dark" style="margin-bottom:var(--s3)">
           <div class="row-between">
             <strong style="font-size:14px">Today's small good</strong>
             <span class="tiny">${data.points_today} / ${data.daily_cap} pts</span>
           </div>
           <div class="bar" style="margin-top:10px"><i style="width:${pct}%"></i></div>
         </div>`),
      ...data.deeds.map((d) => taskCard(d, data, load, { paintCompanion, companionSlot })),
    );
  };

  await load();
}

function taskCard(deed, data, reload, companion) {
  const card = h(`
    <div class="card ${deed.done ? "task-done" : "tappable"}">
      <div class="row">
        <div class="thumb" style="width:48px;height:48px;font-size:22px">${deed.icon}</div>
        <div class="grow">
          <p style="font-weight:700;font-size:14.5px;line-height:1.35">${esc(deed.text)}</p>
          <p class="tiny" style="margin-top:3px">+${deed.points} pts</p>
        </div>
        ${deed.done
          ? `<span class="row" style="gap:6px">
               <button class="delete-btn" data-undo>Undo</button>
               <span class="status-pill status-open">✓ Done</span>
             </span>`
          : `<button class="btn btn-primary btn-sm" data-do>I did it</button>`}
      </div>
    </div>`);

  const undo = card.querySelector("[data-undo]");
  if (undo) {
    undo.onclick = async () => {
      try {
        await api.undoTask(deed.id);
        toast(`Undone — ${deed.points} points returned`);
        reload();
        companion.paintCompanion();
      } catch (err) {
        toast(err?.message || "Couldn't undo that", true);
      }
    };
  }

  const btn = card.querySelector("[data-do]");
  if (btn) {
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = "…";
      try {
        const res = await api.completeTask(deed.id);
        // Keep the header's tier and streak in step without a reload.
        if (state.user) {
          setSession(state.token, {
            ...state.user,
            tier: res.user_tier,
            tier_points: res.user_tier_points,
            current_streak: res.current_streak,
          });
        }
        // Did that tip it over an evolution threshold?
        const before = stageFor(res.user_tier_points - res.points).key;
        const after = stageFor(res.user_tier_points).key;
        const evolved = before !== after;

        companion.paintCompanion();
        celebrate(companion.companionSlot.querySelector(".companion"), { evolved });

        toast(
          evolved
            ? `${stageFor(res.user_tier_points).name}! Your companion evolved.`
            : res.capped
              ? `Logged. You've hit today's ${res.daily_cap}-point cap — it still counts.`
              : `Nice one. +${res.points} pts`,
        );
        reload();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Couldn't log that", true);
        btn.disabled = false;
        btn.textContent = "I did it";
      }
    };
  }
  return card;
}

function quoteCard() {
  const q = quoteOfTheDay();
  return `
    <div class="pad" style="padding-top:0;padding-bottom:var(--s4)">
      <blockquote class="quote-card">
        <p>${esc(q.text)}</p>
        <cite>${esc(q.who)}${q.src ? `, <span>${esc(q.src)}</span>` : ""}</cite>
      </blockquote>
    </div>`;
}
