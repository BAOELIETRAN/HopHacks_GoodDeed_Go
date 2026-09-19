/* Hash router with a per-route params slot.

   Params (a selected quest, a score result) are held in memory rather than
   serialised into the URL -- a score result contains a base64 photo and
   would blow past URL length limits. A refresh therefore lands on the
   route's default state, which is the right behaviour for all of them. */

import { state } from "./api.js";

const routes = new Map();
let pendingParams = {};
let current = null;
let onNavigate = () => {};

export function defineRoute(name, { render, nav = false, auth = false }) {
  routes.set(name, { render, nav, auth });
}

export function setNavigateHook(fn) { onNavigate = fn; }

export function go(name, params = {}) {
  pendingParams = params;
  if (location.hash === "#" + name) dispatch();
  else location.hash = name;
}

export const currentRoute = () => current;

export async function dispatch() {
  const name = location.hash.replace(/^#/, "") || (state.token ? "map" : "welcome");
  const route = routes.get(name) || routes.get("map");

  // Guard authenticated routes. Placeholder data still renders without a
  // backend, but a real session is required before we pretend to be signed in.
  if (route.auth && !state.token) {
    pendingParams = {};
    if (location.hash !== "#welcome") { location.hash = "welcome"; return; }
    return dispatchTo("welcome", routes.get("welcome"));
  }
  return dispatchTo(name, route);
}

async function dispatchTo(name, route) {
  const params = pendingParams;
  pendingParams = {};
  current = name;

  const root = document.getElementById("screen");
  root.className = "screen" + (route.nav ? "" : " no-nav");
  root.scrollTop = 0;
  root.innerHTML = "";

  try {
    await route.render(root, params);
  } catch (err) {
    // An expired or revoked token should land on sign-in, not an error
    // screen. api.js has already cleared the session by this point.
    if (err?.status === 401) {
      current = null;
      location.hash = "welcome";
      return;
    }
    console.error("[gdg] screen failed:", err);
    root.innerHTML = `<div class="empty"><div class="big">😵</div>
      <h3>Something broke on this screen</h3>
      <p class="muted" style="margin-top:8px">${String(err.message || err)}</p></div>`;
  }
  onNavigate(name, route);
}

window.addEventListener("hashchange", dispatch);
