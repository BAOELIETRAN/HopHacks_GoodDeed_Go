/* Welcome, sign up and sign in. */

import { api, ApiError, setSession } from "../api.js";
import { esc, h, statusbar, toast } from "../ui.js";
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
          go("map");
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Google sign-in failed", true);
        }
      },
    });
    const slot = h(`<div style="display:grid;place-items:center"></div>`);
    mount.replaceChildren(slot);
    window.google.accounts.id.renderButton(slot, {
      theme: "outline", size: "large", shape: "pill",
      text: "continue_with", width: 300, logo_alignment: "center",
    });
    mount.appendChild(h(`<div class="row" style="margin:14px 0 2px">
        <hr style="flex:1;border:0;border-top:1px solid var(--cream-deep)">
        <span class="tiny">or</span>
        <hr style="flex:1;border:0;border-top:1px solid var(--cream-deep)">
      </div>`));
  } catch (err) {
    console.warn("[gdg] Google button failed to render:", err);
  }
}

export function renderWelcome(root) {
  root.innerHTML = `
    ${statusbar()}
    <div class="pad stack" style="padding-top:20px">
      <div class="row center" style="justify-content:center;gap:8px">
        <span style="font-size:20px">✦</span><h3>GoodDeed Go</h3>
      </div>
      <div class="panel panel-blue" style="height:230px;display:grid;place-items:center;position:relative">
        <div style="position:absolute;top:22px;right:34px;width:52px;height:52px;border-radius:50%;background:var(--yellow-deep)"></div>
        <div style="position:absolute;top:34px;left:28px;font-size:22px">✦</div>
        <div class="mascot"><div class="eyes"><i class="eye"></i><i class="eye"></i></div></div>
      </div>
      <h1>Small deeds.<br>Real-world wins.</h1>
      <p class="muted">Find trusted local quests, help your neighborhood, and grow your impact streak.</p>
      <div class="row" style="gap:10px;align-items:stretch">
        ${[["⌖", "Find", "a nearby need"], ["♥", "Help", "with proof"], ["★", "Grow", "points & trust"]]
          .map(([i, t, s]) => `
            <div class="card center" style="flex:1;padding:14px 8px">
              <div style="font-size:21px;color:var(--green-press)">${i}</div>
              <div style="font-weight:800;margin-top:5px;font-size:13px">${t}</div>
              <div class="tiny">${s}</div>
            </div>`).join("")}
      </div>
      <div id="gbtn"></div>
      <button class="btn btn-primary" data-go="signup">Let's do some good</button>
      <button class="btn btn-ghost" data-go="login">I already have an account</button>
      <p class="tiny center">Location is used only to show nearby opportunities. You're always in control.</p>
    </div>`;

  root.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  mountGoogleButton(root.querySelector("#gbtn"));
}

function authForm(root, { title, fields, submitLabel, call, altLabel, altRoute }) {
  root.innerHTML = `
    ${statusbar()}
    <div class="appbar"><button data-back>‹</button><h3>${esc(title)}</h3><span></span></div>
    <div class="pad stack">
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
      errEl.textContent = `Please fill in: ${missing.map((f) => f.label.toLowerCase()).join(", ")}`;
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;
    btn.disabled = true;
    btn.textContent = "Just a second…";
    try {
      const res = await call(payload);
      setSession(res.token, res.user);
      go("map");
    } catch (err) {
      const msg = err instanceof ApiError
        ? err.message
        : "Couldn't reach the server. Is the backend running on port 8000?";
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
