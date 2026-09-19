/* Welcome, sign up and sign in. */

import { api, ApiError, setSession } from "../api.js";
import { esc, statusbar, toast } from "../ui.js";
import { go } from "../router.js";

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
      <button class="btn btn-primary" data-go="signup">Let's do some good</button>
      <button class="btn btn-ghost" data-go="login">I already have an account</button>
      <p class="tiny center">Location is used only to show nearby opportunities. You're always in control.</p>
    </div>`;

  root.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
}

function authForm(root, { title, fields, submitLabel, call, altLabel, altRoute }) {
  root.innerHTML = `
    ${statusbar()}
    <div class="appbar"><button data-back>‹</button><h3>${esc(title)}</h3><span></span></div>
    <div class="pad stack">
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
