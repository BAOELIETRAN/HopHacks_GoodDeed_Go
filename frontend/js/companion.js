/* Sprout — the companion that grows with you.
 *
 * Points that only increment a number don't create attachment. A creature
 * that visibly changes does, which is why Duolingo has an owl and Forest
 * grows trees. This is the same idea on the app's own tier ladder.
 *
 * Drawn as inline SVG rather than images: no assets to load, crisp at any
 * size, recolours with the theme, and each part can be animated
 * independently (blink, breathe, bounce) without a sprite sheet.
 *
 * Every animation is decorative, so all of it is disabled under
 * prefers-reduced-motion — a creature that bounces forever is exactly the
 * kind of thing that makes an app unusable for some people.
 */

const STAGES = [
  {
    key: "egg", name: "Egg", at: 0,
    blurb: "Something's in there. Do some good and find out.",
    body: "#8fd9a8", accent: "#5ccb7d",
  },
  {
    key: "sprout", name: "Sprout", at: 25,
    blurb: "It hatched. It seems pleased about it.",
    body: "#7ed393", accent: "#43b168",
  },
  {
    key: "seedling", name: "Seedling", at: 100,
    blurb: "Growing fast. It's started following you around.",
    body: "#6bcd8c", accent: "#2f9c56",
  },
  {
    key: "bloom", name: "Bloom", at: 250,
    blurb: "It flowered. That only happens when someone's been busy.",
    body: "#5fc98a", accent: "#e8bd5c",
  },
  {
    key: "guardian", name: "Guardian", at: 500,
    blurb: "Fully grown, and quietly proud of you.",
    body: "#4fc088", accent: "#ffd98a",
  },
  {
    key: "radiant", name: "Radiant", at: 1000,
    blurb: "Rare. Most people never see one of these.",
    body: "#46bd93", accent: "#ffe9a8",
  },
];

export function stageFor(points) {
  const p = Math.max(0, points || 0);
  let current = STAGES[0];
  for (const s of STAGES) if (p >= s.at) current = s;
  return current;
}

export function nextStage(points) {
  const p = Math.max(0, points || 0);
  return STAGES.find((s) => s.at > p) || null;
}

/** Progress toward the next evolution, 0-1. Returns 1 at the final stage. */
export function stageProgress(points) {
  const p = Math.max(0, points || 0);
  const now = stageFor(p);
  const next = nextStage(p);
  if (!next) return 1;
  return Math.min(1, Math.max(0, (p - now.at) / (next.at - now.at)));
}

/**
 * Render the companion.
 *
 * @param points  tier points, which decide the stage
 * @param mood    "idle" | "happy" | "sleepy"
 * @param size    px
 */
export function companionSvg(points, { mood = "idle", size = 150 } = {}) {
  const stage = stageFor(points);
  const isEgg = stage.key === "egg";
  const hasLeaf = ["seedling", "bloom", "guardian", "radiant"].includes(stage.key);
  const hasFlower = ["bloom", "guardian", "radiant"].includes(stage.key);
  const hasCrown = ["guardian", "radiant"].includes(stage.key);
  const radiant = stage.key === "radiant";

  // Eyes: closed crescents when sleepy, otherwise round with a highlight.
  const eye = (cx) =>
    mood === "sleepy"
      ? `<path d="M${cx - 7} 0 q7 6 14 0" stroke="#10312a" stroke-width="3"
            fill="none" stroke-linecap="round"/>`
      : `<g class="cmp-eye">
           <ellipse cx="${cx}" cy="0" rx="7.5" ry="8.5" fill="#10312a"/>
           <circle cx="${cx + 2.4}" cy="-3" r="2.6" fill="#fff" opacity=".92"/>
         </g>`;

  return `
<svg class="companion mood-${mood} stage-${stage.key}" viewBox="0 0 200 200"
     width="${size}" height="${size}" role="img"
     aria-label="${stage.name}, your companion">
  <defs>
    <radialGradient id="cmpBody-${stage.key}" cx="38%" cy="30%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity=".55"/>
      <stop offset="55%" stop-color="${stage.body}"/>
      <stop offset="100%" stop-color="${stage.accent}"/>
    </radialGradient>
    <filter id="cmpGlow"><feGaussianBlur stdDeviation="6" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>

  ${radiant ? `<circle class="cmp-aura" cx="100" cy="108" r="70"
      fill="${stage.accent}" opacity=".22" filter="url(#cmpGlow)"/>` : ""}

  <ellipse class="cmp-shadow" cx="100" cy="176" rx="46" ry="9"
           fill="#04120f" opacity=".28"/>

  <g class="cmp-bob">
    ${hasCrown ? `<g class="cmp-crown">
      <path d="M74 44 L86 62 L100 40 L114 62 L126 44 L120 70 L80 70 Z"
            fill="${stage.accent}" opacity=".95"/>
    </g>` : ""}

    ${hasLeaf ? `<g class="cmp-leaf">
      <path d="M100 64 C100 44 116 34 128 32 C130 48 120 62 100 64 Z" fill="#79d98f"/>
      <path d="M100 64 C100 48 90 40 80 39 C78 52 86 62 100 64 Z" fill="#5cc47a" opacity=".9"/>
      <line x1="100" y1="64" x2="100" y2="48" stroke="#2f9c56" stroke-width="2.5"
            stroke-linecap="round"/>
    </g>` : ""}

    ${hasFlower ? `<g class="cmp-flower">
      ${[0, 72, 144, 216, 288].map((a) => `
        <ellipse cx="128" cy="26" rx="7" ry="11" fill="${stage.accent}"
                 transform="rotate(${a} 128 26)"/>`).join("")}
      <circle cx="128" cy="26" r="5" fill="#fff8e2"/>
    </g>` : ""}

    <g class="cmp-body">
      ${isEgg
        ? `<ellipse cx="100" cy="112" rx="52" ry="62" fill="url(#cmpBody-egg)"/>
           <path class="cmp-crack" d="M74 96 l14 12 l-9 11 l16 13"
                 stroke="#2f7d55" stroke-width="3" fill="none"
                 stroke-linecap="round" stroke-linejoin="round" opacity=".55"/>`
        : `<ellipse cx="100" cy="116" rx="56" ry="52"
                    fill="url(#cmpBody-${stage.key})"/>
           <ellipse cx="78" cy="98" rx="17" ry="13" fill="#fff" opacity=".22"/>`}
    </g>

    ${isEgg ? "" : `
      <g class="cmp-face" transform="translate(0 108)">
        ${eye(82)}${eye(118)}
        <path class="cmp-smile" d="M86 18 q14 13 28 0" stroke="#10312a"
              stroke-width="3.4" fill="none" stroke-linecap="round"/>
        <ellipse cx="66" cy="14" rx="7" ry="4.5" fill="#ff9d8c" opacity=".5"/>
        <ellipse cx="134" cy="14" rx="7" ry="4.5" fill="#ff9d8c" opacity=".5"/>
      </g>`}
  </g>

  <g class="cmp-sparks" aria-hidden="true">
    ${[[46, 74], [154, 66], [58, 140], [146, 134], [100, 38]].map(
      ([x, y], i) => `<path class="cmp-spark s${i}"
        d="M${x} ${y - 6} L${x + 2} ${y} L${x + 8} ${y + 1} L${x + 2} ${y + 3}
           L${x} ${y + 9} L${x - 2} ${y + 3} L${x - 8} ${y + 1} L${x - 2} ${y} Z"
        fill="${stage.accent}"/>`).join("")}
  </g>
</svg>`;
}

/** Play the celebration once — a bounce, or a full evolution flourish. */
export function celebrate(el, { evolved = false } = {}) {
  if (!el) return;
  const cls = evolved ? "is-evolving" : "is-happy";
  el.classList.remove("is-happy", "is-evolving");
  void el.offsetWidth; // restart the animation
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), evolved ? 2200 : 900);
}

export { STAGES };
