# GoodDeed Go

A Pokémon Go-style app that turns real-world volunteering into a game. The map
shows verified nearby nonprofits as quests; you complete one by photographing
the deed, an AI agent checks the photo is genuine, and the points feed tiers
and leaderboards. A second feed lets people post local problems ("trash under
the bridge") for anyone nearby to claim and fix.

HopHacks build, three people.

---

## Run it

```bash
git clone https://github.com/BAOELIETRAN/Hop_Hacks_Repo.git
cd Hop_Hacks_Repo
pip install -r requirements.txt
cp .env.example .env          # then paste the keys (see "Keys" below)
./run.sh
```

Open **http://localhost:8000**.

One server does everything: FastAPI serves the API *and* the frontend from the
same origin. There is no build step, no `npm install`, and no second port.

> If a page looks stale, you are on a cached build — hard-refresh
> (`Cmd+Shift+R`). Do not run a separate static server on another port; that
> was the cause of several hours of phantom bugs.

---

## Who owns what

| Area | Lives in | Notes |
|---|---|---|
| **AI agent** | `gooddeed_agent/` | Opportunity discovery, photo scoring, org trust checks, report triage. Pure Python, [its own README](gooddeed_agent/README.md). |
| **Backend** | `backend/` | Auth, data, leaderboards, tiers, streaks, badges. FastAPI + SQLAlchemy. |
| **Frontend** | `frontend/` | The whole UI. Plain HTML/CSS/ES modules, [its own README](frontend/README.md). |
| **Deployment** | `render.yaml`, [DEPLOY.md](DEPLOY.md) | One Render service, Supabase Postgres, Google Sign-In. |

The three layers only touch each other through the shared contract below and
the HTTP API. You can work on one without running the others in anger.

---

## Shared data contract

**Do not rename these fields.** All three layers depend on them, and
`tests/test_contract.py` fails the build if they drift.

```jsonc
// Submission
{ "user_id", "org_name", "photo_url", "description",
  "time_spent_minutes", "lat", "lng", "submitted_at" }

// Score result
{ "points": int, "tier_points": int,
  "authenticity_confidence": 0.0-1.0, "rationale": "string" }

// Opportunity / Quest
{ "org_name", "address", "lat", "lng", "category",
  "legitimacy_score": 0.0-1.0, "quest_type": "daily" | "monthly" }

// Community report
{ "report_id", "photo_url", "description", "lat", "lng",
  "status": "open" | "claimed" | "done", "claimed_by", "created_at" }
```

**Tiers** are cumulative per user: Bronze 0–99, Silver 100–499, Gold 500+.

Two notes that trip people up:

- **`points` vs `tier_points`** — `points` goes on the leaderboards and
  includes the quest multiplier. `tier_points` is the slice counting toward
  Bronze/Silver/Gold and excludes multipliers, so a bonus event can't
  fast-track someone to Gold.
- The API adds extra fields beyond the contract (`verified`,
  `estimated_points`, `distance_km`, `is_mine`, `claim_expires_at`, …).
  Extra keys are fine; renamed ones are not.

---

## API

Base URL is the same origin as the app. Everything except `/health` and
`/auth/*` needs `Authorization: Bearer <token>`.

Interactive docs: **http://localhost:8000/docs**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Status + whether the DB and agent are live or mocked |
| `POST` | `/auth/signup` · `/auth/login` | Email/password → `{token, user}` |
| `GET` | `/auth/config` | Whether Google Sign-In is configured here |
| `POST` | `/auth/google` | Google ID token → `{token, user}` |
| `GET` | `/auth/me` | Current user, tier, streak, badges |
| `GET` | `/quests?lat&lng&radius` | Nearby opportunities (cached 5 min) |
| `POST` | `/submissions` | Photo + description → scored result |
| `GET` | `/leaderboard?scope&period` | `friends`\|`nearby` × `daily`\|`weekly` |
| `POST` | `/friends/invite` · `/friends/join` | Team codes |
| `GET` `POST` | `/reports` | List / create community needs |
| `POST` | `/reports/{id}/claim` · `/proof` · `/complete` | The claim lifecycle |

**Photos are sent as `data:` URLs.** The agent accepts them directly, so the
build needs no S3 or Supabase Storage. The frontend downscales to 1024px
first, because raw phone photos are 3–6MB before base64 adds a third.

**Claims expire after 3 hours** if the claimant never submits proof, so an
abandoned claim can't lock a need forever. Submitting proof stops the clock.

---

## Keys

Nothing is required to *run* the app — without keys it serves stub data behind
a visible "demo data" banner.

| Variable | Needed for | Where |
|---|---|---|
| `OPENAI_API_KEY` | Photo scoring, trust checks, report triage | platform.openai.com |
| `ANTHROPIC_API_KEY` | The same, if you'd rather use Claude | console.anthropic.com |
| `GOOGLE_MAPS_API_KEY` | Real nearby orgs | Google Cloud — **enable "Places API (New)"**, not the legacy one |
| `DATABASE_URL` | Persistent accounts | Supabase → Database → URI → **Session pooler** |
| `GOOGLE_CLIENT_ID` | "Sign in with Google" | Google Cloud → Credentials → OAuth client ID (Web) |

Unset `DATABASE_URL` and it falls back to a local SQLite file, which is fine
for development. The map needs **no** key: it uses OpenStreetMap tiles.

Full setup walkthrough: **[DEPLOY.md](DEPLOY.md)**.

---

## Tests

```bash
pytest -q          # 318 tests, no network and no API keys required
```

Everything external sits behind a provider interface, so the suite runs
against deterministic stubs. `tests/test_contract.py` guards the field names
above.

---

## Scripts

```bash
./run.sh                        # start the app
./run.sh --seed                 # ...with demo data loaded first
python3 scripts/seed_demo.py    # 6 users, submissions, reports
python3 scripts/wipe_demo.py    # remove seeded accounts
python3 scripts/wipe_demo.py --all   # remove EVERY account and report
python3 -m gooddeed_agent       # exercise the AI agent on its own
```

---

## Troubleshooting

**The UI looks old / the map has "API KEY REQUIRED" on it**
Cached build. Hard-refresh, and make sure you're on `:8000` and not an old
static server on another port.

**Map shows stub orgs like "Riverside Community Food Bank"**
Those are the mocks. Check `/health` says `"places_provider":"google"`. If it
says `mock`, the Maps key is missing or Places API (New) isn't enabled.

**Every submission scores 0**
That is usually correct — the agent rejects photos that don't match the
description. Check the `rationale` field; it says exactly what it couldn't
confirm. If `/health` says `"llm_provider":"mock"`, the Anthropic key is missing.

**Accounts disappear after a restart**
`/health` will say `"database":"sqlite"`. `DATABASE_URL` isn't reaching the
app, so it fell back to a local file.

**Google button doesn't appear**
`/auth/config` reports `google_enabled: false` when `GOOGLE_CLIENT_ID` is
unset, and the button is hidden on purpose. If it's set but sign-in fails, the
app's URL must be listed under **Authorized JavaScript origins** in Google
Cloud — exactly, with no trailing slash.

---

## Known gaps

Worth knowing before the demo, in rough priority order:

1. **No rate limiting.** Anyone with the URL can sign up, and every submission
   spends an Anthropic vision call.
2. **Rotate the API keys before going public.** The development keys were
   pasted into a chat transcript.
3. **Render's free tier sleeps** after ~15 min idle; the next request takes
   ~50s. Load the page a minute before presenting.
4. **Google OAuth is in "Testing" mode** — only listed test users can sign in,
   and they see an "unverified app" warning. Email/password has no such limit.
5. **The Figma tier numbers** (Bronze 500 / Silver 1,500 / Gold 2,500) don't
   match the contract (0–99 / 100–499 / 500+). The backend implements the
   contract and the UI renders whatever the API returns, so nothing is broken
   — but somebody should decide which scale is wanted.


## Switching the LLM provider

The agent runs on either OpenAI or Claude. Everything above the provider
seam -- rubrics, scoring, the four agent functions -- is identical; only
`gooddeed_agent/providers/` differs.

Set one key and you're done:

```bash
OPENAI_API_KEY=sk-...        # uses gpt-5 via the Responses API
# or
ANTHROPIC_API_KEY=sk-ant-... # uses claude-opus-5 via the Messages API
```

If both keys are set, OpenAI wins. Override with
`GOODDEED_LLM_PROVIDER=anthropic`, and pick a specific model with
`GOODDEED_MODEL`. A model belonging to the other provider is ignored with a
warning rather than 404ing at request time.

With **no** key for the selected provider the agent falls back to
`MockLLMProvider`, which returns plausible stub scores. The app stays usable,
but nothing is really being judged -- check the startup log line
(`Using OpenAI (gpt-5)` / `Using MockLLMProvider ...`) if scores look odd.

Both providers do vision, hosted web search and schema-constrained JSON in a
single request, which is what the agent functions assume. The OpenAI side
uses the Responses API because Chat Completions has no hosted web search, and
`trust_check` and `verify_donation_link` depend on it.
