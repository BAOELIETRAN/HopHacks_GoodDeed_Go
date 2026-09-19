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

// One search radius everywhere: 10 miles. It was a user setting, but the
// control was a decision nobody wanted to make before seeing a single
// result, and 10 miles covers a dense city centre and a thin suburb alike.
// The backend takes km and caps at 50.
export const SEARCH_RADIUS_MI = 10;
const MI_TO_KM = 1.609344;

export const radiusKm = () => Math.min(50, SEARCH_RADIUS_MI * MI_TO_KM);

// Set true to force placeholder data even when the backend is reachable.
export const FORCE_MOCKS = localStorage.getItem("gdg_force_mocks") === "1";
