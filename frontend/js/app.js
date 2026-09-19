/* App shell: route table, bottom nav, demo-data banner. */

import { state } from "./api.js";
import { defineRoute, dispatch, go, setNavigateHook } from "./router.js";
import { renderWelcome, renderSignup, renderLogin } from "./screens/auth.js";
import { renderMap, teardownMap } from "./screens/map.js";
import { renderQuest, renderResult, renderSubmit } from "./screens/submit.js";
import { renderActive, teardownActive } from "./screens/active.js";
import { renderToday } from "./screens/today.js";
import { renderFeed } from "./screens/feed.js";
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
defineRoute("map",         { render: renderMap,        nav: true,  auth: true });
defineRoute("quests",      { render: renderQuests,     nav: true,  auth: true });
defineRoute("quest",       { render: renderQuest,      auth: true });
defineRoute("submit",      { render: renderSubmit,     auth: true });
defineRoute("result",      { render: renderResult,     auth: true });
defineRoute("active",      { render: renderActive,     auth: true });
defineRoute("feed",        { render: renderFeed,       nav: true,  auth: true });
defineRoute("community",   { render: renderCommunity,  nav: true,  auth: true });
defineRoute("report",      { render: renderReportForm, auth: true });
defineRoute("proof",       { render: renderProof,      auth: true });
defineRoute("leaderboard", { render: renderLeaderboard, nav: true, auth: true });
defineRoute("profile",     { render: renderProfile,    nav: true,  auth: true });

const NAV = [
  { route: "today",       icon: "☀", label: "Today" },
  { route: "map",         icon: "⌖", label: "Map" },
  { route: "feed",        icon: "✷", label: "Activity" },
  { route: "community",   icon: "♥", label: "Community" },
  { route: "profile",     icon: "●", label: "Profile" },
];

function buildNav() {
  const nav = document.getElementById("nav");
  nav.innerHTML = NAV.map((n) =>
    `<button data-route="${n.route}"><span class="ico">${n.icon}</span>${n.label}</button>`).join("");
  nav.querySelectorAll("button").forEach((b) => {
    b.onclick = () => { if (b.dataset.route !== "map") teardownMap(); teardownActive(); go(b.dataset.route); };
  });
}

setNavigateHook((name, route) => {
  // The active-quest screen runs a heartbeat loop; leaving it must stop that.
  if (name !== "active") teardownActive();

  const nav = document.getElementById("nav");
  nav.hidden = !route.nav;
  nav.querySelectorAll("button").forEach((b) =>
    b.toggleAttribute("aria-current", b.dataset.route === name));

  // Surface placeholder mode so stub data is never mistaken for a live backend.
  document.getElementById("mockbanner").hidden = !state.usingMocks;
});

buildNav();
dispatch();

// Weekly recap, once per ISO week, after the first screen has painted so it
// never delays the app's first render. Signed-out users never see it.
if (state.token) {
  setTimeout(() => { maybeShowRecap(); }, 1200);
  startLiveActivity();
}
