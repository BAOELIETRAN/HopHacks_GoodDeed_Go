/* The store, and the collection it fills.
 *
 * Deliberately not a loot box. The app's whole look is paper-and-ink with one
 * accent, and a store full of glows and jackpot noises would read as a
 * different product bolted on. So: the same cards as everywhere else, rarity
 * carried by a hairline and a small label rather than by light, and the drop
 * table printed on the egg before you buy it. If someone spends 900 coins on
 * a Gilded Egg they should already know they had a 15% chance at a legendary.
 *
 * Coins are not tier points, and the header says so in as few words as it
 * can. Buying things must never look like it cost you rank.
 *
 * The reveal is the one animated moment, and it is a single scale-and-settle
 * that prefers-reduced-motion turns off entirely.
 */

import { api, ApiError, state } from "../api.js";
import { emptyState, esc, h, ico, skeleton, toast } from "../ui.js";

let tab = "shop";

export async function renderStore(root) {
  root.innerHTML = `
    <div class="page-head">
      <div>
        <p class="eyebrow">Store</p>
        <h2>Spend what you've earned</h2>
        <p class="muted">Coins come from deeds, the same as points — but spending them never touches your tier or your rank.</p>
      </div>
    </div>
    <div class="pad" id="coin-slot"></div>
    <div class="pad" style="padding-top:0;padding-bottom:var(--s2)">
      <div class="pills" id="store-tabs">
        <button data-v="shop" aria-selected="${tab === "shop"}">Shop</button>
        <button data-v="collection" aria-selected="${tab === "collection"}">Collection</button>
      </div>
    </div>
    <div class="pad" id="store-body">${skeleton(3)}</div>`;

  root.querySelector("#store-tabs").onclick = (e) => {
    const btn = e.target.closest("button[data-v]");
    if (!btn || btn.dataset.v === tab) return;
    tab = btn.dataset.v;
    renderStore(root);
  };

  await refresh(root);
}

async function refresh(root) {
  const body = root.querySelector("#store-body");
  const coinSlot = root.querySelector("#coin-slot");
  if (!body) return;

  try {
    const [catalog, portfolio] = await Promise.all([api.store(), api.portfolio()]);
    coinSlot.innerHTML = coinHeader(portfolio);
    if (tab === "shop") renderShop(root, body, catalog);
    else renderCollection(root, body, portfolio);
  } catch (err) {
    body.innerHTML = "";
    body.append(
      h(`<div class="card" style="padding:var(--s4)"><p class="muted">${esc(err.message || "The store didn't load.")}</p></div>`),
    );
  }
}

/* ---------- header ---------- */

function coinHeader(p) {
  const pct = p.animals_total ? Math.round((p.animals_collected / p.animals_total) * 100) : 0;
  return `
    <div class="card coin-head">
      <div class="coin-head-main">
        <span class="coin-mark" aria-hidden="true">${ico("coins", { size: 20 })}</span>
        <div>
          <strong class="coin-amount">${p.coins.toLocaleString()}</strong>
          <span class="muted tiny"> coins to spend</span>
        </div>
      </div>
      <div class="coin-head-collection">
        <p class="tiny muted">Collection</p>
        <p class="coin-collected">${p.animals_collected}<span class="muted">/${p.animals_total}</span></p>
        <div class="coin-bar" role="img" aria-label="${pct}% of species collected">
          <span style="width:${pct}%"></span>
        </div>
      </div>
    </div>`;
}

/* ---------- shop ---------- */

function renderShop(root, body, catalog) {
  body.innerHTML = `
    <div class="section-title"><h3>Eggs</h3></div>
    <p class="muted tiny store-note">An egg costs coins, but it hatches on deeds. Odds are printed on every egg.</p>
    <div class="store-grid" id="egg-grid">${catalog.eggs.map(eggCard).join("")}</div>

    <div class="section-title"><h3>Avatars</h3></div>
    <p class="muted tiny store-note">One of each. Equip from your collection.</p>
    <div class="store-grid" id="avatar-grid">${catalog.avatars.map(avatarCard).join("")}</div>`;

  body.querySelectorAll("[data-buy]").forEach((btn) => {
    btn.onclick = () => buy(root, btn, btn.dataset.buy);
  });
}

function eggCard(e) {
  const odds = e.odds_pct
    .map((o) => `<li><span class="rar-dot" style="background:${o.tint}"></span>${esc(o.label)} <b>${o.pct}%</b></li>`)
    .join("");
  return `
    <article class="card store-card" style="--edge:${e.tint}">
      <div class="store-art" aria-hidden="true">${e.emoji}</div>
      <h4>${esc(e.label)}</h4>
      <p class="muted tiny">${esc(e.blurb)}</p>
      <ul class="odds">${odds}</ul>
      <p class="tiny hatch-need">${ico("clock", { size: 14 })} Hatches after ${e.hatches_after} more deeds</p>
      <button class="btn ${e.affordable ? "btn-primary" : "btn-ghost"} btn-sm"
              data-buy="${e.code}" ${e.affordable ? "" : "disabled"}>
        ${e.affordable ? `Buy · ${e.price}` : `${e.price} coins`}
      </button>
    </article>`;
}

function avatarCard(a) {
  return `
    <article class="card store-card ${a.owned ? "is-owned" : ""}" style="--edge:${a.tint}">
      <div class="store-art" aria-hidden="true">${a.emoji}</div>
      <h4>${esc(a.label)}</h4>
      <p class="muted tiny">${esc(a.blurb)}</p>
      ${a.owned
        ? `<p class="owned-tag">${ico("check", { size: 14 })} Owned</p>`
        : `<button class="btn ${a.affordable ? "btn-primary" : "btn-ghost"} btn-sm"
                   data-buy="${a.code}" ${a.affordable ? "" : "disabled"}>
             ${a.affordable ? `Buy · ${a.price}` : `${a.price} coins`}
           </button>`}
    </article>`;
}

async function buy(root, btn, code) {
  btn.disabled = true;
  const label = btn.textContent.trim();
  btn.textContent = "…";
  try {
    const item = await api.buyItem({ code });
    toast(item.kind === "egg" ? `${item.label} is yours. Go do some good.` : `${item.label} unlocked.`);
    await refresh(root);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = label;
    toast(err instanceof ApiError ? err.message : "That didn't go through.", true);
  }
}

/* ---------- collection ---------- */

function renderCollection(root, body, p) {
  if (!p.items.length) {
    body.innerHTML = "";
    body.append(
      emptyState({
        icon: "inbox",
        title: "Nothing in here yet",
        body: "Buy an egg and do a couple of deeds — whatever's inside shows up here.",
        action: null,
      }),
    );
    return;
  }

  const eggs = p.items.filter((i) => i.state === "incubating");
  const animals = p.items.filter((i) => i.state === "hatched");
  const avatars = p.items.filter((i) => i.kind === "avatar");

  body.innerHTML = `
    ${eggs.length ? `<div class="section-title"><h3>Incubating</h3></div>
      <div class="store-grid">${eggs.map(incubatingCard).join("")}</div>` : ""}
    ${animals.length ? `<div class="section-title"><h3>Animals</h3></div>
      <div class="store-grid">${animals.map(animalCard).join("")}</div>` : ""}
    ${avatars.length ? `<div class="section-title"><h3>Avatars</h3></div>
      <div class="store-grid">${avatars.map((a) => ownedAvatarCard(a, p.equipped_avatar)).join("")}</div>` : ""}`;

  body.querySelectorAll("[data-hatch]").forEach((btn) => {
    btn.onclick = () => hatch(root, btn, btn.dataset.hatch);
  });
  body.querySelectorAll("[data-equip]").forEach((btn) => {
    btn.onclick = () => equip(root, btn, btn.dataset.equip, btn.dataset.equipped === "1");
  });
}

function incubatingCard(i) {
  const pct = Math.round((i.progress / i.needed) * 100);
  return `
    <article class="card store-card" style="--edge:${i.tint}">
      <div class="store-art ${i.ready ? "is-ready" : ""}" aria-hidden="true">${i.emoji}</div>
      <h4>${esc(i.label)}</h4>
      <div class="coin-bar" role="img" aria-label="${i.progress} of ${i.needed} deeds done">
        <span style="width:${pct}%"></span>
      </div>
      <p class="tiny muted">${i.progress} / ${i.needed} deeds</p>
      ${i.ready
        ? `<button class="btn btn-primary btn-sm" data-hatch="${i.id}">It's ready — open it</button>`
        : `<p class="tiny hatch-need">${i.needed - i.progress} more to go</p>`}
    </article>`;
}

function animalCard(i) {
  return `
    <article class="card store-card" style="--edge:${i.tint}">
      <div class="store-art" aria-hidden="true">${i.emoji}</div>
      <h4>${esc(i.label)}</h4>
      <p class="rarity-tag" style="--edge:${i.tint}">${esc(i.rarity_label || "")}</p>
      <p class="tiny muted">From a ${esc(i.from_egg || "egg")}</p>
    </article>`;
}

function ownedAvatarCard(a, equippedCode) {
  const on = a.code === equippedCode;
  return `
    <article class="card store-card ${on ? "is-owned" : ""}" style="--edge:${a.tint}">
      <div class="store-art" aria-hidden="true">${a.emoji}</div>
      <h4>${esc(a.label)}</h4>
      <button class="btn ${on ? "btn-ghost" : "btn-primary"} btn-sm"
              data-equip="${a.code}" data-equipped="${on ? "1" : "0"}">
        ${on ? "Take off" : "Wear"}
      </button>
    </article>`;
}

async function equip(root, btn, code, isOn) {
  btn.disabled = true;
  try {
    const p = await api.equipAvatar({ code: isOn ? null : code });
    if (state.user) state.user.equipped_avatar = p.equipped_avatar;
    await refresh(root);
  } catch (err) {
    btn.disabled = false;
    toast(err instanceof ApiError ? err.message : "Couldn't change that.", true);
  }
}

/* ---------- the reveal ---------- */

async function hatch(root, btn, itemId) {
  btn.disabled = true;
  btn.textContent = "Opening…";
  try {
    const result = await api.hatchEgg(itemId);
    await showReveal(result);
    await refresh(root);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "It's ready — open it";
    toast(err instanceof ApiError ? err.message : "The egg didn't open.", true);
  }
}

/** A modal that names what came out. Dismissed by anything: button, backdrop, Escape. */
function showReveal(result) {
  return new Promise((resolve) => {
    const { item, rarity_label: rarity, is_new_species: isNew } = result;
    const sheet = h(`
      <div class="sheet-overlay reveal-overlay" role="dialog" aria-modal="true" aria-label="Your egg hatched">
        <div class="sheet reveal-sheet" style="--edge:${item.tint}">
          <p class="eyebrow">It hatched</p>
          <div class="reveal-art" aria-hidden="true">${item.emoji}</div>
          <h3>${esc(item.label)}</h3>
          <p class="rarity-tag" style="--edge:${item.tint}">${esc(rarity)}</p>
          ${isNew ? `<p class="muted tiny">New to your collection.</p>`
                  : `<p class="muted tiny">You've had one of these before.</p>`}
          <button class="btn btn-primary" data-close>Nice</button>
        </div>
      </div>`);

    const close = () => {
      document.removeEventListener("keydown", onKey);
      sheet.remove();
      resolve();
    };
    const onKey = (e) => { if (e.key === "Escape") close(); };

    sheet.querySelector("[data-close]").onclick = close;
    sheet.onclick = (e) => { if (e.target === sheet) close(); };
    document.addEventListener("keydown", onKey);

    (document.getElementById("app") || document.body).appendChild(sheet);
    sheet.querySelector("[data-close]").focus();
  });
}
