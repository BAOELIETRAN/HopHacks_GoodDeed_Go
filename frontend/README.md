# GoodDeed Go — frontend

Mobile-first web app built to the Figma reference. **No build step, no npm
install** — plain HTML/CSS/ES modules. Open it with any static server.

## Run it

From the repo root:

```bash
./run.sh --seed     # first time: starts both servers + loads demo data
./run.sh            # after that
```

Then open **http://localhost:5173**. Ctrl+C stops both.

Demo login: `lena@demo.dev` / `demo1234`.

Starting them by hand instead:

```bash
uvicorn backend.main:app --reload --port 8000   # repo root
cd frontend && python3 -m http.server 5173
```

The frontend expects the backend on `http://localhost:8000`. To point it
somewhere else, run this in the browser console — no rebuild needed:

```js
localStorage.setItem("gdg_api_base", "http://192.168.1.50:8000"); location.reload();
```

> Serve it over HTTP, don't double-click `index.html`. ES modules and `fetch`
> are blocked on `file://`.

## It works without the backend

Every read endpoint falls back to placeholder data shaped exactly like the
real responses, so the UI is demoable on its own. A yellow **"Demo data —
backend not reachable"** banner appears whenever a fallback fires, so stub
data is never mistaken for a working API. To force it: `localStorage.setItem("gdg_force_mocks","1")`.

Writes (submit, claim, complete) always hit the real backend — a fake success
there would be actively misleading.

## Screens

| Route | Screen |
|---|---|
| `#map` | Leaflet map, green quest pins + coral community-need pins |
| `#quests` | Quest cards, daily/monthly filter |
| `#quest` | Quest detail — trust signals, "Start quest" |
| `#submit` | **Photo + description + time → POST /submissions** |
| `#result` | Score, rationale, tier progress, streak |
| `#community` | Report feed — claim, add proof, poster confirms |
| `#report` | Post a new community need |
| `#leaderboard` | Friends/Nearby × daily/weekly, podium, tier badges |
| `#profile` | Tier progress, badges, invite code |

## Photos need no storage

The backend takes `photo_url` as a string and the AI agent accepts `data:`
URLs, so photos are sent inline as base64 — **no S3, no Supabase Storage, no
upload endpoint.** `compressImage()` in `js/photo.js` scales to 1024px and
re-encodes at JPEG q82 first, because raw phone photos are 3–6 MB and base64
adds ~33%.

If you later want real hosting, the only change is in `js/screens/submit.js`:
upload the file, then send the returned URL instead of the data URL. Nothing
else in the app touches photo bytes.

## Adding a photo: upload or camera

Every photo box in the app -- quest proof, community report, report after-photo,
campaign proof -- offers the same two buttons: **Take a photo** and **Upload a
photo**. They come from one function, `setupPhotoInput()` in `js/photo.js`, which
adds the buttons beneath the existing `<label class="dropzone">`, so a new photo
box only needs that markup and one call.

- **Take a photo** opens an in-app camera (`getUserMedia`) that asks for the rear
  camera (`facingMode: { ideal: "environment" }` -- a preference, so laptops and
  one-camera phones still work). After the shutter it shows the shot with
  **Retake** and **Use photo**; nothing reaches the form until *Use photo*. A flip
  button appears only if the device has more than one camera.
- **Upload a photo** opens the normal file picker (no `capture` hint, so a phone
  offers its photo library).
- If the in-app camera can't run (plain-http page, no permission, no camera) the
  dialog says why and offers Upload; phones can also hand off to their own camera
  app (`capture="environment"`). The camera is always switched off on close,
  Escape, or leaving the screen.

`getUserMedia` only exists on **https or localhost**. Testing from a phone over a
plain `http://192.168.x.x` address falls back to the phone's camera app.

## Structure

```
index.html          shell: banner, screen slot, bottom nav
css/styles.css      design tokens (colors, radii, spacing) + components
js/config.js        API base URL, fallback location, mock switch
js/api.js           fetch wrapper, bearer token, mock fallback
js/mock.js          placeholder JSON matching backend/schemas.py
js/router.js        hash router with in-memory params + auth guards
js/ui.js            esc(), toast, badges, helpers
js/photo.js         photo box: upload / camera, preview, retake (re-exported by ui.js)
js/app.js           route table + bottom nav
js/screens/*.js     one file per screen
```

Two conventions worth keeping:

- **Everything user-controlled goes through `esc()`** before it touches
  `innerHTML`. Org names, descriptions and report text all come from third
  parties or other users.
- **Route params are held in memory, not the URL.** A score result carries a
  base64 photo and would blow past URL length limits. A refresh lands on the
  route's default state.

## Known mismatch with the Figma

The Figma profile screen shows tiers at **Bronze 500 / Silver 1,500 / Gold
2,500** and deeds worth +180. The shared contract says **Bronze 0–99 / Silver
100–499 / Gold 500+**, and the agent caps a submission at 100 points. The
backend implements the contract.

The UI renders whatever the backend returns (`tier`, `tier_points`,
`points_to_next_tier`) rather than hardcoding either scale, so it stays
correct if the economy is retuned. Only the static "Bronze 0 / Silver 100 /
Gold 500" labels under the profile progress bar would need editing.
