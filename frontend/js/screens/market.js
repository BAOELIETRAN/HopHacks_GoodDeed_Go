/* Boost: pay points to have people share a cause.
 *
 * The money-shaped part of the app, so the UI is blunt about balances:
 * what you have, what is held, and where every movement went. A points
 * economy that hides its ledger is one people stop trusting.
 */

import { api, ApiError, setSession, state } from "../api.js";
import {
  confirmDelete, empty, esc, h, setupPhotoInput, spinner, statusbar, timeAgo, toast,
} from "../ui.js";

const PLATFORM_LABEL = { instagram: "Instagram Story", snapchat: "Snapchat", tiktok: "TikTok" };
const PLATFORM_ICON = { instagram: "📸", snapchat: "👻", tiktok: "🎵" };

let tab = "board";

export async function renderMarket(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="hero" style="display:block">
      <div class="eyebrow">Boost</div>
      <h2>Get your cause seen</h2>
      <p class="muted" style="margin-top:4px">
        Offer points, and someone will share your fundraiser with their followers.
      </p>
    </div>
    <div class="pad" style="padding-top:0" id="wallet-slot"></div>
    <div class="pad" style="padding-top:0">
      <div class="pills" id="market-tabs">
        <button data-v="board" aria-selected="${tab === "board"}">Open bounties</button>
        <button data-v="mine" aria-selected="${tab === "mine"}">Yours</button>
        <button data-v="new" aria-selected="${tab === "new"}">Post one</button>
      </div>
    </div>
    <div class="pad" id="market-body" style="padding-top:8px">${spinner()}</div>`;

  const body = root.querySelector("#market-body");
  const walletSlot = root.querySelector("#wallet-slot");

  const paintWallet = async () => {
    const w = await api.wallet();
    if (!w) return;
    walletSlot.innerHTML = `
      <div class="card wallet-card">
        <div class="wallet-row">
          <div><strong>${w.available_points}</strong><span>available</span></div>
          <div><strong>${w.escrow_points}</strong><span>held</span></div>
          <div><strong>${w.total_points}</strong><span>total</span></div>
        </div>
        ${w.escrow_points > 0 ? `<p class="tiny" style="margin-top:8px">
          Held points are reserved for your open bounties. They come back if a
          campaign expires or you cancel it.</p>` : ""}
        ${w.transactions.length ? `
          <details class="ledger">
            <summary>Recent activity</summary>
            ${w.transactions.slice(0, 12).map((t) => `
              <div class="ledger-row">
                <span class="grow">${esc(t.note || t.kind)}${
                  t.counterparty ? ` · ${esc(t.counterparty)}` : ""}</span>
                <em class="dir-${t.direction}">${
                  t.direction === "in" ? "+" : t.direction === "out" ? "−" : "•"}${t.amount}</em>
              </div>`).join("")}
          </details>` : ""}
      </div>`;
  };

  const load = async () => {
    body.innerHTML = spinner();
    if (tab === "new") return renderForm(body, refresh);

    const rows = await api.campaigns(tab === "mine");
    if (!rows.length) {
      body.innerHTML = empty(
        tab === "mine" ? "📭" : "🌱",
        tab === "mine" ? "Nothing of yours yet" : "No open bounties",
        tab === "mine"
          ? "Post one and people can pick it up."
          : "Check back later, or post your own cause.",
      );
      return;
    }
    body.replaceChildren(...rows.map((c) => campaignCard(c, refresh)));
  };

  const refresh = async () => { await paintWallet(); await load(); };

  root.querySelectorAll("#market-tabs button").forEach((btn) => {
    btn.onclick = () => {
      tab = btn.dataset.v;
      root.querySelectorAll("#market-tabs button").forEach((b) =>
        b.setAttribute("aria-selected", String(b.dataset.v === tab)));
      load();
    };
  });

  await refresh();
}

function campaignCard(c, refresh) {
  const plats = c.platforms.map((p) => `${PLATFORM_ICON[p] || ""} ${PLATFORM_LABEL[p] || p}`).join(" · ");
  const card = h(`
    <div class="card">
      <div class="row-between" style="align-items:flex-start">
        <div class="grow">
          <h3>${esc(c.title)}</h3>
          <p class="tiny" style="margin-top:3px">${esc(plats)} · ${timeAgo(c.created_at)}</p>
        </div>
        <span class="bounty">${c.bounty}<em>pts</em></span>
      </div>

      ${c.note ? `<p class="feed-desc">${esc(c.note)}</p>` : ""}

      ${c.link_org ? `<p class="tiny" style="margin-top:8px">✓ ${esc(c.link_org)}</p>` : ""}

      <div class="row" style="margin-top:12px;gap:8px">
        <a class="btn-directions grow" href="${esc(c.donation_url)}" target="_blank"
           rel="noopener noreferrer" style="text-align:center">🔗 See the cause</a>
        <span data-action></span>
      </div>
      <div data-proof></div>
    </div>`);

  const slot = card.querySelector("[data-action]");

  if (c.is_mine) {
    slot.innerHTML = `<span class="status-pill status-${c.status === "done" ? "done" : "open"}">${esc(c.status)}</span>`;
    const del = h(`<button class="delete-btn">Delete</button>`);
    del.onclick = async () => {
      const held = c.status === "open" || c.status === "claimed";
      const yes = await confirmDelete({
        title: "Delete this campaign?",
        body: held
          ? `Your ${c.bounty} held points come straight back.`
          : "The payout stays in your history.",
      });
      if (!yes) return;
      try {
        await api.deleteCampaign(c.campaign_id);
        toast(held ? `Deleted — ${c.bounty} points returned` : "Deleted");
        refresh();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Couldn't delete that", true);
      }
    };
    slot.replaceChildren(
      h(`<span class="status-pill status-${c.status === "done" ? "done" : "open"}">${esc(c.status)}</span>`),
      del,
    );
  } else if (c.claimed_by_me && c.status === "claimed") {
    const btn = h(`<button class="btn btn-primary btn-sm">Add proof</button>`);
    btn.onclick = () => renderProof(card.querySelector("[data-proof]"), c, refresh);
    slot.replaceChildren(btn);
  } else if (c.status === "done") {
    slot.innerHTML = `<span class="status-pill status-done">✓ Done</span>`;
  } else {
    const btn = h(`<button class="btn btn-primary btn-sm">Claim it</button>`);
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api.claimCampaign(c.campaign_id);
        toast("Yours — post it, then add the screenshot");
        refresh();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Couldn't claim", true);
        btn.disabled = false;
      }
    };
    slot.replaceChildren(btn);
  }
  return card;
}

function renderProof(mount, c, refresh) {
  let photo = null;
  mount.innerHTML = `
    <hr class="divider">
    <label class="field-label">Screenshot of your post</label>
    <label class="dropzone" id="cproof-zone">
      <input type="file" accept="image/jpeg,image/png,image/webp" id="cproof">
      <div class="guide" id="cproof-guide">
        <span class="guide-icon">${PLATFORM_ICON[c.platforms[0]] || "📷"}</span>
        Tap to add
        <span class="guide-hint">Your story or video, showing the link or cause</span>
      </div>
    </label>
    <p class="err" id="cproof-err" hidden></p>
    <button class="btn btn-primary" id="cproof-send" style="margin-top:12px">Claim ${c.bounty} points</button>`;

  const errEl = mount.querySelector("#cproof-err");
  setupPhotoInput({
    dropzone: mount.querySelector("#cproof-zone"),
    input: mount.querySelector("#cproof"),
    guide: mount.querySelector("#cproof-guide"),
    onPhoto: (d) => { photo = d; },
    onError: (msg) => { errEl.textContent = msg || ""; errEl.hidden = !msg; },
  });

  const send = mount.querySelector("#cproof-send");
  send.onclick = async () => {
    if (!photo) {
      errEl.textContent = "Add a screenshot of your post.";
      errEl.hidden = false;
      return;
    }
    send.disabled = true;
    send.textContent = "Checking…";
    try {
      await api.campaignProof(c.campaign_id, photo, "");
      // The payout lands on the user's own balance, so refresh their session.
      const me = await api.me();
      if (me && state.token) setSession(state.token, me);
      toast(`+${c.bounty} points`);
      refresh();
    } catch (err) {
      errEl.textContent = err instanceof ApiError ? err.message : "Couldn't verify that";
      errEl.hidden = false;
    } finally {
      send.disabled = false;
      send.textContent = `Claim ${c.bounty} points`;
    }
  };
}

function renderForm(mount, refresh) {
  mount.innerHTML = `
    <div class="form-section">
      <label class="field-label" for="c-title">What's the cause?</label>
      <input type="text" id="c-title" maxlength="200" placeholder="e.g. Maryland Food Bank winter appeal">
    </div>
    <div class="form-section">
      <label class="field-label" for="c-url">Link to the donation page</label>
      <input type="text" id="c-url" placeholder="https://…">
      <p class="field-hint">We check the link before anyone sees it.</p>
    </div>
    <div class="form-section">
      <label class="field-label">Where should people post it?</label>
      <div class="pills" id="c-plats">
        ${Object.entries(PLATFORM_LABEL).map(([k, v]) =>
          `<button type="button" data-p="${k}" aria-selected="false">${PLATFORM_ICON[k]} ${v}</button>`).join("")}
      </div>
    </div>
    <div class="form-section">
      <label class="field-label" for="c-bounty">Points offered</label>
      <input type="number" id="c-bounty" min="1" max="1000" value="10">
      <p class="field-hint">Held from your balance until someone completes it.</p>
    </div>
    <div class="form-section">
      <label class="field-label" for="c-note">Anything to add? (optional)</label>
      <textarea id="c-note" maxlength="500" placeholder="Why this cause matters to you"></textarea>
    </div>
    <p class="err" id="c-err" hidden></p>
    <button class="btn btn-primary" id="c-send">Post it</button>`;

  const picked = new Set();
  mount.querySelectorAll("[data-p]").forEach((b) => {
    b.onclick = () => {
      const k = b.dataset.p;
      picked.has(k) ? picked.delete(k) : picked.add(k);
      b.setAttribute("aria-selected", String(picked.has(k)));
    };
  });

  const errEl = mount.querySelector("#c-err");
  const send = mount.querySelector("#c-send");
  send.onclick = async () => {
    const title = mount.querySelector("#c-title").value.trim();
    const url = mount.querySelector("#c-url").value.trim();
    const bounty = parseInt(mount.querySelector("#c-bounty").value, 10) || 0;

    const problem =
      title.length < 3 ? "Give the campaign a title."
      : !url ? "Add the donation link."
      : !picked.size ? "Pick at least one platform."
      : bounty < 1 ? "Offer at least 1 point."
      : null;
    if (problem) {
      errEl.textContent = problem;
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;
    send.disabled = true;
    send.textContent = "Checking the link…";
    try {
      await api.createCampaign({
        title, donation_url: url, platforms: [...picked], bounty,
        note: mount.querySelector("#c-note").value.trim(), expires_in_days: 7,
      });
      toast("Posted — your points are held until someone completes it");
      tab = "mine";
      refresh();
    } catch (err) {
      errEl.textContent = err instanceof ApiError ? err.message : "Couldn't post that";
      errEl.hidden = false;
    } finally {
      send.disabled = false;
      send.textContent = "Post it";
    }
  };
}
