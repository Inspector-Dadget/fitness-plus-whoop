# Whoop Workout Formatter

A single static page that turns [Apple Fitness+](https://fitness.apple.com) workout links into the plain-text format Whoop wants for Strength Trainer sessions.

It matches the workout in a stored SeaTable catalog, then fills in the dumbbell weights you enter.

This project is unofficial and is not affiliated with Apple or Whoop. The formatter code is [AGPL-3.0](LICENSE). Catalog rows come from the public [Weekly Workouts SeaTable](https://cloud.seatable.io/dtable/external-links/d08506897d274835bdab/?tid=1vDI&vid=0000).

## Use it

No build step is required. After the repo is on GitHub, turn on Pages:

1. **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` (or `master`), folder: `/ (root)`
4. Open `https://<user>.github.io/<repo>/`

Locally: open `index.html`, or serve the folder (`python3 -m http.server 8080`). Paste a Fitness+ workout link, enter Light / Medium / Heavy dumbbell weights, then **Generate Whoop text**.

Serving over HTTP is more reliable than `file://` because the page loads the matching JSONL from `data/`. Weights stay in `localStorage`.

## Catalog

[`scripts/refresh_catalog.py`](scripts/refresh_catalog.py) pulls the public [Weekly Workouts SeaTable](https://cloud.seatable.io/dtable/external-links/d08506897d274835bdab/?tid=1vDI&vid=0000), writes one JSONL file per workout type (`data/strength.jsonl`, `data/core.jsonl`, …), and audits gaps in [`data/audit.md`](data/audit.md).

The refresh step also fills what it can:

- Apple workout IDs copied out of existing `Link` values
- IDs discovered from Wayback / Common Crawl (`scripts/harvest_apple_ids.py` → [`data/discovered-urls.jsonl`](data/discovered-urls.jsonl))
- A `Format` string inferred from `Detailed Moves` when SeaTable left it blank
- Manual additions from [`data/overrides.jsonl`](data/overrides.jsonl)

Rows that still have no Apple ID are listed in [`data/missing.jsonl`](data/missing.jsonl). Add an `appleId` (or `Link`) to a line and move it into `overrides.jsonl` to fill it on the next refresh.

There is no public Fitness+ search or catalog API. iTunes lookup does not index these workouts, and Apple’s Fitness API is authenticated. The Weekly Workouts SeaTable is the public index; its `Link` column mostly stopped in 2023. That is why most recent rows have no Apple ID, and why we cannot invent move lists or per-move weights from the web.

What we can add:

1. Add a line to `data/overrides.jsonl` to attach an ID, fill a blank field, or insert a workout SeaTable never had:

```json
{"table":"Strength","Trainer":"Gregg","Ep":145,"appleId":"1773439426"}
{"table":"Strength","Trainer":"Gregg","Date":"2026-08-24","Duration":"20 min","appleId":"1885659281","Detailed Moves":"1. Goblet squat\n2. Row"}
```

Unmatched override objects are appended as extra rows.

2. After you generate from a link, this browser remembers the Apple ID in `localStorage` and reuses it on the next match.

A GitHub Action runs that script every Monday and on demand, then commits catalog changes.

```bash
python3 scripts/refresh_catalog.py
```

The page uses the snapshot first and only talks to SeaTable live if the catalog is missing.

## How lookup works

1. The page reads the workout type and trainer from the Fitness+ URL.
2. It tries to load Apple’s page (via a public CORS proxy) for release date, duration, and description.
3. It matches that against the local catalog (Apple ID, then trainer + date + duration).
4. If more than one row looks plausible, you pick the episode.

Strength rows have the richest move scripts. Core, HIIT, and other types fall back to move lists when a full script is missing. When a script has no light/medium/heavy tags, the page infers Light vs Heavy from the movement type.

Move names are mapped to the Whoop Strength Trainer library in [`data/whoop-exercises.json`](data/whoop-exercises.json). `rules` is each SeaTable phrase → one Whoop name from `names`. Empty values are seen but not assigned yet. Rebuild with `python3 scripts/build_whoop_rules.py`.

## Hosting

GitHub Pages should serve `index.html` and `data/*.jsonl` from the repo root. Include `.nojekyll` so Jekyll does not skip files. The Monday catalog refresh Action commits into the same branch, so Pages updates with the catalog.

When you create the GitHub repo, leave it empty (no README/license from the website wizard) so this folder is the first commit. Do not add a second license in the create-repo form.
