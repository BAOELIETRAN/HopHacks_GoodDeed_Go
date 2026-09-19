/* Runtime config. No build step, so everything is resolved in the browser. */

function resolveApiBase() {
  // Explicit override always wins, for pointing a laptop at a phone or a
  // deployed API:  localStorage.setItem("gdg_api_base", "https://...")
  const override = localStorage.getItem("gdg_api_base");
  if (override) return override;

  // Local dev: the frontend is usually on its own static server with the
  // backend on :8000.
  const devPorts = new Set(["5173", "3000", "8080"]);
  if (devPorts.has(location.port)) {
    return `${location.protocol}//${location.hostname}:8000`;
  }

  // Production: the backend serves this page, so the API is same-origin.
  // Returning the origin rather than "" keeps every request an absolute URL
  // -- relative URLs work in a browser but silently fail anywhere else,
  // which made this path untestable outside one.
  return location.origin;
}

export const API_BASE = resolveApiBase();

// Baltimore / Johns Hopkins, used when geolocation is denied or unavailable.
export const FALLBACK_LOCATION = { lat: 39.3299, lng: -76.6205 };

// Search radius, in miles, chosen by the user rather than fixed. A city
// centre is dense at 1 mile; a suburb can be empty at 5. The backend takes
// km and caps at 50 (~31 miles).
export const RADIUS_CHOICES_MI = [1, 3, 5, 10, 25];
export const DEFAULT_RADIUS_MI = 10;
const MI_TO_KM = 1.609344;

export function getRadiusMiles() {
  const saved = parseFloat(localStorage.getItem("gdg_radius_mi") || "");
  return RADIUS_CHOICES_MI.includes(saved) ? saved : DEFAULT_RADIUS_MI;
}

export function setRadiusMiles(miles) {
  localStorage.setItem("gdg_radius_mi", String(miles));
}

export const radiusKm = () => Math.min(50, getRadiusMiles() * MI_TO_KM);

// Set true to force placeholder data even when the backend is reachable.
export const FORCE_MOCKS = localStorage.getItem("gdg_force_mocks") === "1";
