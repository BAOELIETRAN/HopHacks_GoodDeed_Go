# Deploying GoodDeed Go

One Render web service serves the API **and** the frontend from the same URL.
That means no CORS setup, no second URL to configure, and one origin to
register with Google.

Three accounts, all free: **Supabase** (database), **Google Cloud** (sign-in),
**Render** (hosting).

Do them in that order — Render needs values from the other two.

---

## 1. Supabase — the database

Render's free disk is wiped on every restart, so SQLite would lose every
account. Supabase gives free Postgres that persists.

1. [supabase.com](https://supabase.com) → **New project**. Save the database
   password it generates; you cannot see it again.
2. **Project Settings → Database → Connection string → URI**.
3. **Pick the "Session pooler" string, not the direct one.**

   This one matters and the error it causes is unhelpful. Render's free tier
   is IPv4-only; Supabase's direct host (`db.xxx.supabase.co`) is IPv6-only.
   Using the direct string gives a connection timeout that looks like a
   firewall problem. The pooler host looks like
   `aws-0-us-east-1.pooler.supabase.com`.

4. Replace `[YOUR-PASSWORD]` in the string with the password from step 1.

Keep that URI — it is `DATABASE_URL` in step 3.

Tables are created automatically on first boot. Nothing to run by hand.

---

## 2. Google Cloud — sign-in

This uses the ID-token flow, so there is **no client secret** — only a public
client ID.

1. [console.cloud.google.com](https://console.cloud.google.com) → create or
   pick a project (the same one holding your Maps key is fine).
2. **APIs & Services → OAuth consent screen**
   - User type: **External**
   - App name, support email, developer email — that's all that's required
   - Scopes: none to add; `email` and `profile` are included by default
   - Publishing status: leave it **Testing**, and add the Google accounts of
     anyone who will demo under **Test users**
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Type: **Web application**
   - **Authorized JavaScript origins**: your Render URL, e.g.
     `https://gooddeed-go.onrender.com`
     Add `http://localhost:8000` too, for local testing.
   - **Authorized redirect URIs**: leave empty. The ID-token flow doesn't
     redirect, which is why there's no secret to manage.
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`).

You won't have the Render URL until step 3. Create the client now with just
localhost, deploy, then come back and add the real origin.

> **While the app is in Testing**, only listed test users can sign in, and
> they see an "unverified app" warning. Getting rid of both means Google's
> verification review, which takes days — not worth it for a hackathon.
> Email/password signup has no such limit, which is why it's still there.

---

## 3. Render — hosting

1. [render.com](https://render.com) → **New → Blueprint** → connect the
   GitHub repo. It reads `render.yaml` and proposes one service.
2. Set the environment variables it asks for:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | The Supabase **session pooler** URI from step 1 |
   | `OPENAI_API_KEY` | Your OpenAI key (platform.openai.com). If an old `ANTHROPIC_API_KEY` is still set on an existing service, delete it: it is ignored |
   | `GOOGLE_MAPS_API_KEY` | Your Maps key, with **Places API (New)** enabled |
   | `GOOGLE_CLIENT_ID` | The OAuth client ID from step 2 |
   | `REFRESH_TOKEN` | Any long random string. Guards the daily-refresh endpoint; the blueprint generates one for you |

3. Deploy. First build takes ~3 minutes.
4. Copy the URL Render assigns and **add it to your Google OAuth
   "Authorized JavaScript origins"** (step 2.3). Sign-in fails until you do.

### Free tier: it sleeps

The free plan spins down after ~15 minutes idle, and the next request takes
**about 50 seconds** to wake it. Mid-demo that reads as a broken app.

Load the page a minute before you present. If the demo matters, the $7/month
Starter plan removes the spin-down entirely — worth it for one month.

The database is unaffected; Supabase doesn't sleep.

---

## Verifying the deploy

```bash
curl https://YOUR-APP.onrender.com/health
```

```json
{"status":"ok","agent":{"places_provider":"google","llm_provider":"openai"},"database":"postgresql"}
```

Check all three:

- `"database":"postgresql"` — not `sqlite`. If it says sqlite, `DATABASE_URL`
  didn't reach the app and **accounts will vanish on the next restart**.
- `"places_provider":"google"` — not `mock`. Otherwise the map shows stub orgs.
- `"llm_provider":"openai"` — not `mock`. Otherwise scoring is fake.

Then `https://YOUR-APP.onrender.com/auth/config` should report
`{"google_enabled":true,...}`. If it's false, `GOOGLE_CLIENT_ID` isn't set and
the Google button is hidden by design.

## Seeding the demo

Render's free plan has no shell. Seed from your laptop against the same
database:

```bash
DATABASE_URL="<the supabase pooler uri>" python3 scripts/seed_demo.py
```

---

## Rotate your keys before going public

The OpenAI and Google Maps keys used during development were pasted into
a chat transcript. Once the app is on a public URL:

1. Create new keys in both consoles and update them in Render.
2. Delete the old ones.
3. **Restrict the Maps key** to the Places API, and set an OpenAI spend
   limit — a public URL means strangers can trigger your paid API calls.

Anyone can sign up on a public deployment, and every submission costs an
OpenAI vision call. There is no rate limiting in this build.


## Daily opportunity refresh

Cached map results are re-fetched every morning at 08:00, so the first person
to open the app doesn't wait on a Google fan-out.

Two mechanisms, because neither alone is sufficient on Render's free tier:

* **In-process timer** — armed at startup, fires at the next 08:00 local. Free
  services sleep when idle, so this only fires if the process happens to be
  awake. No configuration.
* **Render Cron Job** — `gooddeed-daily-refresh` in `render.yaml` POSTs to
  `/admin/refresh-opportunities` at `0 8 * * *`. This is the one that actually
  holds. Cron jobs require a paid plan; on free, either rely on the in-process
  timer or point any external scheduler (GitHub Actions, cron-job.org) at the
  same endpoint.

Trigger it by hand — useful in a demo:

```bash
curl -X POST "$APP_URL/admin/refresh-opportunities" \
     -H "X-Refresh-Token: $REFRESH_TOKEN"
# {"areas":4,"refreshed":4,"skipped":0,"failed":0,"rows":200}
```

It is idempotent: each area's cached rows are replaced wholesale, so running
it twice leaves the same data rather than two copies. Only areas someone has
already looked at are refreshed — guessing at unused cities would burn Places
quota on maps nobody opens.

With `REFRESH_TOKEN` unset the endpoint returns **404**, not an open route: it
triggers a full Places fan-out, so leaving it reachable would let anyone run
up your API bill.
