/* Map view: quest pins (green) and open community reports (coral). */

import { api, getLocation, state } from "../api.js";
import { radiusKm } from "../config.js";
import {
  directionsUrl, distanceLabel, emptyState, esc, h, ico, icon, skeleton, toast,
} from "../ui.js";
import { go } from "../router.js";

let mapInstance = null;

export async function renderMap(root) {
  const user = state.user || {};
  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Nearby</p>
        <h2>${user.name ? `Ready, ${esc(user.name.split(" ")[0])}?` : "What's around you"}</h2>
      </div>
      <div class="head-actions">
        <span class="chip chip-flame" title="Day streak">${ico("flame", { size: 15 })} ${user.current_streak ?? 0}</span>
        <span class="chip chip-yellow" title="Tier points">${user.tier_points ?? 0} pts</span>
      </div>
    </div>
    <div style="height:var(--s3)"></div>
    <div id="map" role="application" aria-label="Map of nearby quests and community jobs"></div>
    <div class="map-legend">
      <span><span class="legend-dot" style="background:var(--brand)"></span>Vetted nonprofit</span>
      <span><span class="legend-dot" style="background:var(--alert)"></span>Neighbour's job</span>
    </div>
    <div class="pad" id="map-highlight">${skeleton(1)}</div>
    <div class="pad" style="padding-top:0">
      <button class="btn btn-ghost" id="all-quests">See all nearby quests ${ico("arrow", { size: 18 })}</button>
    </div>`;

  root.querySelector("#all-quests").onclick = () => go("quests");

  const loc = await getLocation();
  if (loc.approximate) toast("Showing a default location. Allow location access to see what's really near you.");

  // Leaflet needs a laid-out container, so build the map after paint.
  requestAnimationFrame(() => initLeaflet(loc));

  const load = async () => {
    const [quests, reports] = await Promise.all([
      api.quests(loc.lat, loc.lng, radiusKm()),
      api.reports(loc.lat, loc.lng, radiusKm(), "open"),
    ]);
    drawPins(quests, reports);
    renderHighlight(root.querySelector("#map-highlight"), quests);
  };


  await load();
}

function initLeaflet(loc) {
  const el = document.getElementById("map");
  if (!el || !window.L) return;
  if (mapInstance) { mapInstance.remove(); mapInstance = null; }

  mapInstance = L.map(el, { zoomControl: false }).setView([loc.lat, loc.lng], 14);

  // OpenStreetMap's standard tiles: genuinely keyless. Carto, Stadia and
  // Mapbox all now require an API key and watermark or block you without
  // one. Attribution is required by OSM's tile usage policy, so the
  // attribution control stays on -- it is styled small in styles.css.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(mapInstance);

  L.circleMarker([loc.lat, loc.lng], {
    radius: 8, color: "#fdfbf5", weight: 3, fillColor: "#1b2a22", fillOpacity: 1,
  }).addTo(mapInstance);
}

function drawPins(quests, reports) {
  if (!mapInstance || !window.L) return;

  for (const q of quests.slice(0, 12)) {
    const label = `${icon(q.category, { size: 15 })}<span>${esc(q.org_name.split(/[-–|]/)[0].trim())} · +${q.estimated_points ?? ""}</span>`;
    const marker = L.marker([q.lat, q.lng], {
      icon: L.divIcon({ className: "", html: `<div class="map-pin">${label}</div>`, iconSize: null }),
    }).addTo(mapInstance);

    // Tapping a pin opens a small sheet rather than jumping straight to the
    // detail screen: from the map, "how do I get there" is usually the
    // question, and losing your map position to find out is annoying.
    marker.bindPopup(
      `<div class="map-pop">
         <strong>${esc(q.org_name)}</strong>
         <div class="tiny">${esc(q.address || "")}</div>
         <div class="map-pop-actions">
           <a href="${directionsUrl(q.lat, q.lng)}" target="_blank" rel="noopener noreferrer">${ico("directions", { size: 15 })} Directions</a>
           <button data-quest>View quest</button>
         </div>
       </div>`,
      { closeButton: false, className: "glass-popup", offset: [0, -6] },
    );
    marker.on("popupopen", (e) => {
      e.popup.getElement()?.querySelector("[data-quest]")
        ?.addEventListener("click", () => go("quest", { quest: q }));
    });
  }

  for (const r of reports.slice(0, 10)) {
    const text = esc((r.description || "Community need").slice(0, 26));
    const marker = L.marker([r.lat, r.lng], {
      icon: L.divIcon({
        className: "",
        html: `<div class="map-pin report">${ico("pin", { size: 15 })}<span>${text} · +${r.estimated_points ?? 20}</span></div>`,
        iconSize: null,
      }),
    }).addTo(mapInstance);
    marker.bindPopup(
      `<div class="map-pop">
         <strong>${esc(r.description || "Community need")}</strong>
         <div class="tiny">Posted by ${esc(r.reported_by_name || "a neighbour")}</div>
         <div class="map-pop-actions">
           <a href="${directionsUrl(r.lat, r.lng)}" target="_blank" rel="noopener noreferrer">${ico("directions", { size: 15 })} Directions</a>
           <button data-feed>See the job</button>
         </div>
       </div>`,
      { closeButton: false, className: "glass-popup", offset: [0, -6] },
    );
    marker.on("popupopen", (e) => {
      e.popup.getElement()?.querySelector("[data-feed]")
        ?.addEventListener("click", () => go("community"));
    });
  }
}

function renderHighlight(container, quests) {
  if (!container) return;
  const q = quests[0];
  if (!q) {
    container.replaceChildren(emptyState({
      icon: "search",
      title: "No quests within walking distance",
      body: "Nothing vetted nearby yet. Neighbours may have posted jobs, though.",
      action: { label: "See community jobs", onClick: () => go("community") },
    }));
    return;
  }
  const card = h(`
    <div class="card tappable">
      <p class="eyebrow" style="margin-bottom:var(--s3)">Closest to you</p>
      <div class="row">
        <div class="thumb">${icon(q.category, { size: 24 })}</div>
        <div class="grow">
          <h3 class="truncate">${esc(q.org_name)}</h3>
          <p class="tiny truncate">${esc(q.address)}${q.address ? " · " : ""}${distanceLabel(q.distance_km)}</p>
          ${q.verified ? `<span class="verified">${ico("shield", { size: 14 })} Verified</span>` : ""}
        </div>
        <div style="text-align:right">
          <div class="figure" style="font-size:24px;line-height:1">+${q.estimated_points ?? 0}</div>
          <div class="tiny">pts</div>
        </div>
      </div>
      <div class="row-between" style="margin-top:var(--s4);gap:10px">
        <a class="btn-directions" data-directions target="_blank" rel="noopener noreferrer">${ico("directions", { size: 16 })} Directions</a>
        <button class="btn btn-primary btn-sm" data-open>View quest</button>
      </div>
    </div>`);

  const link = card.querySelector("[data-directions]");
  link.href = directionsUrl(q.lat, q.lng);
  link.onclick = (e) => e.stopPropagation();
  card.querySelector("[data-open]").onclick = (e) => { e.stopPropagation(); go("quest", { quest: q }); };
  card.onclick = () => go("quest", { quest: q });
  container.replaceChildren(card);
}

export function teardownMap() {
  if (mapInstance) { mapInstance.remove(); mapInstance = null; }
}
