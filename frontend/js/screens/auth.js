/* Welcome, sign up and sign in. */

import { api, ApiError, setSession } from "../api.js";
import { esc, h, ico, logoMark, stamp, stampDate, toast } from "../ui.js";
import { go } from "../router.js";

/* --- Google Sign-In -------------------------------------------------------
   Uses Google Identity Services: the button hands us a signed ID token which
   the backend verifies. Only a public client ID is involved, no secret.

   The button renders only when the server reports Google is configured -- a
   button that cannot work is worse than no button -- and any failure to load
   leaves email/password sign-in untouched. */

let cachedConfig = null;

async function googleConfig() {
  if (cachedConfig) return cachedConfig;
  try {
    cachedConfig = await api.authConfig();
  } catch {
    cachedConfig = { google_enabled: false, google_client_id: "" };
  }
  return cachedConfig;
}

function loadGsi() {
  if (window.google?.accounts?.id) return Promise.resolve(true);
  return new Promise((resolve) => {
    const existing = document.getElementById("gsi-script");
    if (existing) {
      existing.addEventListener("load", () => resolve(true));
      existing.addEventListener("error", () => resolve(false));
      return;
    }
    const script = document.createElement("script");
    script.id = "gsi-script";
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

/** Render the Google button into `mount`, if this deployment supports it. */
async function mountGoogleButton(mount) {
  if (!mount) return;
  const config = await googleConfig();
  if (!config.google_enabled || !config.google_client_id) return;
  if (!(await loadGsi())) return;

  try {
    window.google.accounts.id.initialize({
      client_id: config.google_client_id,
      callback: async ({ credential }) => {
        try {
          const res = await api.google(credential);
          setSession(res.token, res.user);
          go("today");
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Google sign-in failed", true);
        }
      },
    });
    const slot = h(`<div style="display:grid;justify-items:start"></div>`);
    mount.replaceChildren(slot);
    window.google.accounts.id.renderButton(slot, {
      theme: "outline", size: "large", shape: "rectangular",
      text: "continue_with", width: 300, logo_alignment: "center",
    });
    mount.appendChild(h(`<div class="row" style="margin:14px 0 2px">
        <hr style="flex:1;border:0;border-top:1px solid var(--line)">
        <span class="tiny">or use email</span>
        <hr style="flex:1;border:0;border-top:1px solid var(--line)">
      </div>`));
  } catch (err) {
    console.warn("[gdg] Google button failed to render:", err);
  }
}

export function renderWelcome(root) {
  root.innerHTML = `
    <div class="welcome">
      <div class="wordmark">${logoMark(30)}GoodDeed Go</div>

      <div class="welcome-main">
        <div>
          <p class="eyebrow">Volunteering, close to home</p>
          <h1>Do one good thing near you today.</h1>
          <p class="welcome-lede">
            GoodDeed Go finds vetted nonprofits and small neighbourhood jobs
            around you. Do one, take a photo, and it counts.
          </p>
        </div>

        <div id="gbtn"></div>
        <div class="welcome-actions">
          <button class="btn btn-primary" data-go="signup">Get started</button>
          <button class="btn btn-ghost" data-go="login">I already have an account</button>
        </div>
        <p class="tiny">Your location is only used to show what's nearby. You stay in control.</p>
      </div>

      <div class="welcome-aside">
        <ol class="steps">
          <li><div><strong>Find something close</strong><span>Nonprofits we've checked, and jobs your neighbours posted.</span></div></li>
          <li><div><strong>Do it, and show it</strong><span>A quick photo is all the proof it takes.</span></div></li>
          <li><div><strong>Earn credit</strong><span>Points build your tier, your streak and your team's ranking.</span></div></li>
        </ol>

        <div class="receipt">
          <span class="receipt-label">Sample entry</span>
          <p><strong>Bagged litter along the creek path</strong></p>
          <p class="tiny">45 minutes · photo checked</p>
          <div class="receipt-foot">
            <span class="receipt-pts">+24<small>pts</small></span>
            ${stamp("Verified", { sub: stampDate(), seed: "welcome", slam: true })}
          </div>
        </div>
      </div>
    </div>`;

  root.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  mountGoogleButton(root.querySelector("#gbtn"));
}

function authForm(root, { title, lede, fields, submitLabel, call, altLabel, altRoute }) {
  root.innerHTML = `
    <div class="appbar"><button data-back aria-label="Back">${ico("back", { size: 22 })}</button><h3>${esc(title)}</h3><span></span></div>
    <div class="auth-form stack">
      <p class="muted">${esc(lede)}</p>
      <div id="gbtn"></div>
      ${fields.map((f) => `
        <label class="field">
          <span>${esc(f.label)}</span>
          <input type="${f.type}" id="${f.id}" placeholder="${esc(f.placeholder || "")}"
                 autocomplete="${f.autocomplete || "off"}">
        </label>`).join("")}
      <p class="err" id="err" hidden></p>
      <button class="btn btn-primary" id="go">${esc(submitLabel)}</button>
      <button class="btn btn-ghost" data-alt>${esc(altLabel)}</button>
    </div>`;

  const errEl = root.querySelector("#err");
  const btn = root.querySelector("#go");
  mountGoogleButton(root.querySelector("#gbtn"));
  root.querySelector("[data-back]").onclick = () => go("welcome");
  root.querySelector("[data-alt]").onclick = () => go(altRoute);

  btn.onclick = async () => {
    const payload = {};
    for (const f of fields) payload[f.id] = root.querySelector("#" + f.id).value.trim();

    const missing = fields.filter((f) => !f.optional && !payload[f.id]);
    if (missing.length) {
      const names = missing.map((f) => f.label.toLowerCase());
      errEl.textContent = `Add your ${names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names.at(-1) : names[0]}.`;
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;
    btn.disabled = true;
    btn.textContent = "One moment…";
    try {
      const res = await call(payload);
      setSession(res.token, res.user);
      go("today");
    } catch (err) {
      const msg = err instanceof ApiError
        ? err.message
        : "Couldn't reach the server. Check your connection and try again.";
      errEl.textContent = msg;
      errEl.hidden = false;
      toast(msg, true);
    } finally {
      btn.disabled = false;
      btn.textContent = submitLabel;
    }
  };
}

export function renderSignup(root) {
  authForm(root, {
    title: "Create account",
    lede: "It takes a minute. Your name is what your team sees on the leaderboard.",
    submitLabel: "Create account",
    altLabel: "I already have an account",
    altRoute: "login",
    call: (p) => api.signup(p),
    fields: [
      { id: "name", label: "Name", type: "text", placeholder: "Maya Chen", autocomplete: "name" },
      { id: "email", label: "Email", type: "email", placeholder: "you@example.com", autocomplete: "email" },
      { id: "password", label: "Password", type: "password", placeholder: "At least 6 characters", autocomplete: "new-password" },
      { id: "username", label: "Username (optional)", type: "text", placeholder: "mayadoesgood", optional: true },
      { id: "city", label: "City (optional)", type: "text", placeholder: "Baltimore", optional: true },
    ],
  });
}

export function renderLogin(root) {
  authForm(root, {
    title: "Sign in",
    lede: "Welcome back. Pick up where you left off.",
    submitLabel: "Sign in",
    altLabel: "Create an account instead",
    altRoute: "signup",
    call: (p) => api.login(p),
    fields: [
      { id: "email", label: "Email", type: "email", placeholder: "you@example.com", autocomplete: "email" },
      { id: "password", label: "Password", type: "password", autocomplete: "current-password" },
    ],
  });
}
