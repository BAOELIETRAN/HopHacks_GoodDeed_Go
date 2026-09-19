/* The check mark and the tier progress bar.
 *
 * There used to be a confetti burst here. A verified deed is now marked with the
 * ink stamp (see stamp() in ui.js), which is quieter and says the same thing.
 */

/** A checkmark that draws itself. A small, quiet confirmation. */
export function checkBurst(mount) {
  if (!mount) return;
  mount.innerHTML = `
    <svg class="check-burst" viewBox="0 0 100 100" width="96" height="96" aria-hidden="true">
      <circle class="cb-ring" cx="50" cy="50" r="42" fill="none"
              stroke="var(--brand)" stroke-width="5"/>
      <path class="cb-tick" d="M30 52 L44 66 L71 36" fill="none"
            stroke="var(--brand)" stroke-width="7"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
}

/* ---------- Tier progress ---------- */

// Mirrors the contract thresholds. The server is the source of truth and
// sends points_to_next_tier; these are only for drawing the bar when we
// have a raw total and no server response to hand.
export const TIERS = [
  { name: "Bronze", at: 0 },
  { name: "Silver", at: 100 },
  { name: "Gold", at: 500 },
];

export function tierProgress(tierPoints) {
  const p = Math.max(0, tierPoints || 0);
  let current = TIERS[0];
  for (const t of TIERS) if (p >= t.at) current = t;
  const next = TIERS.find((t) => t.at > p) || null;
  const span = next ? next.at - current.at : 1;
  return {
    current: current.name,
    next: next?.name ?? null,
    toNext: next ? next.at - p : null,
    // Clamp to 99 while a next tier remains: rounding filled the bar at
    // 499/500, which promises a promotion that hasn't happened.
    pct: next
      ? Math.min(99, Math.max(2, Math.round(((p - current.at) / span) * 100)))
      : 100,
  };
}

/** The XP bar. `animateFrom` replays the fill from an older total. */
export function tierBar(tierPoints, { animateFrom = null } = {}) {
  const now = tierProgress(tierPoints);
  const el = document.createElement("div");
  el.className = "tier-bar";
  el.innerHTML = `
    <div class="row-between" style="margin-bottom:8px">
      <strong style="font-size:13px">${now.current}</strong>
      <span class="tiny">${
        now.next ? `${now.toNext} pts to ${now.next}` : "Top tier"
      }</span>
    </div>
    <div class="bar"><i style="width:${
      animateFrom === null ? now.pct : tierProgress(animateFrom).pct
    }%"></i></div>
    <div class="row-between tiny" style="margin-top:6px;opacity:.75">
      <span>Bronze</span><span>Silver 100</span><span>Gold 500</span>
    </div>`;

  if (animateFrom !== null) {
    // Next frame, so the browser paints the old width before transitioning.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const fill = el.querySelector(".bar > i");
        fill.style.transition = "width .9s cubic-bezier(.2,.9,.3,1)";
        fill.style.width = `${now.pct}%`;
      });
    });
  }
  return el;
}
