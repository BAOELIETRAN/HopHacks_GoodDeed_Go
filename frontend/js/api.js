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
    // FastAPI puts the useful message in `detail`; 422 nests it in a list.
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d) => d.msg).join(", ");
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

  // --- submissions ---------------------------------------------------------
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
