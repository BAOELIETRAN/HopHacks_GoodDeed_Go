// Run with:  node --test tests/js
// Covers the DOM-free parts of frontend/js/photo.js. The dialog and widget
// themselves are exercised in a real browser by e2e/photo.spec.mjs.
import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_CAPTURE_EDGE, cameraSupport, describeCameraError, fitWithin } from "../../frontend/js/photo.js";

test("photo.js can be imported without a DOM", () => {
  assert.equal(typeof fitWithin, "function");
});

test("fitWithin never scales up", () => {
  assert.deepEqual(fitWithin(800, 600), { width: 800, height: 600 });
  assert.deepEqual(fitWithin(MAX_CAPTURE_EDGE, 900), { width: MAX_CAPTURE_EDGE, height: 900 });
});

test("fitWithin scales the long edge down and keeps the aspect ratio", () => {
  assert.deepEqual(fitWithin(3200, 2400, 1600), { width: 1600, height: 1200 });
  assert.deepEqual(fitWithin(2400, 3200, 1600), { width: 1200, height: 1600 });
  assert.deepEqual(fitWithin(4000, 4000, 1000), { width: 1000, height: 1000 });
});

test("fitWithin tolerates a video that has no size yet", () => {
  assert.deepEqual(fitWithin(0, 0), { width: 0, height: 0 });
  assert.deepEqual(fitWithin(NaN, NaN), { width: NaN, height: NaN });
});

test("a blocked camera says how to fix it and allows a retry", () => {
  for (const name of ["NotAllowedError", "PermissionDeniedError", "SecurityError"]) {
    const info = describeCameraError({ name });
    assert.equal(info.retry, true, name);
    assert.match(info.message, /blocked/i);
    assert.match(info.message, /upload a photo/i);
  }
});

test("a missing camera offers no retry, since trying again cannot help", () => {
  for (const name of ["NotFoundError", "DevicesNotFoundError", "OverconstrainedError"]) {
    const info = describeCameraError({ name });
    assert.equal(info.retry, false, name);
    assert.match(info.message, /couldn't find a camera/i);
  }
});

test("a busy camera can be retried once the other app is closed", () => {
  for (const name of ["NotReadableError", "TrackStartError", "AbortError"]) {
    const info = describeCameraError({ name });
    assert.equal(info.retry, true, name);
    assert.match(info.message, /busy/i);
  }
});

test("unknown and empty errors still produce a usable message", () => {
  for (const err of [new Error("boom"), {}, null, undefined]) {
    const info = describeCameraError(err);
    assert.ok(info.message.length > 10);
    assert.match(info.message, /upload a photo/i);
  }
});

test("every camera failure points the user at the upload alternative", () => {
  for (const name of ["NotAllowedError", "NotFoundError", "NotReadableError", "SomethingElse"]) {
    assert.match(describeCameraError({ name }).message, /upload a photo/i, name);
  }
});

const phone = { maxTouchPoints: 5, mediaDevices: { getUserMedia() {} } };
const coarse = (matches) => ({ ontouchstart: null, matchMedia: () => ({ matches }) });

test("cameraSupport: a phone with getUserMedia gets both the in-app and native camera", () => {
  assert.deepEqual(cameraSupport(phone, coarse(true)), { inApp: true, touch: true });
});

test("cameraSupport: a plain-http page has no getUserMedia, so only the native camera remains", () => {
  const insecure = { maxTouchPoints: 5 }; // mediaDevices is undefined outside https/localhost
  assert.deepEqual(cameraSupport(insecure, coarse(true)), { inApp: false, touch: true });
});

test("cameraSupport: a laptop webcam is in-app only, not touch", () => {
  const laptop = { maxTouchPoints: 0, mediaDevices: { getUserMedia() {} } };
  assert.deepEqual(cameraSupport(laptop, { matchMedia: () => ({ matches: false }) }), { inApp: true, touch: false });
});

test("cameraSupport: a touchscreen laptop (fine pointer) is not treated as a phone", () => {
  const touchLaptop = { maxTouchPoints: 10, mediaDevices: { getUserMedia() {} } };
  assert.equal(cameraSupport(touchLaptop, coarse(false)).touch, false);
});

test("cameraSupport: a desktop without a camera API reports neither path", () => {
  assert.deepEqual(cameraSupport({ maxTouchPoints: 0 }, { matchMedia: () => ({ matches: false }) }), {
    inApp: false,
    touch: false,
  });
});

test("cameraSupport: safe in environments with no navigator or window at all", () => {
  assert.deepEqual(cameraSupport(undefined, undefined), { inApp: false, touch: false });
});
