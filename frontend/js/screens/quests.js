/* Quest list: daily / monthly cards from nearby opportunities. */

import { api } from "../api.js";
import { getLocation } from "../location.js";
import { radiusKm } from "../config.js";
import {
  directionsUrl, distanceLabel, emptyState, esc, h, ico, icon, orgLink, prettyCategory,
  skeleton,
} from "../ui.js";
import { go } from "../router.js";

let filter = "all";

export async function renderQuests(root) {
  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Opportunities</p>
        <h2>Quests near you</h2>
        <p class="muted">Drop in for an afternoon, or sign up for the month.</p>
      </div>
    </div>
    <div class="pad" style="padding-bottom:var(--s2)">
      <div class="pills" id="filters">
        <button data-f="all" aria-selected="${filter === "all"}">All</button>
        <button data-f="daily" aria-selected="${filter === "daily"}">Daily</button>
        <button data-f="monthly" aria-selected="${filter === "monthly"}">Monthly</button>
      </div>
    </div>
    <div class="pad" style="padding-top:var(--s3)"><div id="list" class="grid-2">${skeleton(3)}</div></div>`;

  const list = root.querySelector("#list");
  const loc = await getLocation();
  const quests = await api.quests(loc.lat, loc.lng, radiusKm());

  const draw = () => {
    const shown = filter === "all" ? quests : quests.filter((q) => q.quest_type === filter);
    if (!shown.length) {
      list.replaceChildren(emptyState({
        icon: "search",
        title: filter === "all" ? "No quests found near you" : `No ${filter} quests nearby`,
        body: filter === "all"
          ? "Nothing vetted within 25 miles yet. Check back soon, or look at what neighbours have posted."
          : "Try another filter to see the rest.",
        action: filter === "all" ? null : { label: "Show all quests", onClick: () => root.querySelector('#filters [data-f="all"]').click() },
      }));
      return;
    }
    list.replaceChildren(...shown.map(questCard));
  };

  root.querySelectorAll("#filters button").forEach((btn) => {
    btn.onclick = () => {
      filter = btn.dataset.f;
      root.querySelectorAll("#filters button").forEach((b) =>
        b.setAttribute("aria-selected", String(b.dataset.f === filter)));
      draw();
    };
  });

  draw();
}

function questCard(q) {
  const card = h(`
    <div class="card tappable">
      <div class="row" style="align-items:flex-start">
        <div class="thumb">${icon(q.category, { size: 24 })}</div>
        <div class="grow">
          <div class="meta-row" style="margin-bottom:6px">
            <span class="chip ${q.quest_type === "monthly" ? "chip-blue" : ""}">
              ${q.quest_type === "monthly" ? "Monthly" : "Daily"}
            </span>
            ${q.verified ? `<span class="verified">${ico("shield", { size: 14 })} Verified</span>` : ""}
          </div>
          <h3 class="truncate">${esc(q.org_name)}</h3>
          <p class="tiny truncate">${esc(prettyCategory(q.category))} · ${distanceLabel(q.distance_km)}</p>
          <p class="tiny truncate">${esc(q.address || "")}</p>
        </div>
        <div style="text-align:right">
          <div class="figure" style="font-size:24px;line-height:1">+${q.estimated_points ?? 0}</div>
          <div class="tiny">pts</div>
        </div>
      </div>
      <div class="row" style="margin-top:var(--s4);gap:8px">
        <a class="btn-directions" data-directions target="_blank" rel="noopener noreferrer" aria-label="Directions to ${esc(q.org_name)}">${ico("directions", { size: 16 })}</a>
        <a class="btn-directions" data-website target="_blank" rel="noopener noreferrer" aria-label="About ${esc(q.org_name)}">${ico("link", { size: 16 })}</a>
        <button class="btn btn-primary btn-sm grow" data-open>View quest</button>
      </div>
    </div>`);

  // The whole card navigates, so links must not also trigger that.
  const dirs = card.querySelector("[data-directions]");
  dirs.href = directionsUrl(q.lat, q.lng);
  dirs.title = "Directions";
  dirs.onclick = (e) => e.stopPropagation();

  const site = card.querySelector("[data-website]");
  site.href = orgLink(q);
  site.title = q.website ? "Their website" : "Look them up";
  site.onclick = (e) => e.stopPropagation();

  card.querySelector("[data-open]").onclick = (e) => {
    e.stopPropagation();
    go("quest", { quest: q });
  };
  card.onclick = () => go("quest", { quest: q });
  return card;
}
