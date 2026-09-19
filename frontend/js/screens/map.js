/* Map view: quest pins (green) and open community reports (coral). */

import { api, getLocation, state } from "../api.js";
import { DEFAULT_RADIUS_KM } from "../config.js";
import { distanceLabel, esc, h, icon, statusbar, toast } from "../ui.js";
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

  const [quests, reports] = await Promise.all([
    api.quests(loc.lat, loc.lng, DEFAULT_RADIUS_KM),
    api.reports(loc.lat, loc.lng, DEFAULT_RADIUS_KM, "open"),
  ]);

  drawPins(quests, reports);
  renderHighlight(root.querySelector("#map-highlight"), quests);
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
    L.marker([q.lat, q.lng], {
      icon: L.divIcon({ className: "", html: `<div class="map-pin">${label}</div>`, iconSize: null }),
    })
      .addTo(mapInstance)
      .on("click", () => go("quest", { quest: q }));
  }

  for (const r of reports.slice(0, 10)) {
    const text = esc((r.description || "Community need").slice(0, 26));
    L.marker([r.lat, r.lng], {
      icon: L.divIcon({
        className: "",
        html: `<div class="map-pin report">❤ ${text} · +${r.estimated_points ?? 20}</div>`,
        iconSize: null,
      }),
    })
      .addTo(mapInstance)
      .on("click", () => go("community"));
  }
}

function renderHighlight(container, quests) {
  if (!container) return;
  const q = quests[0];
  if (!q) {
    container.innerHTML = `
      <div class="card center">
        <p class="muted">No quests found nearby.</p>
        <p class="tiny" style="margin-top:6px">Try again from a different location.</p>
      </div>`;
    return;
  }
  const card = h(`
    <div class="card tappable" style="cursor:pointer">
      <div class="row">
        <div class="thumb">${icon(q.category)}</div>
        <div class="grow">
          ${q.verified ? `<div class="verified">✓ Verified organization</div>` : ""}
          <h3 class="truncate">${esc(q.org_name)}</h3>
          <p class="tiny truncate">${esc(q.address)} · ${distanceLabel(q.distance_km)}</p>
        </div>
        <div style="text-align:right">
          <div style="font-weight:800;color:var(--green-press)">+${q.estimated_points ?? 0}</div>
          <div style="font-size:20px;color:var(--ink-faint);line-height:1">›</div>
        </div>
      </div>
    </div>`);
  card.onclick = () => go("quest", { quest: q });
  container.replaceChildren(card);
}

export function teardownMap() {
  if (mapInstance) { mapInstance.remove(); mapInstance = null; }
}
