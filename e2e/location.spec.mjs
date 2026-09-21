/* Does the app look where the user actually is?

   Every one of these failed before the location rewrite. The app resolved a
   hardcoded Baltimore coordinate whenever the browser did not hand back a fix,
   said nothing about it, and then described Maryland to someone in Illinois.
   The insidious part is that it looked like a working app throughout, so these
   assert on two things at once: the coordinates the app asks the backend about,
   and whether it admits when it is guessing. */
import { expect, test } from "@playwright/test";

import { apiSignup } from "./helpers.mjs";

const CHICAGO = { latitude: 41.8781, longitude: -87.6298 };
const BALTIMORE_LAT = 39.3299; // the built-in default, in config.js

/** A signed-in phone. `at` grants location permission at a point; omitting it
 *  is the common real-world case -- a denied prompt, or a page on plain http. */
async function player(browser, request, { at = null } = {}) {
  const who = await apiSignup(request, "Loc Tester");
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    // A context with no geolocation permission is how a refused prompt looks.
    ...(at ? { permissions: ["geolocation"], geolocation: at } : { permissions: [] }),
  });
  await context.addInitScript(
    ([token, user]) => {
      localStorage.setItem("gdg_token", token);
      localStorage.setItem("gdg_user", JSON.stringify(user));
      // Suppress the weekly recap popup, which would sit over the banner.
      const d = new Date();
      const jan = new Date(d.getFullYear(), 0, 1);
      const week = Math.ceil(((d - jan) / 86400000 + jan.getDay() + 1) / 7);
      localStorage.setItem("gdg_recap_seen", `${d.getFullYear()}-W${week}`);
    },
    [who.token, who.user],
  );

  const page = await context.newPage();
  // Every coordinate the app asks the backend about, which is the only thing
  // that decides what the user is shown.
  const asked = [];
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.pathname === "/quests" || url.pathname === "/reports") {
      asked.push({
        path: url.pathname,
        lat: Number(url.searchParams.get("lat")),
        lng: Number(url.searchParams.get("lng")),
      });
    }
  });
  return { page, context, asked };
}

test("with location granted, the app searches where the user is", async ({ browser, request }) => {
  const { page, context, asked } = await player(browser, request, { at: CHICAGO });
  await page.goto("/#map");
  await expect.poll(() => asked.length, { message: "the map never asked the backend anything" })
    .toBeGreaterThan(0);

  for (const q of asked) {
    expect(q.lat, `${q.path} was asked about the wrong latitude`).toBeCloseTo(CHICAGO.latitude, 2);
    expect(q.lng, `${q.path} was asked about the wrong longitude`).toBeCloseTo(CHICAGO.longitude, 2);
  }
  // Nothing tells the user we are guessing, because we are not.
  await expect(page.locator("#locbanner")).toBeHidden();
  await context.close();
});

test("with location refused, the app says it is guessing rather than quietly showing Baltimore", async ({ browser, request }) => {
  const { page, context, asked } = await player(browser, request);
  await page.goto("/#map");

  const banner = page.locator("#locbanner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText(/don't know where you are/i);
  await expect(banner).toContainText(/Baltimore/i);
  await expect(banner.getByRole("button", { name: /set location/i })).toBeVisible();

  // A populated map is still better than an empty one -- as long as it is not
  // passed off as the user's own neighbourhood.
  await expect.poll(() => asked.length).toBeGreaterThan(0);
  expect(asked[0].lat).toBeCloseTo(BALTIMORE_LAT, 2);
  await context.close();
});

test("setting a location by hand moves the whole app there, and it sticks", async ({ browser, request }) => {
  const { page, context, asked } = await player(browser, request);

  // The geocoder is stubbed: this is about the app adopting a place, not about
  // OpenStreetMap being reachable from CI.
  await page.route("**/geo/search**", (route) => route.fulfill({
    json: [{ label: "Chicago, Cook County, Illinois, United States", lat: CHICAGO.latitude, lng: CHICAGO.longitude }],
  }));
  await page.route("**/geo/reverse**", (route) => route.fulfill({ json: { label: "Chicago, Illinois" } }));

  await page.goto("/#map");
  await page.locator("#locbanner").getByRole("button", { name: /set location/i }).click();
  await page.getByLabel("Search for a place").fill("Chicago");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.locator(".loc-result").first().click();

  await expect(page.locator("#locbanner")).toContainText(/near Chicago/i);
  await expect
    .poll(() => asked.filter((q) => Math.abs(q.lat - CHICAGO.latitude) < 0.01).length,
      { message: "nothing was re-fetched around the place the user set" })
    .toBeGreaterThan(0);

  // It survives a reload, so nobody re-types it on every screen.
  await page.reload();
  await expect(page.locator("#locbanner")).toContainText(/near Chicago/i);
  await context.close();
});

test("the quest list and community feed use the real location too, not just the map", async ({ browser, request }) => {
  const { page, context, asked } = await player(browser, request, { at: CHICAGO });

  await page.goto("/#quests");
  await expect.poll(() => asked.filter((q) => q.path === "/quests").length).toBeGreaterThan(0);
  await page.goto("/#community");
  await expect.poll(() => asked.filter((q) => q.path === "/reports").length).toBeGreaterThan(0);

  for (const q of asked) expect(q.lat, `${q.path} looked in the wrong place`).toBeCloseTo(CHICAGO.latitude, 2);
  await context.close();
});

/* The map drew nothing at all for a while, for a reason unrelated to where the
   user was: renderMap fired initLeaflet inside requestAnimationFrame without
   waiting for it, and drawPins returns early when there is no map yet. Whenever
   the quest fetch resolved before the next frame -- which is what happens every
   time the backend answers from a warm cache -- every pin was dropped, silently,
   onto a map that otherwise looked completely normal. */
test("pins are drawn even when the quests arrive before the map does", async ({ browser, request }) => {
  const { page, context } = await player(browser, request, { at: CHICAGO });

  const near = (n, dLat, dLng) => ({
    org_name: `Test Org ${n}`, address: `${n} Main St`, lat: CHICAGO.latitude + dLat,
    lng: CHICAGO.longitude + dLng, category: "food", legitimacy_score: 0.9,
    quest_type: "daily", verified: true, estimated_points: 20,
    distance_km: Math.round(Math.hypot(dLat, dLng) * 1110) / 10, website: null,
  });

  // Fulfilled from memory, so the fetch always wins the race against the frame.
  await page.route("**/quests?**", (r) => r.fulfill({
    json: [near(1, 0.004, 0.004), near(2, -0.01, 0.012), near(3, 0.02, -0.02)],
  }));
  await page.route("**/reports?**", (r) => r.fulfill({ json: [] }));

  await page.goto("/#map");
  await expect(page.locator(".map-pin")).toHaveCount(3);
  await context.close();
});

test("a wide search frames everything it found, rather than a fixed zoom around the user", async ({ browser, request }) => {
  const { page, context } = await player(browser, request, { at: CHICAGO });

  // 30km north-west: outside the old fixed zoom-14 viewport entirely.
  await page.route("**/quests?**", (r) => r.fulfill({
    json: [{
      org_name: "Far Org", address: "far away", lat: CHICAGO.latitude + 0.27,
      lng: CHICAGO.longitude - 0.27, category: "food", legitimacy_score: 0.9,
      quest_type: "daily", verified: true, estimated_points: 20, distance_km: 30, website: null,
    }],
  }));
  await page.route("**/reports?**", (r) => r.fulfill({ json: [] }));

  await page.goto("/#map");
  await expect(page.locator(".map-pin")).toHaveCount(1);

  // The pin is inside the map's box, not off beyond its edge.
  const map = await page.locator("#map").boundingBox();
  const pin = await page.locator(".map-pin").boundingBox();
  expect(pin.x).toBeGreaterThanOrEqual(map.x);
  expect(pin.x + pin.width).toBeLessThanOrEqual(map.x + map.width);
  expect(pin.y).toBeGreaterThanOrEqual(map.y);
  expect(pin.y + pin.height).toBeLessThanOrEqual(map.y + map.height);
  await context.close();
});
