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

export function defineRoute(name, { render, nav = false, auth = false, wide = false }) {
  routes.set(name, { render, nav, auth, wide });
}

export function setNavigateHook(fn) { onNavigate = fn; }

export function go(name, params = {}) {
  pendingParams = params;
  if (location.hash === "#" + name) dispatch();
  else location.hash = name;
}

export const currentRoute = () => current;

export async function dispatch() {
  const name = location.hash.replace(/^#/, "") || (state.token ? "today" : "welcome");
  const route = routes.get(name) || routes.get("today") || routes.get("welcome");

  // No route resolved at all. Happens if a hashchange fires before the
  // route table is built, or from a hand-typed URL. Doing nothing is
  // correct; throwing here took down whatever screen was already up.
  if (!route) return;

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
  root.className = "screen" + (route.nav ? "" : " no-nav") + (route.wide ? " wide" : "");
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
    const detail = String(err.message || err).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    root.innerHTML = `
      <div class="pad">
        <div class="empty-state">
          <h3>This screen didn't load</h3>
          <p>Something went wrong on our side. Your points and deeds are safe. Try again in a moment.</p>
          <button class="btn btn-ghost" data-retry>Try again</button>
          <details class="tiny" style="margin-top:var(--s3)"><summary>Details</summary>${detail}</details>
        </div>
      </div>`;
    root.querySelector("[data-retry]").onclick = () => dispatch();
  }
  onNavigate(name, route);
}

window.addEventListener("hashchange", dispatch);
