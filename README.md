# GoodDeed Go — AI agent layer

This is the AI half of GoodDeed Go: opportunity discovery, submission scoring,
organization trust checks, and community-report triage. It is a plain Python
package with four public functions. There is no server here unless you want one.

**It runs with zero API keys.** Without credentials every external call is
served by a deterministic stub, so you can build the backend and the UI against
real-shaped data today and flip to live APIs by exporting two environment
variables. Nothing about the call signatures or return shapes changes.

## Quick start

```bash
pip install -r requirements.txt
python -m gooddeed_agent            # demo, prints exactly what the backend receives
pytest -q                           # 160 tests, no network, no keys
```

```python
from gooddeed_agent import find_opportunities, score_submission, trust_check, classify_report

quests = find_opportunities(lat=39.2904, lng=-76.6122, radius_km=5)
score  = score_submission(photo, description, org_name="Riverside Food Bank", time_spent_minutes=90)
trust  = trust_check("Riverside Food Bank", "1 Maple Ave, Baltimore MD")
triage = classify_report(photo, "Overflowing trash bins at 3rd and Maple")
```

## The four functions

### `find_opportunities(lat, lng, radius_km=5.0, **opts) -> list[dict]`

Searches Google Places around a point and returns Opportunity dicts, highest
legitimacy first.

```json
{"org_name": "Riverside Community Food Bank", "address": "2625 Maple Ave",
 "lat": 39.3359, "lng": -76.6165, "category": "food_bank",
 "legitimacy_score": 0.85, "quest_type": "daily"}
```

Useful options: `max_results` (default 20), `min_legitimacy` (default 0.4,
filters the list), `queries` (override the nonprofit search terms), and
`verify=True` / `max_verify=5` to run real web-search trust checks on the top
results. **`verify` is off by default** — it costs one LLM call per org, so use
it on a periodic map refresh, not on every pan of the viewport.

`include_description=True` adds a `description` key with the one-line
web-search summary of the org (needs `verify=True` to be populated). It's
opt-in so the default return value matches the seven-field Opportunity
contract exactly.

#### Search breadth

Discovery covers 15 philanthropic domains — food, housing, animals,
environment, health, seniors, youth/education, crisis, veterans, disability,
immigrant services, goods, community, disaster, arts — as 54 queries in
`QUERY_PACKS`.

```python
find_opportunities(lat, lng, 5)                          # 18-query default
find_opportunities(lat, lng, 5, packs=["food", "crisis"])  # one or more domains
find_opportunities(lat, lng, 5, packs=["all"], max_queries=60)  # everything
find_opportunities(lat, lng, 5, queries=["beach cleanup"])      # your own
```

Results are **interleaved across categories** by default, so the map shows a
mix rather than 20 food banks — a strict legitimacy sort buries every smaller
category. Repeat org names are pushed later within a category too, so one
thrift chain's four branches don't take every slot (all four are still
returned; they're separate map pins). Pass `diversify=False` for a pure
legitimacy ranking.

**Each query is one billed Places request.** The default fan-out takes the
broadest one or two queries from every domain; `packs=["all"]` roughly triples
the cost per refresh. `max_queries` (default 24) is the guard — raise it
deliberately. Queries run concurrently (8 at a time), so 18 queries take about
as long as 3, and results stay deterministic regardless of completion order.

A Places failure returns `[]` rather than raising.

### `score_submission(photo, description, org_name, time_spent_minutes, **opts) -> dict`

Sends the photo and text to Claude, then converts the verdict into points.

```json
{"points": 36, "tier_points": 36, "authenticity_confidence": 0.92,
 "rationale": "The photo shows donation crates being sorted, matching your description."}
```

`photo` accepts a URL, a file path, raw `bytes`, or a base64 / `data:` string —
whatever is easiest on your side.

Two options worth knowing:
- **`category="food_bank"`** — pass it if you have it. It sets the base points;
  without it the model guesses, which is less reliable.
- **`quest_multiplier=1.5`** — applies to `points` only, never `tier_points`.

`include_debug=True` adds a `debug` key with the model's full assessment
(sub-judgments, category used, minutes counted). Leave it off in production.

### `trust_check(org_name, address) -> dict`

Web-searches the org and summarizes the evidence. Gates which orgs become quests.

```json
{"legit": true, "confidence": 0.88, "summary": "Registered 501(c)(3), active site, accepts walk-in volunteers Saturdays."}
```

**`confidence: 0.0` means "couldn't check", not "it's fake."** A lookup failure
returns `legit: false, confidence: 0.0`. Branch on confidence before you treat
`legit: false` as a verdict.

### `classify_report(photo, description="") -> dict`

Triages a community "needs fixing" photo.

```json
{"category": "litter", "is_valid": true, "confidence": 0.91,
 "reason": "Clear photo of bagged trash on a public sidewalk."}
```

`category` is one of: `litter`, `illegal_dumping`, `graffiti`,
`broken_infrastructure`, `overgrowth`, `hazard`, `abandoned_item`, `other`.
`confidence` and `reason` are extra — ignore them if you don't need them.

`is_valid: false` covers spam, memes, screenshots, "nothing wrong here", privacy
problems (an identifiable face or plate as the subject), and anything needing
emergency services rather than volunteers. **A failure also returns
`is_valid: false`**, so nothing unreviewed reaches the public feed.

## Passing stored records straight in

Your `Submission` record calls it `photo_url`; `score_submission` takes `photo`.
Rather than unpack that by hand every time, pass the record:

```python
from gooddeed_agent import score_submission_from_dict, classify_report_from_dict

score  = score_submission_from_dict(submission_row, category="food_bank")
triage = classify_report_from_dict(report_row)
```

Both accept a plain dict or the matching dataclass, ignore extra keys your
table adds, and forward every keyword option. `Submission` and
`CommunityReport` are also importable if you want the shapes as dataclasses —
their fields are asserted against the contract in `tests/test_contract.py`.

## Scoring, tiers, and leaderboards (for the backend)

`gooddeed_agent.scoring` is pure math — no network, no LLM, no API key. Call it
directly for tier logic instead of reimplementing it:

```python
from gooddeed_agent import tier_for_points, points_to_next_tier, leaderboard, compute_points

tier_for_points(340)            # "Silver"
points_to_next_tier(340)        # 160
leaderboard([("u1", 90), ("u2", 120)])   # ranked, ties share a rank
```

The formula, in words: **base points for the category, plus one point per 10
minutes (capped at 30), scaled by authenticity confidence, capped at 100 per
submission.** Anything under `MIN_AUTHENTICITY` (0.45) scores zero.

Base points run 15–35 by category (`CATEGORY_BASE_POINTS`); shelter and
healthcare work is worth more than dropping off a bag at a thrift store. Tiers
are the contract's: Bronze 0–99, Silver 100–499, Gold 500+.

**`points` vs `tier_points`:** `points` goes on the daily/weekly leaderboards
and includes the quest multiplier. `tier_points` is the slice that counts toward
the cumulative Bronze/Silver/Gold total and deliberately excludes multipliers,
so a bonus weekend can't fast-track someone to Gold. With the default multiplier
of 1.0 they are equal.

All of this is tunable in one place: the constants at the top of
`gooddeed_agent/scoring.py`.

## HTTP wrapper (optional)

If the backend isn't Python, or wants process isolation:

```bash
pip install fastapi uvicorn python-multipart
uvicorn gooddeed_agent.service:app --reload --port 8100
```

| Method | Path | Returns |
|---|---|---|
| `GET`  | `/health` | Status **and which providers are live vs mocked** |
| `POST` | `/opportunities` | `{"opportunities": [Opportunity, ...]}` |
| `POST` | `/score` | Score result (photo as URL or base64) |
| `POST` | `/score/upload` | Score result (multipart file upload) |
| `POST` | `/trust` | `{legit, confidence, summary}` |
| `POST` | `/reports/classify` | `{category, is_valid, confidence, reason}` |
| `POST` | `/reports/classify/upload` | Same, multipart |
| `GET`  | `/tier/{points}` | `{tier, tier_points, points_to_next_tier}` |

Interactive docs at `http://localhost:8100/docs`.

If you're calling from Python, **skip this and import the functions directly** —
it's one less process to keep running during the demo.

## Going live

```bash
cp .env.example .env     # then fill in the two keys, no quotes needed
```

`.env` is loaded automatically (it needs `python-dotenv`, which is in
`requirements.txt`). Exported environment variables take precedence over the
file. `.env` is gitignored — never commit it.

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables real Claude calls (scoring, trust, triage) |
| `GOOGLE_MAPS_API_KEY` | Enables real Places search. Needs **Places API (New)** enabled |
| `GOODDEED_USE_MOCKS=1` | Forces stubs even with keys present |
| `GOODDEED_MODEL` | Model override (default `claude-opus-5`) |

The two keys are independent: real Places with a mocked LLM works fine.
`GET /health` or the `python -m gooddeed_agent` header tells you which mode
each provider is in — check there first when output looks like stub text
(the mocks label themselves `[mock]`).

## Design notes

**Authenticity, never impact.** The scoring prompt judges whether the photo
plausibly shows the described deed at the named org, how specific the write-up
is, and whether the claimed time is believable. It is explicitly instructed not
to estimate real-world impact — that isn't visible in a photo, and rewarding
guesses at it would just teach users to write better captions.

**Failures degrade, they don't raise.** Every agent function catches provider
errors and returns a valid, zero-value result with an explanatory string. A
Claude outage should queue a submission for retry, not 500 the app. The one
place this is asymmetric is `classify_report`: failures return `is_valid: false`
so nothing unreviewed reaches the public feed.

**Everything external sits behind a provider.** `PlacesProvider` and
`LLMProvider` (in `providers/base.py`) are the only seams to the outside world.
Every agent function takes optional `places=` / `llm=` arguments, which is how
the tests run with no network and how you'd stub one service while the other
stays live.

**Text queries, not Places types.** The Places taxonomy has no reliable
"nonprofit" type, so discovery fans out a list of text queries ("food bank",
"animal shelter", …) biased to a circle around the user, then dedupes. The
query an org was found by is also the strongest signal for its category.

## Layout

```
gooddeed_agent/
  discovery.py       find_opportunities, trust_check
  vision.py          score_submission, classify_report
  scoring.py         pure points/tier/leaderboard math — no network
  models.py          contract dataclasses
  config.py          env settings, mock fallback
  service.py         optional FastAPI app
  __main__.py        python -m gooddeed_agent demo
  providers/
    base.py          PlacesProvider / LLMProvider protocols
    google_places.py Places API (New)
    claude_llm.py    Claude vision + web search + structured output
    mock.py          deterministic stubs
tests/               160 tests, no network required
```
