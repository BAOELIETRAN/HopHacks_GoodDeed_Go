import { expect, test } from "@playwright/test";
import {
  BALTIMORE,
  FILES,
  apiSignup,
  dataUrl,
  dialog,
  earnPoints,
  newPlayer,
  openReportForm,
  shot,
  takeAndUsePhoto,
  waitForLiveVideo,
  widget,
} from "./helpers.mjs";

/** Every photo box gets the same two buttons and the same camera flow. */
async function expectFullPhotoFlow(page, { screenshotName } = {}) {
  const w = widget(page);
  await expect(w.takeButton).toBeVisible();
  await expect(w.uploadButton).toBeVisible();
  await expect(w.takeButton).toHaveText(/Take a photo/);
  await expect(w.uploadButton).toHaveText(/Upload a photo/);
  await expect(page.getByRole("button", { name: /^Take a photo$/ })).toHaveCount(1); // never duplicated

  await takeAndUsePhoto(page);
  await expect(w.takeButton).toHaveText(/Retake photo/);
  await expect(w.uploadButton).toHaveText(/Choose another/);
  if (screenshotName) await shot(page, screenshotName);
}

test.describe("every screen that accepts an image", () => {
  test("log a deed: both options for required and optional photos, and no duplicates when the type changes", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Sol");
    await p.page.goto("/#submit");
    await expect(p.page.locator(".dropzone")).toBeVisible();
    await expectFullPhotoFlow(p.page, { screenshotName: "06-deed-form-photo" });

    // Switching the deed type rebuilds the form: one fresh pair of buttons, and the old photo is gone.
    await p.page.locator('[data-deed="kindness"]').click();
    await expect(p.page.locator(".dropzone")).toBeVisible();
    await expect(p.page.getByRole("button", { name: /^Take a photo$/ })).toHaveCount(1);
    await expect(p.page.getByRole("button", { name: /^Upload a photo$/ })).toHaveCount(1);
    await expect(widget(p.page).preview).toHaveCount(0);

    // Kindness makes the photo optional -- and both options are still offered.
    await expect(widget(p.page).guide).toContainText(/optional/i);
    await expect(widget(p.page).takeButton).toBeVisible();
    await expect(widget(p.page).uploadButton).toBeVisible();
    await p.context.close();
  });

  test("log a deed: a camera photo goes all the way through scoring", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Tam");
    await p.page.goto("/#submit");
    await expect(p.page.locator(".dropzone")).toBeVisible();
    await takeAndUsePhoto(p.page);

    const org = p.page.locator("#org");
    if (await org.count()) await org.fill("Maryland Food Bank");
    await p.page.locator("#desc").fill("Sorted donated cans and packed grocery boxes with two other volunteers for the morning shift.");
    await p.page.locator("#send").click();

    // The result screen replaces the form, and the deed is recorded.
    await expect(p.page.locator(".dropzone")).toHaveCount(0);
    await expect.poll(async () => (await (await request.get("/submissions/mine", { headers: p.headers })).json()).length).toBeGreaterThan(0);
    await p.context.close();
  });

  test("report after-photo: both options, and the camera photo is what gets submitted", async ({ browser, request }) => {
    const poster = await apiSignup(request, "Uma");
    const description = `Litter piled up beside the bus shelter on Charles Street ${Date.now()}`;
    const created = await request.post("/reports", {
      headers: poster.headers,
      data: { photo_url: dataUrl(FILES.orange), description, lat: BALTIMORE.latitude, lng: BALTIMORE.longitude, total_slots: 1 },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const { report_id } = await created.json();

    const p = await newPlayer(browser, request, "Val");
    const claim = await request.post(`/reports/${report_id}/claim`, { headers: p.headers });
    expect(claim.ok(), await claim.text()).toBeTruthy();

    await p.page.goto("/#community");
    await p.page.locator('[data-act="proof"]').first().click();
    await expect(p.page.getByRole("heading", { name: "Add cleanup proof" })).toBeVisible();
    await expectFullPhotoFlow(p.page, { screenshotName: "07-proof-form-photo" });

    await p.page.locator("#desc").fill("Collected two bags of litter and left the glass marked for city pickup.");
    await p.page.locator("#send").click();
    await expect(p.page.getByRole("heading", { name: "Add cleanup proof" })).toBeHidden();

    const after = await request.get(`/reports/${report_id}`, { headers: p.headers });
    const body = await after.json();
    expect(body.proof_photo_url?.startsWith("data:image/jpeg;base64,")).toBe(true);
    await p.context.close();
  });

  test("campaign proof: both options, and the camera photo is accepted", async ({ browser, request }) => {
    const poster = await apiSignup(request, "Wes");
    await earnPoints(request, poster);
    const title = `Share our bake sale ${Date.now()}`;
    const made = await request.post("/campaigns", {
      headers: poster.headers,
      data: { title, donation_url: "https://example.org/donate", platforms: ["instagram"], bounty: 1, note: "Story or reel is fine." },
    });
    expect(made.ok(), await made.text()).toBeTruthy();

    const p = await newPlayer(browser, request, "Xia");
    await p.page.goto("/#market");
    await p.page.locator(".card", { hasText: title }).getByRole("button", { name: "Claim it" }).click();
    // A claimed bounty moves out of "Open bounties" and into "Yours".
    await p.page.getByRole("button", { name: "Yours" }).click();
    const card = p.page.locator(".card", { hasText: title });
    await card.getByRole("button", { name: "Add proof" }).click();

    await expect(card.locator(".dropzone")).toBeVisible();
    await expectFullPhotoFlow(p.page, { screenshotName: "08-campaign-proof-photo" });

    await card.getByRole("button", { name: /^Claim \d+ points$/ }).click();
    await expect(card.getByText("Done", { exact: true })).toBeVisible();
    await p.context.close();
  });
});

test.describe("layout", () => {
  test("both buttons fit side by side on a very narrow phone", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Yan", { mobile: true, viewport: { width: 320, height: 568 } });
    await openReportForm(p.page);
    const w = widget(p.page);
    const a = await w.takeButton.boundingBox();
    const b = await w.uploadButton.boundingBox();

    for (const box of [a, b]) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(320);
    }
    expect(Math.abs(a.y - b.y)).toBeLessThan(4); // same row
    for (const btn of [w.takeButton, w.uploadButton]) {
      const clipped = await btn.evaluate((el) => el.scrollWidth > el.clientWidth + 1);
      expect(clipped, "button label is clipped").toBe(false);
    }
    await w.takeButton.scrollIntoViewIfNeeded();
    await shot(p.page, "09-narrow-phone");
    await p.context.close();
  });

  test("the camera dialog fits a phone screen, with its controls inside the viewport", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Zed", { mobile: true });
    await openReportForm(p.page);
    const cam = dialog(p.page);
    await widget(p.page).takeButton.click();
    await waitForLiveVideo(p.page);

    for (const control of [cam.close, cam.shutter]) {
      const box = await control.boundingBox();
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(844);
      expect(box.x + box.width).toBeLessThanOrEqual(390);
    }
    await cam.shutter.click();
    for (const control of [cam.retake, cam.use]) {
      const box = await control.boundingBox();
      expect(box.y + box.height).toBeLessThanOrEqual(844);
    }
    await p.context.close();
  });

  test("on a phone the bottom nav no longer covers the form's submit button", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Abe", { mobile: true });
    await openReportForm(p.page);
    await expect(p.page.locator("#nav")).toBeHidden();

    await p.page.locator("#send").scrollIntoViewIfNeeded();
    const box = await p.page.locator("#send").boundingBox();
    const hit = await p.page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.id, [box.x + box.width / 2, box.y + box.height / 2]);
    expect(hit).toBe("send"); // the button itself is what a tap would land on
    await shot(p.page, "10-submit-button-reachable");
    await p.context.close();
  });

  test("on desktop the nav stays as a sidebar and the camera works", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Bea", { viewport: { width: 1280, height: 800 } });
    await openReportForm(p.page);
    await expect(p.page.locator("#nav")).toBeVisible(); // unchanged desktop layout
    await takeAndUsePhoto(p.page);
    await shot(p.page, "11-desktop");
    await p.context.close();
  });
});
