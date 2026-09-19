/* Confetti and the tier progress bar.
 *
 * Confetti is drawn on a canvas rather than as DOM nodes: 90 elements
 * animating at once thrashes layout, and a canvas is one composited layer.
 * It self-removes when the last piece falls, so nothing is left behind.
 *
 * Skipped entirely under prefers-reduced-motion -- a full-screen particle
 * burst is exactly the kind of thing that setting exists for.
 */

const COLORS = ["#5ccb7d", "#e8bd5c", "#ff9d8c", "#8fd9f0", "#ffe9a8", "#ffffff"];

export function confettiBurst({ count = 90, duration = 2200 } = {}) {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;

  const canvas = document.createElement("canvas");
  canvas.className = "confetti-canvas";
  const host = document.getElementById("app") || document.body;
  host.appendChild(canvas);

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = host.clientWidth, hgt = host.clientHeight;
  canvas.width = w * dpr;
  canvas.height = hgt * dpr;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    // No 2D context (canvas disabled, memory pressure, a headless runtime).
    // Confetti is decoration; it must never take the screen down with it.
    canvas.remove();
    return;
  }
  ctx.scale(dpr, dpr);

  // Two side cannons rather than a top-down drizzle: the arc reads as
  // celebration, falling flakes read as weather.
  const pieces = Array.from({ length: count }, (_, i) => {
    const left = i % 2 === 0;
    return {
      x: left ? w * 0.08 : w * 0.92,
      y: hgt * 0.62,
      vx: (left ? 1 : -1) * (3 + Math.random() * 6),
      vy: -(7 + Math.random() * 7),
      size: 5 + Math.random() * 6,
      color: COLORS[(Math.random() * COLORS.length) | 0],
      spin: (Math.random() - 0.5) * 0.4,
      angle: Math.random() * Math.PI,
      sway: Math.random() * 0.06,
    };
  });

  const start = performance.now();
  let raf;

  const frame = (now) => {
    const elapsed = now - start;
    if (elapsed > duration) {
      cancelAnimationFrame(raf);
      canvas.remove();
      return;
    }
    // Fade the last 500ms so pieces don't vanish mid-flight.
    ctx.clearRect(0, 0, w, hgt);
    ctx.globalAlpha = Math.max(0, Math.min(1, (duration - elapsed) / 500));

    for (const p of pieces) {
      p.vy += 0.32;                       // gravity
      p.vx *= 0.995;                      // drag
      p.x += p.vx + Math.sin(now * p.sway * 0.01) * 0.6;
      p.y += p.vy;
      p.angle += p.spin;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.angle);
      ctx.fillStyle = p.color;
      // Rectangles, squashed on one axis, so they read as tumbling paper.
      ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      ctx.restore();
    }
    raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
}

/** A checkmark that draws itself. Used when confetti would be too much. */
export function checkBurst(mount) {
  if (!mount) return;
  mount.innerHTML = `
    <svg class="check-burst" viewBox="0 0 100 100" width="96" height="96" aria-hidden="true">
      <circle class="cb-ring" cx="50" cy="50" r="42" fill="none"
              stroke="var(--green)" stroke-width="5"/>
      <path class="cb-tick" d="M30 52 L44 66 L71 36" fill="none"
            stroke="var(--green)" stroke-width="7"
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
    <div class="row-between" style="margin-bottom:7px">
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
