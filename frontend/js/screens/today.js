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
import { emptyState, esc, h, ico, microIcon, skeleton, toast } from "../ui.js";
import { go } from "../router.js";
import { quoteOfTheDay } from "../quotes.js";
import { activeSessionBanner } from "../ui.js";
import { celebrate, companionSvg, nextStage, stageFor, stageProgress } from "../companion.js";

export async function renderToday(root) {
  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Today</p>
        <h2>Small things count</h2>
        <p class="muted">Quick, everyday good. No photo and no check-in: do it, then tap.</p>
      </div>
    </div>
    <div class="pad" id="companion-slot"></div>
    <div id="session-slot"></div>
    <div class="pad" style="padding-top:0;padding-bottom:0">${quoteCard()}</div>
    <div class="pad" id="tasks" style="padding-top:var(--s6)">${skeleton(3)}</div>
    <div class="pad" style="padding-top:0">
      <div class="section-title" style="margin-top:0"><h3>Something bigger?</h3></div>
      <button class="btn btn-ghost" id="log-deed">Log a donation, fundraiser or other deed</button>
      <p class="tiny" style="margin-top:10px">
        Money, goods, fundraising, remote help, blood, advocacy.
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
        ${companionSvg(points, { mood, size: 116 })}
        <div class="companion-body">
          <div class="companion-name">${esc(stage.name)}
            <span class="chip chip-quiet">${points} pts</span>
          </div>
          <p class="companion-blurb">${esc(stage.blurb)}</p>
          ${next ? `
            <div class="bar"><i style="width:${Math.round(stageProgress(points) * 100)}%"></i></div>
            <p class="companion-next">${next.at - points} pts to ${esc(next.name)}</p>`
            : `<p class="companion-next">Fully grown. Nothing left to prove.</p>`}
        </div>
      </div>`;
  };
  paintCompanion();

  // If a quest is running, say so here too. Someone who backgrounded the
  // app and came back to the home screen should not have to remember.
  activeSessionBanner(root.querySelector("#session-slot"));

  const load = async () => {
    const data = await api.todaysTasks();
    const pct = Math.min(100, Math.round((data.points_today / data.daily_cap) * 100));

    const head = h(`
      <div>
        <div class="section-title" style="margin-top:0">
          <h3>Today's small good</h3>
          <span class="tiny">${data.points_today} of ${data.daily_cap} pts</span>
        </div>
        <div class="bar" style="margin-bottom:var(--s4)"><i style="width:${pct}%"></i></div>
      </div>`);

    if (!data.deeds.length) {
      list.replaceChildren(head, emptyState({
        icon: "sprout", title: "Nothing on the list right now",
        body: "New everyday ideas show up each morning. Check back tomorrow.",
      }));
      return;
    }
    const rows = h(`<div class="card task-list"></div>`);
    rows.append(...data.deeds.map((d) => taskCard(d, data, load, { paintCompanion, companionSlot })));
    list.replaceChildren(head, rows);
  };

  await load();
}

function taskCard(deed, data, reload, companion) {
  const card = h(`
    <div class="task-row ${deed.done ? "task-done" : ""}">
      <div class="thumb">${deed.done ? ico("check", { size: 22 }) : microIcon(deed.id, { size: 22 })}</div>
      <div class="grow">
        <p class="task-text">${esc(deed.text)}</p>
        <p class="tiny">+${deed.points} pts</p>
      </div>
      ${deed.done
        ? `<span class="row" style="gap:4px">
             <button class="delete-btn" data-undo>Undo</button>
             <span class="task-done-mark">${ico("check", { size: 16 })} Done</span>
           </span>`
        : `<button class="btn btn-primary btn-sm" data-do>I did it</button>`}
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
      btn.textContent = "Saving…";
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
            ? `Your companion just grew into a ${stageFor(res.user_tier_points).name}.`
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
    <blockquote class="quote-card">
      <p>${esc(q.text)}</p>
      <cite>${esc(q.who)}${q.src ? `, <span>${esc(q.src)}</span>` : ""}</cite>
    </blockquote>`;
}
