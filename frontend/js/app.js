/* App shell: route table, bottom nav, demo-data banner. */

import { state } from "./api.js";
import { API_BASE } from "./config.js";
import { ico, logoMark } from "./ui.js";
import { defineRoute, dispatch, go, setNavigateHook } from "./router.js";
import { renderWelcome, renderSignup, renderLogin } from "./screens/auth.js";
import { renderMap, teardownMap } from "./screens/map.js";
import { renderQuest, renderResult, renderSubmit } from "./screens/submit.js";
import { renderActive, teardownActive } from "./screens/active.js";
import { renderToday } from "./screens/today.js";
import { renderFeed } from "./screens/feed.js";
import { renderMarket } from "./screens/market.js";
import { maybeShowRecap } from "./recap.js";
import { startLiveActivity, stopLiveActivity } from "./live.js";
import { renderQuests } from "./screens/quests.js";
import { renderLeaderboard } from "./screens/leaderboard.js";
import { renderCommunity, renderProof, renderReportForm } from "./screens/community.js";
import { renderProfile } from "./screens/profile.js";

defineRoute("welcome",     { render: renderWelcome });
defineRoute("signup",      { render: renderSignup });
defineRoute("login",       { render: renderLogin });
defineRoute("today",       { render: renderToday,      nav: true,  auth: true });
defineRoute("map",         { render: renderMap,        nav: true,  auth: true, wide: true });
defineRoute("quests",      { render: renderQuests,     nav: true,  auth: true, wide: true });
defineRoute("quest",       { render: renderQuest,      auth: true });
defineRoute("submit",      { render: renderSubmit,     auth: true });
defineRoute("result",      { render: renderResult,     auth: true });
defineRoute("active",      { render: renderActive,     auth: true });
defineRoute("feed",        { render: renderFeed,       nav: true,  auth: true });
defineRoute("market",      { render: renderMarket,     nav: true,  auth: true });
defineRoute("community",   { render: renderCommunity,  nav: true,  auth: true, wide: true });
defineRoute("report",      { render: renderReportForm, auth: true });
defineRoute("proof",       { render: renderProof,      auth: true });
defineRoute("leaderboard", { render: renderLeaderboard, nav: true, auth: true });
defineRoute("profile",     { render: renderProfile,    nav: true,  auth: true });

const NAV = [
  { route: "today",       icon: "today",     label: "Today" },
  { route: "map",         icon: "map",       label: "Map" },
  { route: "feed",        icon: "activity",  label: "Activity" },
  { route: "community",   icon: "community", label: "Community" },
  { route: "market",      icon: "boost",     label: "Boost" },
  { route: "profile",     icon: "profile",   label: "Profile" },
];

function buildNav() {
  const nav = document.getElementById("nav");
  // The wordmark only shows in the desktop sidebar; on a phone the bar is just the tabs.
  nav.innerHTML = `<div class="brand"><span class="wordmark">${logoMark(30)}GoodDeed Go</span></div>` +
    NAV.map((n) =>
      `<button data-route="${n.route}">${ico(n.icon, { size: 22 })}<span>${n.label}</span></button>`).join("");
  nav.querySelectorAll("button").forEach((b) => {
    b.onclick = () => { if (b.dataset.route !== "map") teardownMap(); teardownActive(); go(b.dataset.route); };
  });
}

setNavigateHook((name, route) => {
  // The active-quest screen runs a heartbeat loop; leaving it must stop that.
  if (name !== "active") teardownActive();

  // Chrome elements are optional: a screen must still render if the shell
  // around it is missing, rather than taking the whole app down.
  const nav = document.getElementById("nav");
  // Signed-out screens (welcome, sign in) get the whole width: no sidebar on desktop.
  document.getElementById("app")?.classList.toggle("bare", !route.auth);
  if (nav) {
    nav.hidden = !route.nav;
    nav.querySelectorAll("button").forEach((b) => {
      if (b.dataset.route === name) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
  }

  refreshBanner();
});

/** Surface placeholder mode so stub data is never mistaken for a live backend.
 *  Two different situations: the backend is unreachable (screens show canned
 *  data), or it is reachable but its AI isn't configured (points come from a
 *  stub). The stub's text reads like an ordinary verdict, so this is where that
 *  gets said. */
function refreshBanner() {
  const banner = document.getElementById("mockbanner");
  if (!banner) return;
  if (state.usingMocks) banner.textContent = "Showing sample data — can't reach the server";
  else if (state.demoScoring) {
    banner.textContent = "Demo scoring — the AI reviewer isn't connected, so points are placeholders";
  }
  banner.hidden = !(state.usingMocks || state.demoScoring);
}

fetch(`${API_BASE}/health`)
  .then((r) => (r.ok ? r.json() : null))
  .then((body) => {
    if (body?.agent?.llm_provider === "mock") {
      state.demoScoring = true;
      refreshBanner();
    }
  })
  .catch(() => { /* unreachable backend is already handled by the mock fallback */ });

buildNav();
dispatch();

// Weekly recap, once per ISO week, after the first screen has painted so it
// never delays the app's first render. Signed-out users never see it.
if (state.token) {
  setTimeout(() => { maybeShowRecap(); }, 1200);
  startLiveActivity();
}
