/* Quest list: daily / monthly cards from nearby opportunities. */

import { api, getLocation } from "../api.js";
import { DEFAULT_RADIUS_KM } from "../config.js";
import { distanceLabel, empty, esc, h, icon, prettyCategory, spinner, statusbar } from "../ui.js";
import { go } from "../router.js";

let filter = "all";

export async function renderQuests(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="pad" style="padding-bottom:8px">
      <h2>Quests near you</h2>
      <p class="muted">Daily drop-ins and monthly commitments.</p>
    </div>
    <div class="pad" style="padding-top:0;padding-bottom:8px">
      <div class="pills" id="filters">
        <button data-f="all" aria-selected="${filter === "all"}">All</button>
        <button data-f="daily" aria-selected="${filter === "daily"}">Daily</button>
        <button data-f="monthly" aria-selected="${filter === "monthly"}">Monthly</button>
      </div>
    </div>
    <div class="pad" id="list" style="padding-top:8px">${spinner()}</div>`;

  const list = root.querySelector("#list");
  const loc = await getLocation();
  const quests = await api.quests(loc.lat, loc.lng, DEFAULT_RADIUS_KM);

  const draw = () => {
    const shown = filter === "all" ? quests : quests.filter((q) => q.quest_type === filter);
    if (!shown.length) {
      list.innerHTML = empty("🔍", "No quests here yet", "Try widening your search or check back later.");
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
    <div class="card" style="cursor:pointer">
      <div class="row">
        <div class="thumb">${icon(q.category)}</div>
        <div class="grow">
          <div class="row" style="gap:6px;margin-bottom:2px">
            <span class="chip ${q.quest_type === "monthly" ? "chip-blue" : ""}" style="font-size:11px;padding:3px 10px">
              ${q.quest_type === "monthly" ? "Monthly" : "Daily"}
            </span>
            ${q.verified ? `<span class="verified">✓ Verified</span>` : ""}
          </div>
          <h3 class="truncate">${esc(q.org_name)}</h3>
          <p class="tiny truncate">${esc(prettyCategory(q.category))} · ${distanceLabel(q.distance_km)}</p>
        </div>
        <div style="text-align:right">
          <div style="font-weight:800;color:var(--green-press)">+${q.estimated_points ?? 0}</div>
          <div class="tiny">pts</div>
        </div>
      </div>
    </div>`);
  card.onclick = () => go("quest", { quest: q });
  return card;
}
