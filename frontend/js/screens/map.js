/* Map view: quest pins (green) and open community reports (coral). */

import { api, getLocation, state } from "../api.js";
import { radiusKm } from "../config.js";
import {
  directionsUrl, distanceLabel, esc, h, icon, radiusPicker, statusbar, toast,
} from "../ui.js";
import { go } from "../router.js";

let mapInstance = null;

export async function renderMap(root) {
  const user = state.user || {};
  root.innerHTML = `
    ${statusbar()}
    <div class="hero">
      <div>
        <div class="eyebrow">Nearby good deeds</div>
        <h2>Ready${user.name ? ", " + esc(user.name.split(" ")[0]) : ""}?</h2>
      </div>
      <div class="stats">
        <span class="chip chip-flame">🔥 ${user.current_streak ?? 0}</span>
        <span class="chip chip-yellow">★ ${user.tier_points ?? 0}</span>
      </div>
    </div>
    <div class="pad" style="padding-top:0;padding-bottom:10px" id="radius-slot"></div>
    <div id="map"></div>
    <div class="map-legend">
      <span><span class="legend-dot" style="background:var(--green)"></span>Verified nonprofit</span>
      <span><span class="legend-dot" style="background:var(--coral)"></span>Community need</span>
    </div>
    <div class="pad" id="map-highlight" style="padding-top:12px"></div>`;

  const loc = await getLocation();
  if (loc.approximate) toast("Using a default location — allow location for real results");

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

  root.querySelector("#radius-slot").replaceChildren(
    radiusPicker(() => {
      // Rebuild the map so old pins from a wider search don't linger.
      initLeaflet(loc);
      load();
    }),
  );

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
    radius: 9, color: "#fff", weight: 3, fillColor: "#8b7ff0", fillOpacity: 1,
  }).addTo(mapInstance);
}

function drawPins(quests, reports) {
  if (!mapInstance || !window.L) return;

  for (const q of quests.slice(0, 12)) {
    const label = `${icon(q.category)} ${esc(q.org_name.split(/[-–|]/)[0].trim())} · +${q.estimated_points ?? ""}`;
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
           <a href="${directionsUrl(q.lat, q.lng)}" target="_blank" rel="noopener noreferrer">🧭 Directions</a>
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
        html: `<div class="map-pin report">❤ ${text} · +${r.estimated_points ?? 20}</div>`,
        iconSize: null,
      }),
    }).addTo(mapInstance);
    marker.bindPopup(
      `<div class="map-pop">
         <strong>${esc(r.description || "Community need")}</strong>
         <div class="tiny">Posted by ${esc(r.reported_by_name || "a neighbour")}</div>
         <div class="map-pop-actions">
           <a href="${directionsUrl(r.lat, r.lng)}" target="_blank" rel="noopener noreferrer">🧭 Directions</a>
           <button data-feed>Open feed</button>
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
    container.innerHTML = `
      <div class="card center" style="background:var(--glass-dark)">
        <p class="muted">No quests found nearby.</p>
        <p class="tiny" style="margin-top:6px">Try again from a different location.</p>
      </div>`;
    return;
  }
  const card = h(`
    <div class="card tappable" style="cursor:pointer;background:var(--glass-dark)">
      <div class="row">
        <div class="thumb">${icon(q.category)}</div>
        <div class="grow">
          ${q.verified ? `<div class="verified">✓ Verified organization</div>` : ""}
          <h3 class="truncate">${esc(q.org_name)}</h3>
          <p class="tiny truncate">${esc(q.address)} · ${distanceLabel(q.distance_km)}</p>
        </div>
        <div style="text-align:right">
          <div style="font-weight:800;color:var(--green)">+${q.estimated_points ?? 0}</div>
          <div class="tiny">pts</div>
        </div>
      </div>
      <div class="row-between" style="margin-top:12px;gap:10px">
        <a class="btn-directions" data-directions target="_blank" rel="noopener noreferrer">🧭 Directions</a>
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
