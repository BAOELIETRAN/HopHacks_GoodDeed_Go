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

// Absolute last resort, used only when the device gives us nothing AND we have
// never seen a real fix from this browser (see location.js for the full order).
// Reaching this point is always surfaced in the UI as a guess -- silently
// resolving it was how the app came to describe Baltimore to everyone,
// wherever they actually were.
export const LAST_RESORT_LOCATION = { lat: 39.3299, lng: -76.6205, label: "Baltimore, Maryland" };

// One search radius everywhere: 25 miles, which is a whole county and the
// towns either side of it. It was a user setting, but the control was a
// decision nobody wanted to make before seeing a single result.
//
// It was 10 miles, chosen for "within walking distance". That is the right
// framing for a dense city centre and the wrong one everywhere else: in a
// suburb it returned a thin list and an almost empty map, which reads as a
// broken app rather than a quiet neighbourhood. Results are sorted by
// distance and the map frames whatever it finds, so a wider net costs
// nothing -- the closest thing is still the first thing you see.
//
// The backend takes km and caps at 50, so this is near the ceiling: 25mi is
// 40.2km. Raising it further needs that cap lifted too.
export const SEARCH_RADIUS_MI = 25;
const MI_TO_KM = 1.609344;

export const radiusKm = () => Math.min(50, SEARCH_RADIUS_MI * MI_TO_KM);

// Set true to force placeholder data even when the backend is reachable.
export const FORCE_MOCKS = localStorage.getItem("gdg_force_mocks") === "1";
