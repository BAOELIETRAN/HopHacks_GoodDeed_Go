// Runtime config. Change API_BASE if the backend runs on another port/host.
export const API_BASE = localStorage.getItem("gdg_api_base") || "http://localhost:8000";

// Baltimore / Johns Hopkins, used when geolocation is denied or unavailable.
export const FALLBACK_LOCATION = { lat: 39.3299, lng: -76.6205 };
export const DEFAULT_RADIUS_KM = 8;

// Set true to force placeholder data even when the backend is reachable.
export const FORCE_MOCKS = localStorage.getItem("gdg_force_mocks") === "1";
