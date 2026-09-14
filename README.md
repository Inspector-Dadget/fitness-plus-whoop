# Whoop Workout Formatter

A static page that turns [Apple Fitness+](https://fitness.apple.com) workouts into the text Whoop wants for Strength Trainer.

Unofficial, not affiliated with Apple or Whoop. Code is [AGPL-3.0](LICENSE). Move lists come from the public [Weekly Workouts SeaTable](https://cloud.seatable.io/dtable/external-links/d08506897d274835bdab/?tid=1vDI&vid=0000).

Use it at https://inspector-dadget.github.io/fitness-plus-whoop/ or locally:

```bash
python3 -m http.server 8080
```

Pick a catalog workout or paste a Fitness+ link, enter Light / Medium / Heavy dumbbell weights, then generate. Serve over HTTP so the page can load `data/`. Weights stay in this browser.

## Catalog

[`scripts/refresh_catalog.py`](scripts/refresh_catalog.py) pulls SeaTable into `data/*.jsonl`. A GitHub Action runs that every Monday and on demand. The page uses the snapshot first and only talks to SeaTable if those files are missing.

Fill gaps in [`data/overrides.jsonl`](data/overrides.jsonl) (Apple ID, a blank field, or a workout SeaTable never had). Rows still missing an ID are listed in [`data/missing.jsonl`](data/missing.jsonl).

```json
{"table":"Strength","Trainer":"Gregg","Ep":145,"appleId":"1773439426"}
```

## Whoop names

[`data/whoop-exercises.json`](data/whoop-exercises.json) maps each SeaTable phrase to one name from the Whoop library. Empty values are unassigned. Rebuild with `python3 scripts/build_whoop_rules.py`.
