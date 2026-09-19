/* Live friend activity, by polling.
 *
 * No websockets on purpose: a persistent connection needs server-side
 * infrastructure this build does not have, and the thing being announced --
 * a friend logged a deed — is not worth a socket. Polling every 45s and on
 * tab focus is indistinguishable to a user and is a few lines.
 *
 * Restraint is most of the design here. A notification that fires on your
 * own action, or on the first load of a feed you have never seen, is noise
 * and teaches people to ignore the real ones:
 *
 *   - The first poll only records a watermark; it never announces.
 *   - Your own deeds are filtered out.
 *   - Polling stops while the tab is hidden, and catches up on focus.
 *   - Nothing runs when signed out.
 */

import { api, state } from "./api.js";
import { esc, toast } from "./ui.js";

const POLL_MS = 45_000;

let timer = null;
let watermark = null;     // ISO of the newest item we've already accounted for
let primed = false;       // has the first (silent) poll happened
let running = false;      // guards against overlapping polls

function describe(items) {
  const names = [...new Set(items.map((i) => i.user_name))];
  if (items.length === 1) {
    const it = items[0];
    return `${it.user_name} logged a good deed · +${it.points}`;
  }
  if (names.length === 1) return `${names[0]} logged ${items.length} good deeds`;
  if (names.length === 2) return `${names[0]} and ${names[1]} have been busy`;
  return `${names[0]} and ${names.length - 1} others have been busy`;
}

async function poll() {
  if (running || !state.token || document.hidden) return;
  running = true;
  try {
    const items = await api.feed(watermark || undefined);
    if (!Array.isArray(items) || !items.length) return;

    // Newest first from the API; the newest timestamp becomes the watermark
    // whether or not we announce, so a filtered-out item is not re-reported.
    const newest = items[0]?.created_at;
    if (newest) watermark = newest;

    if (!primed) {
      // First run establishes "already seen" — announcing a feed the user
      // has never opened would fire on every fresh session.
      primed = true;
      return;
    }

    const theirs = items.filter((i) => !i.is_mine);
    if (theirs.length) toast(describe(theirs));
  } catch {
    // A failed poll is not worth surfacing; the next one will catch up.
  } finally {
    running = false;
  }
}

/** Begin watching. Safe to call more than once. */
export function startLiveActivity() {
  if (timer) return;
  poll();                                   // primes the watermark silently
  timer = setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("focus", poll);
}

export function stopLiveActivity() {
  clearInterval(timer);
  timer = null;
  document.removeEventListener("visibilitychange", onVisible);
  window.removeEventListener("focus", poll);
  primed = false;
  watermark = null;
}

function onVisible() {
  // Coming back to the tab is the moment someone most wants to know what
  // they missed, so catch up immediately rather than waiting out the timer.
  if (!document.hidden) poll();
}

export const _test = { poll, describe, reset: () => { primed = false; watermark = null; } };
