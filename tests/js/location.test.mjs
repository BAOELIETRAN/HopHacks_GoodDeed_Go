// Run with:  node --test tests/js
//
// Covers frontend/js/location.js -- specifically that a failure to get a real
// position is never silently dressed up as a real position. The bug this file
// exists for: every geolocation failure resolved a hardcoded Baltimore
// coordinate with nothing in the result to say so, so the app confidently
// described the wrong city.
//
// The browser globals the module touches (navigator.geolocation, localStorage,
// window) are stubbed here rather than mocked in a real browser; the ordering
// logic is plain data flow and this keeps it fast.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

/* --- browser stubs ---------------------------------------------------------- */

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

let geoBehaviour = null; // (success, error) => void
// Node 22 defines `navigator` itself, as a getter-only global.
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  writable: true,
  value: {
    geolocation: {
      getCurrentPosition: (ok, fail, opts) => geoBehaviour(ok, fail, opts),
    },
  },
});

// config.js resolves the API base from the page URL at import time.
globalThis.location = { port: "", protocol: "https:", hostname: "localhost", origin: "https://localhost" };

const events = [];
globalThis.window = {
  isSecureContext: true,
  dispatchEvent: (e) => events.push(e),
};
globalThis.CustomEvent = class {
  constructor(type, { detail } = {}) { this.type = type; this.detail = detail; }
};

const loc = await import("../../frontend/js/location.js");
const { LAST_RESORT_LOCATION } = await import("../../frontend/js/config.js");

const CHICAGO = { latitude: 41.8781, longitude: -87.6298, accuracy: 18 };

const grants = (coords) => (ok) => ok({ coords });
const refuses = (code) => (_ok, fail) => fail({ code });

beforeEach(() => {
  store.clear();
  events.length = 0;
  globalThis.window.isSecureContext = true;
  loc.forgetCachedLocation();
});

/* --- a real fix ------------------------------------------------------------- */

test("a device fix is reported as exact, at the coordinates the device gave", async () => {
  geoBehaviour = grants(CHICAGO);
  const got = await loc.getLocation();

  assert.equal(got.source, "device");
  assert.equal(got.approximate, false);
  assert.equal(got.lat, 41.8781);
  assert.equal(got.lng, -87.6298);
  assert.equal(got.accuracyM, 18);
  assert.ok(loc.isDeviceFix(got));
});

test("the first attempt refuses a cached position, which is what goes stale when you travel", async () => {
  const seen = [];
  geoBehaviour = (ok, _fail, opts) => { seen.push(opts); ok({ coords: CHICAGO }); };
  await loc.getLocation();

  assert.equal(seen[0].maximumAge, 0, "a cached fix is exactly the wrong answer after moving");
  assert.ok(seen[0].timeout >= 15000, "a cold GPS fix outdoors takes longer than 6s");
});

/* --- the failures that used to look like success ---------------------------- */

test("with no fix and no history, the built-in default is flagged as a guess", async () => {
  geoBehaviour = refuses(2);
  const got = await loc.getLocation();

  assert.equal(got.source, "default");
  assert.equal(got.approximate, true, "the whole bug was this being indistinguishable from a real fix");
  assert.equal(got.lat, LAST_RESORT_LOCATION.lat);
  assert.ok(loc.REASON_TEXT[got.reason], "a reason the user can act on");
  assert.equal(loc.isDeviceFix(got), false);
});

test("a remembered real fix beats the default, and is still flagged approximate", async () => {
  geoBehaviour = grants(CHICAGO);
  await loc.getLocation();          // remembers Chicago
  loc.forgetCachedLocation();
  geoBehaviour = refuses(3);        // now the device times out

  const got = await loc.getLocation();
  assert.equal(got.source, "remembered");
  assert.equal(got.lat, 41.8781, "their real city, not Baltimore");
  assert.equal(got.approximate, true);
  assert.equal(loc.isDeviceFix(got), false, "not evidence of standing anywhere");
});

test("an insecure origin is identified as such, not reported as a denied prompt", async () => {
  globalThis.window.isSecureContext = false;
  geoBehaviour = refuses(1);

  const got = await loc.getLocation();
  assert.equal(got.reason, "insecure");
  assert.match(loc.REASON_TEXT.insecure, /https/, "names the thing the developer has to change");
});

test("a denied prompt is not retried -- asking twice only re-annoys", async () => {
  let calls = 0;
  geoBehaviour = (_ok, fail) => { calls += 1; fail({ code: 1 }); };

  const got = await loc.getLocation();
  assert.equal(calls, 1);
  assert.equal(got.reason, "denied");
});

test("no satellite fix falls back to coarse positioning rather than giving up", async () => {
  let calls = 0;
  geoBehaviour = (ok, fail) => {
    calls += 1;
    if (calls === 1) return fail({ code: 3 });   // no precise fix in time
    return ok({ coords: CHICAGO });              // wifi/cell knows the city
  };

  const got = await loc.getLocation();
  assert.equal(calls, 2);
  assert.equal(got.source, "device", "a coarse fix in the right city is a real fix");
});

/* --- a location set by hand ------------------------------------------------- */

test("a place set by hand outranks the device and survives a reload", async () => {
  geoBehaviour = grants(CHICAGO);
  loc.setManualLocation({ lat: 51.5072, lng: -0.1276, label: "London" });

  const got = await loc.getLocation();
  assert.equal(got.source, "manual");
  assert.equal(got.lat, 51.5072);
  assert.equal(got.label, "London");
  assert.equal(got.approximate, false, "the user knows where they are");
});

test("a place set by hand is not evidence of being there", async () => {
  loc.setManualLocation({ lat: 51.5072, lng: -0.1276, label: "London" });
  const got = await loc.getLocation();
  assert.equal(
    loc.isDeviceFix(got), false,
    "starting a timed check-in or pinning a report needs the device, not a typed city",
  );
});

test("clearing a manual place hands control back to the device", async () => {
  geoBehaviour = grants(CHICAGO);
  loc.setManualLocation({ lat: 51.5072, lng: -0.1276, label: "London" });
  const got = await loc.clearManualLocation();
  assert.equal(got.source, "device");
  assert.equal(got.lat, 41.8781);
});

/* --- plumbing the UI depends on -------------------------------------------- */

test("every resolution is announced, so the shell can say what it settled on", async () => {
  geoBehaviour = refuses(2);
  await loc.getLocation();
  assert.equal(events.at(-1).type, "gdg:location");
  assert.equal(events.at(-1).detail.source, "default");
});

test("concurrent screens share one acquisition instead of each prompting", async () => {
  let calls = 0;
  geoBehaviour = (ok) => { calls += 1; setTimeout(() => ok({ coords: CHICAGO }), 5); };

  const [a, b, c] = await Promise.all([loc.getLocation(), loc.getLocation(), loc.getLocation()]);
  assert.equal(calls, 1);
  assert.deepEqual([a.lat, b.lat, c.lat], [41.8781, 41.8781, 41.8781]);
});

test("`fresh` re-measures instead of reusing the window a heartbeat would outlive", async () => {
  let calls = 0;
  geoBehaviour = (ok) => { calls += 1; ok({ coords: CHICAGO }); };

  await loc.getLocation();
  await loc.getLocation();               // inside the reuse window
  assert.equal(calls, 1);
  await loc.getLocation({ fresh: true }); // a presence heartbeat
  assert.equal(calls, 2);
});
