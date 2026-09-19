/* Thin fetch wrapper around the backend.

   Two things it guarantees for the rest of the app:
   1. Every call returns contract-shaped data, falling back to placeholder
      JSON when the backend is unreachable. Screens never branch on it.
   2. The bearer token is attached automatically and a 401 clears the session.

   `state.usingMocks` flips true the first time a fallback fires, which drives
   the "demo data" banner so nobody mistakes stub data for a working backend. */

import { API_BASE, FALLBACK_LOCATION, FORCE_MOCKS } from "./config.js";
import * as mock from "./mock.js";

export const state = {
  token: localStorage.getItem("gdg_token") || null,
  user: JSON.parse(localStorage.getItem("gdg_user") || "null"),
  usingMocks: FORCE_MOCKS,
};

export function setSession(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem("gdg_token", token);
  localStorage.setItem("gdg_user", JSON.stringify(user));
}

export function clearSession() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("gdg_token");
  localStorage.removeItem("gdg_user");
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;

  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    clearSession();
    throw new ApiError("Your session expired. Please sign in again.", 401);
  }
  if (!res.ok) {
    // FastAPI's `detail` is a string for raised HTTPExceptions, a list of
    // field errors for schema violations, and an object when a handler
    // raises one. Missing the object case threw away the server's actual
    // explanation and showed a bare status code instead.
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      const d = data?.detail;
      if (typeof d === "string" && d.trim()) {
        detail = d;
      } else if (Array.isArray(d) && d.length) {
        detail = d
          .map((e) => {
            const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : null;
            return field ? `${field}: ${e.msg}` : e.msg;
          })
          .join(", ");
      } else if (d && typeof d === "object") {
        detail = d.message || d.reason || JSON.stringify(d);
      } else if (typeof data?.message === "string") {
        detail = data.message;
      }
    } catch { /* non-JSON error body */ }
    throw new ApiError(detail, res.status);
  }
  return res.status === 204 ? null : res.json();
}

/* Run a real request, falling back to placeholder data if the backend is
   unreachable. Only network-level failures fall back -- a 400 or 409 is a
   real answer and must reach the caller so the UI can show it. */
async function withFallback(fn, fallbackValue) {
  if (FORCE_MOCKS) {
    state.usingMocks = true;
    return fallbackValue;
  }
  try {
    return await fn();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    state.usingMocks = true;
    console.warn("[gdg] backend unreachable, using placeholder data:", err.message);
    return fallbackValue;
  }
}

const qs = (params) => new URLSearchParams(params).toString();

// --- auth -----------------------------------------------------------------
export const api = {
  authConfig: () => request("/auth/config", { auth: false }),
  google: (credential) => request("/auth/google", { method: "POST", body: { credential }, auth: false }),
  signup: (payload) => request("/auth/signup", { method: "POST", body: payload, auth: false }),
  login: (payload) => request("/auth/login", { method: "POST", body: payload, auth: false }),
  me: () => withFallback(() => request("/auth/me"), mock.MOCK_USER),

  // --- quests / opportunities ---------------------------------------------
  quests: (lat, lng, radius) =>
    withFallback(() => request(`/quests?${qs({ lat, lng, radius })}`), mock.MOCK_QUESTS),

  // --- everyday deeds (tap to complete) -----------------------------------
  todaysTasks: () =>
    withFallback(() => request("/tasks/today"), {
      day: new Date().toISOString().slice(0, 10), points_today: 0, daily_cap: 20,
      deeds: [
        { id: "three_pieces", text: "Pick up three pieces of litter that aren't yours", icon: "🧹", points: 4, theme: "place", done: false },
        { id: "compliment", text: "Give someone a genuine compliment", icon: "💬", points: 3, theme: "people", done: false },
        { id: "hold_door", text: "Hold a door for someone behind you", icon: "🚪", points: 2, theme: "people", done: false },
      ],
    }),
  completeTask: (id, note) =>
    request(`/tasks/${id}/complete`, { method: "POST", body: { note: note || null } }),

  // --- presence-verified sessions -----------------------------------------
  activeCheckin: () => request("/checkins/active"),
  startCheckin: (payload) => request("/checkins", { method: "POST", body: payload }),
  heartbeat: (id, lat, lng) =>
    request(`/checkins/${id}/heartbeat`, { method: "POST", body: { lat, lng } }),
  stopCheckin: (id) => request(`/checkins/${id}/stop`, { method: "POST" }),

  // --- submissions ---------------------------------------------------------
  deedTypes: () =>
    withFallback(() => request("/deed-types"), [
      { key: "volunteer", label: "Volunteered in person", icon: "🙌", blurb: "A shift at an organization",
        evidence: "A photo of you doing the work", photo_required: true, time_required: true,
        location_required: true, base_points: 30, max_points: 100 },
    ]),
  submit: (payload) => request("/submissions", { method: "POST", body: payload }),

  // --- leaderboard ---------------------------------------------------------
  leaderboard: (scope, period) =>
    withFallback(() => request(`/leaderboard?${qs({ scope, period })}`), mock.MOCK_LEADERBOARD),

  // --- community reports ----------------------------------------------------
  reports: (lat, lng, radius, status) =>
    withFallback(
      () => request(`/reports?${qs(status ? { lat, lng, radius, status } : { lat, lng, radius })}`),
      status ? mock.MOCK_REPORTS.filter((r) => r.status === status) : mock.MOCK_REPORTS,
    ),
  report: (id) => request(`/reports/${id}`),
  createReport: (payload) => request("/reports", { method: "POST", body: payload }),
  claimReport: (id) => request(`/reports/${id}/claim`, { method: "POST" }),
  submitProof: (id, payload) => request(`/reports/${id}/proof`, { method: "POST", body: payload }),
  completeReport: (id) => request(`/reports/${id}/complete`, { method: "POST" }),

  // --- friends ---------------------------------------------------------------
  invite: () => request("/friends/invite", { method: "POST" }),
  join: (invite_code) => request("/friends/join", { method: "POST", body: { invite_code } }),
};

/* Browser geolocation with a graceful fallback -- a denied prompt must not
   leave the map empty during a demo. */
export function getLocation() {
  return new Promise((resolve) => {
    const fallback = () => resolve({ ...FALLBACK_LOCATION, approximate: true });
    if (!navigator.geolocation) return fallback();
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, approximate: false }),
      fallback,
      { timeout: 6000, maximumAge: 300000 },
    );
  });
}
