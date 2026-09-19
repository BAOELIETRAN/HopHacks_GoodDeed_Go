import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { crc32, deflateSync } from "node:zlib";
import { expect } from "@playwright/test";

export const BALTIMORE = { latitude: 39.3299, longitude: -76.6205 };
const SHOTS = join(import.meta.dirname, ".tmp", "shots");
mkdirSync(SHOTS, { recursive: true });
// Let fade/slide animations finish so the picture shows the settled UI, not a mid-transition frame.
export const shot = async (page, name) => {
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
};
const PASSWORD = "hunter22";

/* ---------------------------------------------------------------- test photos */

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body) >>> 0);
  return Buffer.concat([length, body, crc]);
}

/** A small gradient PNG, so screenshots show something and files are real images. */
export function png([r, g, b], size = 96) {
  const row = size * 3 + 1;
  const raw = Buffer.alloc(row * size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const shade = 0.75 + 0.25 * ((x + y) / (2 * size));
      const o = y * row + 1 + x * 3;
      raw[o] = Math.round(r * shade);
      raw[o + 1] = Math.round(g * shade);
      raw[o + 2] = Math.round(b * shade);
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8;
  header[9] = 2;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

export const FILES = {
  blue: { name: "blue.png", mimeType: "image/png", buffer: png([70, 150, 220]) },
  orange: { name: "orange.png", mimeType: "image/png", buffer: png([230, 140, 60]) },
};
export const dataUrl = (file) => `data:${file.mimeType};base64,${file.buffer.toString("base64")}`;

let counter = 0;
export const uniqueEmail = (name) => `${name.toLowerCase().replace(/[^a-z0-9]/g, "")}-${Date.now()}-${++counter}@example.com`;

/* ------------------------------------------------------------------ backend API */

/** Sign up through the API. Returns { token, user, headers }. */
export async function apiSignup(request, name) {
  const res = await request.post("/auth/signup", { data: { name, email: uniqueEmail(name), password: PASSWORD } });
  expect(res.ok(), `signup ${name}: ${await res.text()}`).toBeTruthy();
  const { token, user } = await res.json();
  return { token, user, headers: { Authorization: `Bearer ${token}` } };
}

/** Give a user some spendable points by scoring a deed (mock AI, so this is deterministic). */
export async function earnPoints(request, who) {
  const res = await request.post("/submissions", {
    headers: who.headers,
    data: {
      deed_type: "kindness",
      org_name: "",
      photo_url: "",
      description: "Carried an elderly neighbour's groceries up three flights of stairs and stayed to help unpack.",
      time_spent_minutes: 30,
      lat: BALTIMORE.latitude,
      lng: BALTIMORE.longitude,
      submitted_at: new Date().toISOString(),
    },
  });
  expect(res.ok(), `earn points: ${await res.text()}`).toBeTruthy();
  return res.json();
}

/* ---------------------------------------------------------------------- pages */

/** Runs before any page script. Records every getUserMedia call and every stream
 *  it hands out, so tests can assert on the constraints and on tracks being stopped. */
export function cameraSpy() {
  window.__cam = { calls: [], streams: [] };
  const md = navigator.mediaDevices;
  if (!md?.getUserMedia) return;
  const original = md.getUserMedia.bind(md);
  md.getUserMedia = async (constraints) => {
    window.__cam.calls.push(JSON.parse(JSON.stringify(constraints)));
    const stream = await original(constraints);
    window.__cam.streams.push(stream);
    return stream;
  };
}

export const camera = (page) =>
  page.evaluate(() => ({
    calls: window.__cam?.calls ?? [],
    liveTracks: (window.__cam?.streams ?? []).flatMap((s) => s.getTracks()).filter((t) => t.readyState === "live").length,
    streams: (window.__cam?.streams ?? []).length,
  }));

/** A signed-in player on a fresh page. `mobile` emulates a phone (touch + coarse pointer). */
export async function newPlayer(
  browser,
  request,
  name,
  { mobile = false, init = [], viewport = { width: 390, height: 844 } } = {},
) {
  const who = await apiSignup(request, name);
  const context = await browser.newContext({
    viewport,
    isMobile: mobile,
    hasTouch: mobile,
    permissions: ["camera", "geolocation"],
    geolocation: BALTIMORE,
  });
  await context.addInitScript(
    ([token, user]) => {
      localStorage.setItem("gdg_token", token);
      localStorage.setItem("gdg_user", JSON.stringify(user));
    },
    [who.token, who.user],
  );
  // The app shows a "Your week" popup once per ISO week, ~1s after load, which would
  // block clicks in slower tests. Mark this week as seen the same way recap.js does.
  await context.addInitScript(() => {
    const d = new Date();
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
    const week = Math.ceil(((t - new Date(Date.UTC(t.getUTCFullYear(), 0, 1))) / 86400000 + 1) / 7);
    localStorage.setItem("gdg_recap_seen_week", `${t.getUTCFullYear()}-W${String(week).padStart(2, "0")}`);
  });
  await context.addInitScript(cameraSpy);
  // Each entry is a function, or [function, argument] -- a serialized function loses its closure.
  for (const item of init) {
    if (Array.isArray(item)) await context.addInitScript(item[0], item[1]);
    else await context.addInitScript(item);
  }
  const page = await context.newPage();
  return { ...who, context, page };
}

/* Page objects for the photo widget and its camera dialog. */
export const widget = (page) => ({
  takeButton: page.getByRole("button", { name: /^(Take a photo|Retake photo)$/ }),
  uploadButton: page.getByRole("button", { name: /^(Upload a photo|Choose another)$/ }),
  removeButton: page.getByRole("button", { name: "Remove photo" }),
  uploadInput: page.locator(".dropzone input[type=file]").first(),
  preview: page.locator(".dropzone img"),
  guide: page.locator(".dropzone .guide"),
});

export const dialog = (page) => {
  const root = page.getByRole("dialog", { name: "Take a photo" });
  return {
    root,
    video: root.locator("[data-cam-video]"),
    still: root.locator("[data-cam-still]"),
    shutter: root.getByRole("button", { name: "Take photo" }),
    close: root.getByRole("button", { name: "Close camera" }),
    retake: root.getByRole("button", { name: "Retake", exact: true }),
    use: root.getByRole("button", { name: "Use photo" }),
    flip: root.getByRole("button", { name: "Switch camera" }),
    error: root.locator("[data-cam-error]"),
    retry: root.getByRole("button", { name: "Try again" }),
    uploadInstead: root.getByRole("button", { name: "Upload a photo" }),
    nativeCamera: root.getByRole("button", { name: "Use your phone's camera app" }),
  };
};

/** Wait until the live preview is actually producing frames. */
export async function waitForLiveVideo(page) {
  await expect
    .poll(() =>
      page.evaluate(() => {
        const v = document.querySelector("[data-cam-video]");
        return Boolean(v && v.videoWidth > 0 && !v.paused && v.readyState >= 2);
      }),
    )
    .toBe(true);
}

/* ---------------------------------------------- init-script stubs (pass as [fn, arg]) */

/** getUserMedia rejects with the given DOMException name. */
export const failCamera = (name) => {
  navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("stubbed", name));
};

/** getUserMedia rejects once, then behaves normally (a user who grants access on retry). */
export const failCameraOnce = (name) => {
  const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  let failed = false;
  navigator.mediaDevices.getUserMedia = (constraints) => {
    if (!failed) {
      failed = true;
      return Promise.reject(new DOMException("stubbed", name));
    }
    return original(constraints);
  };
};

/** No camera API at all, as on a plain-http page. */
export const noCameraApi = () => {
  Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
};

/** Report two video inputs so the flip button appears. */
export const twoCameras = () => {
  navigator.mediaDevices.enumerateDevices = async () => [
    { kind: "videoinput", deviceId: "back", label: "Back camera" },
    { kind: "videoinput", deviceId: "front", label: "Front camera" },
  ];
};

/* ------------------------------------------------------------- shared page actions */

export const DESCRIPTION = "Overflowing trash bins at the corner of 3rd and Maple street";

/** The community report form: the most complete photo box in the app. */
export async function openReportForm(page) {
  await page.goto("/#report");
  await expect(page.getByRole("heading", { name: "Report a need" })).toBeVisible();
  await expect(page.locator(".dropzone")).toBeVisible();
}

/** Take a photo with the camera and confirm it. Leaves the dialog closed. */
export async function takeAndUsePhoto(page) {
  const cam = dialog(page);
  await widget(page).takeButton.click();
  await expect(cam.root).toBeVisible();
  await waitForLiveVideo(page);
  await cam.shutter.click();
  await expect(cam.still).toBeVisible();
  await cam.use.click();
  await expect(cam.root).toBeHidden();
  await expect(widget(page).preview).toBeVisible();
}
