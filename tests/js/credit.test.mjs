// Run with:  node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import { test } from "node:test";

import { completionMessage, creditLabel } from "../../frontend/js/credit.js";

const done = (over = {}) => ({
  status: "done",
  points_awarded: 25,
  reporter_points_awarded: 5,
  claimed_by_me: false,
  is_mine: false,
  ...over,
});

test("a helper sees what they earned", () => {
  assert.equal(creditLabel(done({ claimed_by_me: true })), "+25 pts earned");
});

test("the poster sees what they earned for reporting, not the helper's figure", () => {
  assert.equal(creditLabel(done({ is_mine: true })), "+5 pts for reporting");
});

test("someone watching sees what the helpers were awarded", () => {
  assert.equal(creditLabel(done()), "+25 pts awarded");
});

test("a person who is both poster and helper (can't be, but must not break) sees their helper credit", () => {
  assert.equal(creditLabel(done({ claimed_by_me: true, is_mine: true })), "+25 pts earned");
});

test("a finished post never says nobody was paid", () => {
  // Confirmed before payouts were recorded: no figures at all.
  const label = creditLabel(done({ points_awarded: 0, reporter_points_awarded: null }));
  assert.equal(label, "completed");
  assert.doesNotMatch(label, /no points/i);
});

test("a poster whose helper earned nothing recorded still sees their own credit", () => {
  assert.equal(creditLabel(done({ is_mine: true, points_awarded: 0 })), "+5 pts for reporting");
});

test("an unfinished post shows the estimate", () => {
  assert.equal(creditLabel({ status: "open", estimated_points: 26 }), "+26 pts");
  assert.equal(creditLabel({ status: "claimed" }), "+20 pts"); // falls back to the default estimate
});

test("the confirmation toast names both payouts (single helper)", () => {
  assert.equal(
    completionMessage({ points_awarded: 25, reporter_points_awarded: 5, filled_slots: 1 }),
    "Confirmed. You earned +5 pts, and the helper earned +25.",
  );
});

test("the confirmation toast says 'each' when several helpers were paid", () => {
  assert.equal(
    completionMessage({ points_awarded: 25, reporter_points_awarded: 5, filled_slots: 3 }),
    "Confirmed. You earned +5 pts, and helpers earned +25 each.",
  );
});
