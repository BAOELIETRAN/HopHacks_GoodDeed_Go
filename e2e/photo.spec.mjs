import { expect, test } from "@playwright/test";
import {
  BALTIMORE,
  DESCRIPTION,
  FILES,
  camera,
  dialog,
  failCamera,
  failCameraOnce,
  newPlayer,
  noCameraApi,
  openReportForm,
  shot,
  takeAndUsePhoto,
  twoCameras,
  waitForLiveVideo,
  widget,
} from "./helpers.mjs";

test.describe("both options are always visible", () => {
  test("before a photo exists, take and upload are side by side and nothing else is offered", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Ana");
    await openReportForm(p.page);
    const w = widget(p.page);

    await expect(w.takeButton).toBeVisible();
    await expect(w.takeButton).toHaveText(/Take a photo/);
    await expect(w.uploadButton).toBeVisible();
    await expect(w.uploadButton).toHaveText(/Upload a photo/);
    await expect(w.removeButton).toBeHidden();
    await expect(w.guide).toBeVisible();

    // Both are real buttons a keyboard user can reach (the old dropzone <label> was not focusable).
    await w.takeButton.focus();
    await expect(w.takeButton).toBeFocused();
    await p.page.keyboard.press("Tab");
    await expect(w.uploadButton).toBeFocused();

    await shot(p.page, "01-report-form-both-options");
    await p.context.close();
  });
});

test.describe("take a photo with the camera", () => {
  test("live preview -> capture -> review -> retake -> use photo", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Ben");
    await openReportForm(p.page);
    const w = widget(p.page);
    const cam = dialog(p.page);

    await w.takeButton.click();
    await expect(cam.root).toBeVisible();
    await expect(cam.video).toBeVisible();
    await waitForLiveVideo(p.page);
    await expect(cam.shutter).toBeEnabled();
    await expect(cam.still).toBeHidden();
    await shot(p.page, "02-camera-live");

    // Capture shows a still and asks for a decision; nothing is applied to the form yet.
    await cam.shutter.click();
    await expect(cam.still).toBeVisible();
    await expect(cam.video).toBeHidden();
    await expect(cam.retake).toBeVisible();
    await expect(cam.use).toBeVisible();
    await expect(cam.shutter).toBeHidden();
    await expect(w.preview).toHaveCount(0);
    await expect(w.guide).toBeVisible();
    await shot(p.page, "03-camera-review");

    // The still is a real image of the whole frame, not an empty canvas.
    const still = await cam.still.evaluate((img) => ({ w: img.naturalWidth, h: img.naturalHeight }));
    expect(still.w).toBeGreaterThan(100);
    expect(still.h).toBeGreaterThan(100);

    // Retake goes back to the live camera without asking for permission again.
    await cam.retake.click();
    await expect(cam.video).toBeVisible();
    await expect(cam.still).toBeHidden();
    await waitForLiveVideo(p.page);
    expect((await camera(p.page)).calls).toHaveLength(1);

    await cam.shutter.click();
    await expect(cam.still).toBeVisible();
    await cam.use.click();

    // Confirming closes the dialog, shows the preview, and relabels the buttons.
    await expect(cam.root).toBeHidden();
    await expect(w.preview).toBeVisible();
    await expect(w.guide).toBeHidden();
    await expect(w.takeButton).toHaveText(/Retake photo/);
    await expect(w.uploadButton).toHaveText(/Choose another/);
    await expect(w.removeButton).toBeVisible();
    await shot(p.page, "04-photo-chosen");

    // ...and the camera is switched off, not left running behind the scenes.
    await expect.poll(async () => (await camera(p.page)).liveTracks).toBe(0);
    await p.context.close();
  });

  test("a captured photo can be submitted, and arrives as a JPEG", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Cy");
    await openReportForm(p.page);
    await takeAndUsePhoto(p.page);

    await p.page.locator("#desc").fill(DESCRIPTION);
    await p.page.locator("#send").click();
    // Navigation to the feed is the signal that the post went through. (A heading match is
    // too loose: the form itself has one containing the word "community".)
    await expect(p.page).toHaveURL(/#community$/);

    const res = await request.get("/reports", {
      headers: p.headers,
      params: { lat: BALTIMORE.latitude, lng: BALTIMORE.longitude, radius: 20 },
    });
    const mine = (await res.json()).find((r) => r.description === DESCRIPTION);
    expect(mine, "the report should exist").toBeTruthy();
    expect(mine.photo_url.startsWith("data:image/jpeg;base64,")).toBe(true);
    expect(mine.photo_url.length).toBeGreaterThan(2000); // a real frame, not an empty image
    await p.context.close();
  });

  test("retake after confirming replaces the earlier photo", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Di");
    await openReportForm(p.page);
    await takeAndUsePhoto(p.page);
    const first = await widget(p.page).preview.getAttribute("src");

    await takeAndUsePhoto(p.page);
    await expect(widget(p.page).preview).toHaveCount(1);
    expect(await widget(p.page).preview.getAttribute("src")).not.toBe(first);
    await p.context.close();
  });

  test("the rear camera is requested by default, as a preference rather than a demand", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Eli", { mobile: true });
    await openReportForm(p.page);
    await widget(p.page).takeButton.click();
    await waitForLiveVideo(p.page);

    const { calls } = await camera(p.page);
    expect(calls).toHaveLength(1);
    // `ideal`, not `exact`: a laptop or a phone with one camera must still work.
    expect(calls[0].video.facingMode).toEqual({ ideal: "environment" });
    expect(calls[0].audio).toBe(false); // never ask for the microphone
    await p.context.close();
  });
});

test.describe("closing the camera", () => {
  test("cancel, Escape and leaving the screen all stop the camera", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Flo");
    await openReportForm(p.page);
    const cam = dialog(p.page);
    const w = widget(p.page);

    // Close button
    await w.takeButton.click();
    await waitForLiveVideo(p.page);
    expect((await camera(p.page)).liveTracks).toBeGreaterThan(0);
    await cam.close.click();
    await expect(cam.root).toBeHidden();
    await expect.poll(async () => (await camera(p.page)).liveTracks).toBe(0);
    await expect(w.preview).toHaveCount(0); // cancelling adds no photo
    await expect(w.takeButton).toBeFocused(); // focus returns to where the user was

    // Escape
    await w.takeButton.click();
    await waitForLiveVideo(p.page);
    await p.page.keyboard.press("Escape");
    await expect(cam.root).toBeHidden();
    await expect.poll(async () => (await camera(p.page)).liveTracks).toBe(0);

    // Navigating away while the camera is open
    await w.takeButton.click();
    await waitForLiveVideo(p.page);
    await p.page.evaluate(() => {
      location.hash = "community";
    });
    await expect(cam.root).toBeHidden();
    await expect.poll(async () => (await camera(p.page)).liveTracks).toBe(0);
    await p.context.close();
  });

  test("cancelling from the review step discards the shot", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Gus");
    await openReportForm(p.page);
    const cam = dialog(p.page);
    await widget(p.page).takeButton.click();
    await waitForLiveVideo(p.page);
    await cam.shutter.click();
    await expect(cam.still).toBeVisible();

    await cam.close.click();
    await expect(cam.root).toBeHidden();
    await expect(widget(p.page).preview).toHaveCount(0);
    await expect.poll(async () => (await camera(p.page)).liveTracks).toBe(0);
    await p.context.close();
  });

  test("keyboard focus stays inside the open camera dialog", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Hal");
    await openReportForm(p.page);
    const cam = dialog(p.page);
    await widget(p.page).takeButton.click();
    await waitForLiveVideo(p.page);

    await expect(cam.root).toHaveAttribute("aria-modal", "true");
    for (let i = 0; i < 6; i++) {
      await p.page.keyboard.press("Tab");
      const inside = await p.page.evaluate(() => Boolean(document.activeElement?.closest(".cam-overlay")));
      expect(inside, `Tab #${i + 1} escaped the dialog`).toBe(true);
    }
    await p.context.close();
  });
});

test.describe("upload a photo from the device", () => {
  test("choose, replace, and remove", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Ida");
    await openReportForm(p.page);
    const w = widget(p.page);

    await w.uploadInput.setInputFiles(FILES.blue);
    await expect(w.preview).toBeVisible();
    await expect(w.takeButton).toHaveText(/Retake photo/);
    await expect(w.uploadButton).toHaveText(/Choose another/);
    const first = await w.preview.getAttribute("src");

    await w.uploadInput.setInputFiles(FILES.orange);
    await expect.poll(() => w.preview.getAttribute("src")).not.toBe(first);
    await expect(w.preview).toHaveCount(1);

    await w.removeButton.click();
    await expect(w.preview).toHaveCount(0);
    await expect(w.guide).toBeVisible();
    await expect(w.takeButton).toHaveText(/Take a photo/);
    await expect(w.uploadButton).toHaveText(/Upload a photo/);
    await expect(w.removeButton).toBeHidden();

    // With the photo removed, the form asks for one again rather than posting without.
    await p.page.locator("#send").click();
    await expect(p.page.locator("#formerr")).toContainText("Add a photo");
    await p.context.close();
  });

  test("the Upload button opens the file picker without a camera hint", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Jo", { mobile: true });
    await openReportForm(p.page);

    const [chooser] = await Promise.all([p.page.waitForEvent("filechooser"), widget(p.page).uploadButton.click()]);
    // `capture` would make a phone skip the photo library, which is what Upload is for.
    expect(await chooser.element().getAttribute("capture")).toBeNull();
    await chooser.setFiles(FILES.blue);
    await expect(widget(p.page).preview).toBeVisible();
    await p.context.close();
  });

  test("a non-image file is refused with a reason, and any earlier photo is kept", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Kit");
    await openReportForm(p.page);
    const w = widget(p.page);
    await w.uploadInput.setInputFiles(FILES.blue);
    await expect(w.preview).toBeVisible();
    const kept = await w.preview.getAttribute("src");

    await w.uploadInput.setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("not a photo") });
    // Either the browser rejects it outright or the app reports it -- but never a silent corrupt state.
    await expect.poll(async () => {
      const shown = (await w.preview.count()) === 1 ? await w.preview.getAttribute("src") : null;
      const message = await p.page.locator("#formerr").textContent();
      return shown === kept || Boolean(message?.trim());
    }).toBe(true);
    await p.context.close();
  });
});

test.describe("when the camera can't be used", () => {
  for (const [name, expected, canRetry] of [
    ["NotAllowedError", /blocked/i, true],
    ["NotFoundError", /couldn't find a camera/i, false],
    ["NotReadableError", /busy/i, true],
  ]) {
    test(`${name}: explains what happened and offers upload instead`, async ({ browser, request }) => {
      const p = await newPlayer(browser, request, `Err${name.slice(3, 6)}`, { init: [[failCamera, name]] });
      await openReportForm(p.page);
      const cam = dialog(p.page);

      await widget(p.page).takeButton.click();
      await expect(cam.error).toBeVisible();
      await expect(cam.error).toContainText(expected);
      await expect(cam.uploadInstead).toBeVisible();
      if (canRetry) await expect(cam.retry).toBeVisible();
      else await expect(cam.retry).toBeHidden();
      await expect(cam.shutter).toBeHidden();
      await shot(p.page, `05-camera-error-${name}`);

      // The way out really works: upload opens the file picker from the same click.
      const [chooser] = await Promise.all([p.page.waitForEvent("filechooser"), cam.uploadInstead.click()]);
      await expect(cam.root).toBeHidden();
      await chooser.setFiles(FILES.blue);
      await expect(widget(p.page).preview).toBeVisible();
      await p.context.close();
    });
  }

  test("Try again works once access is granted", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Lu", { init: [[failCameraOnce, "NotAllowedError"]] });
    await openReportForm(p.page);
    const cam = dialog(p.page);

    await widget(p.page).takeButton.click();
    await expect(cam.error).toBeVisible();
    await cam.retry.click();
    await expect(cam.error).toBeHidden();
    await waitForLiveVideo(p.page);
    await cam.shutter.click();
    await cam.use.click();
    await expect(widget(p.page).preview).toBeVisible();
    await p.context.close();
  });

  test("with no camera API (plain http) a desktop gets a clear message and upload still works", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Mo", { init: [noCameraApi] });
    await openReportForm(p.page);

    await widget(p.page).takeButton.click();
    await expect(p.page.locator("#formerr")).toContainText(/secure|https/i);
    await expect(p.page.locator("#formerr")).toContainText(/upload a photo/i);
    await expect(dialog(p.page).root).toHaveCount(0);

    await widget(p.page).uploadInput.setInputFiles(FILES.blue);
    await expect(widget(p.page).preview).toBeVisible();
    await expect(p.page.locator("#formerr")).toBeHidden(); // the message clears once a photo is in
    await p.context.close();
  });

  test("a phone with no camera API falls back to its own camera app, rear-facing", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Ned", { mobile: true, init: [noCameraApi] });
    await openReportForm(p.page);

    const [chooser] = await Promise.all([p.page.waitForEvent("filechooser"), widget(p.page).takeButton.click()]);
    expect(await chooser.element().getAttribute("capture")).toBe("environment");
    await chooser.setFiles(FILES.orange);
    await expect(widget(p.page).preview).toBeVisible();
    await expect(dialog(p.page).root).toHaveCount(0);
    await p.context.close();
  });

  test("a blocked camera on a phone also offers the camera app", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Oz", { mobile: true, init: [[failCamera, "NotAllowedError"]] });
    await openReportForm(p.page);
    const cam = dialog(p.page);
    await widget(p.page).takeButton.click();
    await expect(cam.nativeCamera).toBeVisible();

    const [chooser] = await Promise.all([p.page.waitForEvent("filechooser"), cam.nativeCamera.click()]);
    expect(await chooser.element().getAttribute("capture")).toBe("environment");
    await p.context.close();
  });

  test("a laptop is not offered the phone camera app", async ({ browser, request }) => {
    const p = await newPlayer(browser, request, "Pia", { init: [[failCamera, "NotAllowedError"]] });
    await openReportForm(p.page);
    await widget(p.page).takeButton.click();
    await expect(dialog(p.page).error).toBeVisible();
    await expect(dialog(p.page).nativeCamera).toBeHidden();
    await p.context.close();
  });
});

test.describe("switching cameras", () => {
  test("the flip button appears only when there is more than one camera", async ({ browser, request }) => {
    const single = await newPlayer(browser, request, "Quin");
    await openReportForm(single.page);
    await widget(single.page).takeButton.click();
    await waitForLiveVideo(single.page);
    await expect(dialog(single.page).flip).toBeHidden();
    await single.context.close();

    const multi = await newPlayer(browser, request, "Rex", { init: [twoCameras] });
    await openReportForm(multi.page);
    const cam = dialog(multi.page);
    await widget(multi.page).takeButton.click();
    await waitForLiveVideo(multi.page);
    await expect(cam.flip).toBeVisible();

    // Flipping asks for the other side and swaps the stream, releasing the old one.
    await cam.flip.click();
    await expect.poll(async () => (await camera(multi.page)).calls.length).toBe(2);
    const { calls } = await camera(multi.page);
    expect(calls[0].video.facingMode).toEqual({ ideal: "environment" });
    expect(calls[1].video.facingMode).toEqual({ ideal: "user" });
    await waitForLiveVideo(multi.page);
    await expect.poll(async () => (await camera(multi.page)).liveTracks).toBe(1);
    await multi.context.close();
  });
});
