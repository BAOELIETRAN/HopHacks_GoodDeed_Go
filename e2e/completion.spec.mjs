import { expect, test } from "@playwright/test";
import { BALTIMORE, FILES, dataUrl, newPlayer, shot } from "./helpers.mjs";

// Mirrors backend/config.py. If those change, this fails loudly, which is the point.
const REPORTER_POINTS = 5;
const COMPLETION_MIN_POINTS = 10;

/** Poster posts a need, a helper claims it and submits proof -- all through the API,
 *  so each test can focus on what the UI shows once the poster confirms. */
async function postedAndProven(request, poster, helper, proofText) {
  const description = `Trash piled up along the creek footbridge ${Date.now()}`;
  const created = await request.post("/reports", {
    headers: poster.headers,
    data: { photo_url: dataUrl(FILES.orange), description, lat: BALTIMORE.latitude, lng: BALTIMORE.longitude, total_slots: 1 },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { report_id } = await created.json();

  expect((await request.post(`/reports/${report_id}/claim`, { headers: helper.headers })).ok()).toBeTruthy();
  const proof = await request.post(`/reports/${report_id}/proof`, {
    headers: helper.headers,
    data: { photo_url: dataUrl(FILES.blue), description: proofText, time_spent_minutes: 45 },
  });
  expect(proof.ok(), await proof.text()).toBeTruthy();
  return { description, report_id };
}

async function joinSameTeam(request, a, b) {
  const { invite_code } = await (await request.post("/friends/invite", { headers: a.headers })).json();
  expect((await request.post("/friends/join", { headers: b.headers, data: { invite_code } })).ok()).toBeTruthy();
}

const cardFor = (page, description) => page.locator(".card", { hasText: description });
const bodyText = (page) => page.evaluate(() => document.body.innerText);

test.describe("confirming a community task pays both people", () => {
  test("the poster confirms in the UI; each person then sees their own credit, and the leaderboard shows both", async ({ browser, request }) => {
    const poster = await newPlayer(browser, request, "Pia");
    const helper = await newPlayer(browser, request, "Hana");
    await joinSameTeam(request, poster, helper);
    const { description } = await postedAndProven(
      request, poster, helper, "Collected three bags of litter and cleared the drain by the footbridge.",
    );

    // --- The poster confirms from the Community feed ---
    await poster.page.goto("/#community");
    const posterCard = cardFor(poster.page, description);
    await expect(posterCard.getByText("Waiting", { exact: false }).or(posterCard.getByRole("button", { name: /Confirm/ }))).toBeVisible();
    await posterCard.getByRole("button", { name: /Confirm/ }).click();

    // The toast names both payouts.
    const toast = poster.page.locator(".toast");
    await expect(toast).toContainText(`You earned +${REPORTER_POINTS} pts`);
    await expect(toast).toContainText(/the helper earned \+\d+/);
    const helperPoints = Number(/helper earned \+(\d+)/.exec(await toast.textContent())[1]);
    expect(helperPoints).toBeGreaterThanOrEqual(COMPLETION_MIN_POINTS);

    // --- Poster's Completed tab: their own credit, plus a plain-language note ---
    await poster.page.getByRole("button", { name: "Completed" }).click();
    const finishedForPoster = cardFor(poster.page, description);
    await expect(finishedForPoster).toContainText(`+${REPORTER_POINTS} pts for reporting`);
    await expect(finishedForPoster).toContainText("Confirmed by the poster");
    await expect(finishedForPoster).not.toContainText(/no points/i);
    await shot(poster.page, "20-completed-poster-view");

    // --- Helper's view of the same card ---
    await helper.page.goto("/#community");
    await helper.page.getByRole("button", { name: "Completed" }).click();
    const finishedForHelper = cardFor(helper.page, description);
    await expect(finishedForHelper).toContainText(`+${helperPoints} pts earned`);
    await expect(finishedForHelper).toContainText("You joined");
    await expect(finishedForHelper).not.toContainText(/no points/i);
    await shot(helper.page, "21-completed-helper-view");

    // --- Leaderboard: both people are on it, with what they earned ---
    await poster.page.goto("/#leaderboard");
    const rows = poster.page.locator(".lb-row");
    await expect(rows.filter({ hasText: "Hana" })).toContainText(String(helperPoints));
    await expect(rows.filter({ hasText: "Pia" })).toContainText(String(REPORTER_POINTS));
    await shot(poster.page, "22-leaderboard-both");

    // --- Nothing anywhere reads as placeholder text ---
    for (const page of [poster.page, helper.page]) {
      for (const route of ["community", "leaderboard", "profile"]) {
        await page.goto(`/#${route}`);
        await page.waitForTimeout(500);
        const text = await bodyText(page);
        expect(text.toLowerCase(), `${route} shows placeholder text`).not.toContain("[mock]");
        expect(text, `${route} names the mock provider`).not.toContain("MockLLMProvider");
      }
    }

    await poster.context.close();
    await helper.context.close();
  });

  test("a proof the AI can't confirm still earns the helper the completion credit", async ({ browser, request }) => {
    const poster = await newPlayer(browser, request, "Pat");
    const helper = await newPlayer(browser, request, "Hal");
    // The stub AI refuses text like this, so the raw score is zero.
    const { description } = await postedAndProven(request, poster, helper, "asdf spam lorem ipsum");

    await poster.page.goto("/#community");
    await cardFor(poster.page, description).getByRole("button", { name: /Confirm/ }).click();
    await expect(poster.page.locator(".toast")).toContainText(`the helper earned +${COMPLETION_MIN_POINTS}`);

    await helper.page.goto("/#community");
    await helper.page.getByRole("button", { name: "Completed" }).click();
    const card = cardFor(helper.page, description);
    await expect(card).toContainText(`+${COMPLETION_MIN_POINTS} pts earned`);
    await expect(card).not.toContainText(/no points/i);

    // Their balance really moved, not just the label.
    const me = await (await request.get("/auth/me", { headers: helper.headers })).json();
    expect(me.tier_points).toBe(COMPLETION_MIN_POINTS);
    const posterMe = await (await request.get("/auth/me", { headers: poster.headers })).json();
    expect(posterMe.tier_points).toBe(REPORTER_POINTS);

    await poster.context.close();
    await helper.context.close();
  });

  test("the poster's profile lists the credit, and the poster's cached points update without a reload", async ({ browser, request }) => {
    const poster = await newPlayer(browser, request, "Quill");
    const helper = await newPlayer(browser, request, "Rae");
    const { description } = await postedAndProven(request, poster, helper, "Bagged the litter and swept the path clean.");

    await poster.page.goto("/#community");
    await cardFor(poster.page, description).getByRole("button", { name: /Confirm/ }).click();
    await expect(poster.page.locator(".toast")).toBeVisible();

    // The app caches the signed-in user; it should already reflect the new points.
    await expect
      .poll(() => poster.page.evaluate(() => JSON.parse(localStorage.getItem("gdg_user") || "null")?.tier_points))
      .toBe(REPORTER_POINTS);

    // And the history the profile reads includes the entry.
    const history = await (await request.get("/submissions/mine", { headers: poster.headers })).json();
    expect(history.map((h) => [h.deed_type, h.points])).toEqual([["community_report", REPORTER_POINTS]]);

    await poster.context.close();
    await helper.context.close();
  });
});

test.describe("when the AI isn't connected", () => {
  test("the app says so in a banner, instead of leaking placeholder text into cards", async ({ browser, request }) => {
    // The e2e backend runs with mocks forced, i.e. exactly "AI not connected".
    const health = await (await request.get("/health")).json();
    expect(health.agent.llm_provider).toBe("mock");

    const p = await newPlayer(browser, request, "Sid");
    await p.page.goto("/#community");
    const banner = p.page.locator("#mockbanner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Demo scoring");
    await shot(p.page, "23-demo-scoring-banner");
    await p.context.close();
  });
});
