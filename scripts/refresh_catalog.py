#!/usr/bin/env python3
"""Pull the public Weekly Workouts SeaTable into per-type JSONL files and audit gaps."""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SEATABLE_LINK = "d08506897d274835bdab"
TABLES = [
    "Strength",
    "Core",
    "HIIT",
    "Pilates",
    "Kickboxing",
]
KEEP = {
    "_id",
    "Name",
    "Date",
    "Duration",
    "Trainer",
    "Guest",
    "Ep",
    "Music",
    "Body Focus",
    "Format",
    "Format Details",
    "Dumbbells",
    "Equipment",
    "Link",
    "Detailed Moves",
    "WIP-Moves",
    "Workout Details",
    "Stretches",
    "Types of Moves",
    "Moves",
    "Floor Exercises",
    "Strength Exercises",
    "Conditioning Exercises",
    "Strikes",
    "Description",
}
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_META = DATA_DIR / "meta.json"
OUT_AUDIT = DATA_DIR / "audit.md"
OUT_OVERRIDES = DATA_DIR / "overrides.jsonl"
OUT_DISCOVERED = DATA_DIR / "discovered-urls.jsonl"
OUT_MISSING = DATA_DIR / "missing.jsonl"
MISSING_FIELDS = ("table", "_id", "Name", "Trainer", "Date", "Duration", "Ep", "Music", "Body Focus")
HTTP_TIMEOUT = 30


def jsonl_dumps(rows: list[dict]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        for row in rows
    )


def table_slug(table: str) -> str:
    return table.lower().replace(" ", "-")


def table_path(table: str) -> Path:
    return DATA_DIR / f"{table_slug(table)}.jsonl"


def seatable_auth() -> tuple[str, str]:
    html = urllib.request.urlopen(
        f"https://cloud.seatable.io/dtable/external-links/{SEATABLE_LINK}/",
        timeout=HTTP_TIMEOUT,
    ).read().decode()
    token = re.search(r"accessToken:\s*'([^']+)'", html)
    uuid = re.search(r"dtableUuid:\s*'([^']+)'", html)
    if not token or not uuid:
        raise RuntimeError("Could not read SeaTable access token from the public base")
    return token.group(1), uuid.group(1)


def seatable_sql(token: str, uuid: str, sql: str) -> list[dict]:
    body = json.dumps({"sql": sql, "convert_keys": True}).encode()
    req = urllib.request.Request(
        f"https://cloud.seatable.io/api-gateway/api/v2/dtables/{uuid}/sql/",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    data = json.load(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT))
    if not data.get("success"):
        raise RuntimeError(data.get("error_message") or "SeaTable query error")
    return data.get("results") or []


def date_only(value) -> str:
    if not value:
        return ""
    return str(value)[:10]


def duration_label_from_ms(ms) -> str:
    try:
        minutes = float(ms) / 60000
    except (TypeError, ValueError):
        return ""
    best = 30
    best_diff = float("inf")
    for option in (5, 10, 20, 30, 45, 60):
        diff = abs(minutes - option)
        if diff < best_diff:
            best = option
            best_diff = diff
    return f"{best} min"


def normalize_trainer(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def trainers_match(row_trainer, discovered_trainer) -> bool:
    left = normalize_trainer(row_trainer)
    right = normalize_trainer(discovered_trainer)
    return bool(left and right and left == right)


def apple_id_from_link(link) -> str | None:
    if not link:
        return None
    match = re.search(r"/workout/[^/]+/(\d+)", str(link))
    return match.group(1) if match else None


def move_source(row: dict) -> str:
    return (
        row.get("Detailed Moves")
        or row.get("WIP-Moves")
        or row.get("Workout Details")
        or row.get("Stretches")
        or ""
    )


def infer_format(row: dict) -> str:
    if row.get("Format"):
        if isinstance(row["Format"], list):
            return " • ".join(str(part) for part in row["Format"] if part)
        return str(row["Format"])
    text = move_source(row)
    if not text:
        return ""
    block_ids = re.findall(r"^block\s+(\d+)", text, flags=re.I | re.M)
    move_lines = re.findall(r"^\d+[.)]\s+", text, flags=re.M)
    bits = []
    if move_lines:
        per_block = len(move_lines) // max(len(set(block_ids)), 1)
        bits.append(f"{per_block} moves" if per_block else f"{len(move_lines)} moves")
    if len(set(block_ids)) > 1:
        bits.append(f"{len(set(block_ids))} blocks")
    return " • ".join(bits)


def has_move_script(row: dict) -> bool:
    return bool(re.search(r"^\d+[.)]\s+", move_source(row), flags=re.M))


def has_per_move_weights(row: dict) -> bool:
    return bool(re.search(r"\b(light|medium|heavy)\b", move_source(row), flags=re.I))


def uses_dumbbells(row: dict) -> bool:
    equipment = " ".join(row.get("Equipment") or []).lower()
    if "dumbbell" in equipment:
        return True
    return any(not re.search(r"bodyweight", str(item), re.I) for item in (row.get("Dumbbells") or []))


def slim_row(row: dict) -> dict:
    out = {key: row.get(key) for key in KEEP if row.get(key) not in (None, "", [])}
    out["Date"] = date_only(row.get("Date"))
    if "Ep" in row and row["Ep"] not in (None, ""):
        try:
            out["Ep"] = int(row["Ep"])
        except (TypeError, ValueError):
            out["Ep"] = row["Ep"]
    apple_id = apple_id_from_link(row.get("Link"))
    if apple_id:
        out["appleId"] = apple_id
    inferred = infer_format(row)
    if inferred and not out.get("Format"):
        out["Format"] = inferred
    return out


def fetch_table(token: str, uuid: str, table: str) -> list[dict]:
    escaped = table.replace("`", "``")
    rows: list[dict] = []
    page_size = 800
    start = 0
    while True:
        chunk = seatable_sql(
            token,
            uuid,
            f"SELECT * FROM `{escaped}` LIMIT {page_size} OFFSET {start}",
        )
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        start += page_size
    return [slim_row(row) for row in rows]


def load_overrides() -> list[dict]:
    if not OUT_OVERRIDES.exists():
        return []
    rows = []
    for line in OUT_OVERRIDES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def rows_match(row: dict, override: dict) -> bool:
    if override.get("_id") and row.get("_id") == override["_id"]:
        return True
    if override.get("appleId") and row.get("appleId") == str(override["appleId"]):
        return True
    trainer = override.get("Trainer") or override.get("trainer")
    if trainer and (row.get("Trainer") or row.get("Guest")) != trainer:
        return False
    if override.get("Ep") not in (None, "") and row.get("Ep") not in (None, ""):
        try:
            return int(row["Ep"]) == int(override["Ep"])
        except (TypeError, ValueError):
            return False
    if override.get("Date") and date_only(row.get("Date")) == date_only(override["Date"]):
        if override.get("Duration") and row.get("Duration") != override["Duration"]:
            return False
        return True
    return False


def apply_overrides(tables: dict[str, list[dict]]) -> dict:
    stats = {"updated": 0, "added": 0}
    for override in load_overrides():
        table = override.get("table") or override.get("Table")
        if not table or table not in tables:
            continue
        payload = {key: value for key, value in override.items() if key not in {"table", "Table"}}
        if payload.get("Link") and not payload.get("appleId"):
            payload["appleId"] = apple_id_from_link(payload["Link"])
        if payload.get("Date"):
            payload["Date"] = date_only(payload["Date"])
        matched = next((row for row in tables[table] if rows_match(row, payload)), None)
        if matched:
            for key, value in payload.items():
                if value in (None, "", []):
                    continue
                if key in matched and matched[key] not in (None, "", []) and key != "appleId":
                    continue
                matched[key] = value
            stats["updated"] += 1
            continue
        payload["_id"] = payload.get("_id") or f"override-{payload.get('appleId') or stats['added'] + 1}"
        payload["source"] = "override"
        tables[table].append(payload)
        stats["added"] += 1
    return stats


def load_tables_from_jsonl() -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    for table in TABLES:
        path = table_path(table)
        if not path.exists():
            continue
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        tables[table] = rows
    return tables


def load_discovered() -> list[dict]:
    if not OUT_DISCOVERED.exists():
        return []
    rows = []
    for line in OUT_DISCOVERED.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def write_discovered(records: list[dict]) -> None:
    records = sorted(records, key=lambda item: (item.get("table") or "", item.get("trainer") or "", item.get("appleId") or ""))
    OUT_DISCOVERED.write_text(jsonl_dumps(records), encoding="utf-8")


def pick_discovered_match(candidates: list[dict], date: str, duration: str, episode) -> dict | None:
    if date:
        on_date = [row for row in candidates if date_only(row.get("Date")) == date]
        if duration:
            both = [row for row in on_date if row.get("Duration") == duration]
            if len(both) == 1:
                return both[0]
            if len(both) > 1:
                return None
        if len(on_date) == 1:
            return on_date[0]
        if len(on_date) > 1:
            return None
    if episode not in (None, "") and duration:
        by_ep = []
        for row in candidates:
            try:
                if int(row.get("Ep")) == int(episode) and row.get("Duration") == duration:
                    by_ep.append(row)
            except (TypeError, ValueError):
                pass
        if len(by_ep) == 1:
            return by_ep[0]
    return None


def apply_discovered(tables: dict[str, list[dict]], records: list[dict] | None = None) -> dict:
    records = records if records is not None else load_discovered()
    claimed = {
        str(row["appleId"])
        for rows in tables.values()
        for row in rows
        if row.get("appleId")
    }
    stats = {"updated": 0, "ambiguous": 0, "unmatched": 0}
    for record in records:
        table = record.get("table")
        apple_id = str(record.get("appleId") or "")
        if not table or table not in tables or not apple_id or apple_id in claimed:
            continue
        trainer = record.get("trainer")
        date = date_only(record.get("releaseDate"))
        duration = record.get("duration") or ""
        candidates = [
            row
            for row in tables[table]
            if not row.get("appleId") and trainers_match(row.get("Trainer"), trainer)
        ]
        match = pick_discovered_match(candidates, date, duration, record.get("episodeNumber"))
        if match:
            match["appleId"] = apple_id
            match["Link"] = record.get("url") or f"https://fitness.apple.com/us/workout/{record.get('slug')}/{apple_id}"
            claimed.add(apple_id)
            stats["updated"] += 1
        elif candidates:
            stats["ambiguous"] += 1
        else:
            stats["unmatched"] += 1
    return stats


def missing_rows(tables: dict[str, list[dict]]) -> list[dict]:
    rows = []
    for table, items in tables.items():
        for row in items:
            if row.get("appleId"):
                continue
            item = {key: row[key] for key in MISSING_FIELDS if key != "table" and row.get(key) not in (None, "", [])}
            item["table"] = table
            rows.append(item)
    table_order = {name: index for index, name in enumerate(TABLES)}
    rows.sort(
        key=lambda item: (
            table_order.get(item.get("table"), 99),
            item.get("Date") or "",
            item.get("Trainer") or "",
            item.get("Ep") if isinstance(item.get("Ep"), int) else 0,
        ),
        reverse=True,
    )
    rows.sort(key=lambda item: table_order.get(item.get("table"), 99))
    return rows


def write_missing(tables: dict[str, list[dict]]) -> list[dict]:
    rows = missing_rows(tables)
    OUT_MISSING.write_text(jsonl_dumps(rows), encoding="utf-8")
    return rows


def write_table_files(tables: dict[str, list[dict]]) -> dict[str, str]:
    files = {}
    for table, rows in tables.items():
        path = table_path(table)
        path.write_text(jsonl_dumps(rows), encoding="utf-8")
        files[table] = path.name
        print(f"Wrote {path} ({path.stat().st_size / 1024:.0f} KB, {len(rows)} rows)")
    return files


def audit(tables: dict[str, list[dict]]) -> str:
    lines = [
        "# Catalog audit",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "Inferred `Format` when SeaTable left it blank. Apple IDs come from `Link`, [`overrides.jsonl`](overrides.jsonl), and [`discovered-urls.jsonl`](discovered-urls.jsonl). Remaining gaps are in [`missing.jsonl`](missing.jsonl).",
        "",
        "| Table | Rows | With move script | Missing Apple ID | DBs but no per-move weight |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    details = []
    for table, rows in tables.items():
        script = sum(1 for row in rows if has_move_script(row))
        missing_id = [row for row in rows if not row.get("appleId")]
        db_no_weight = [
            row for row in rows
            if uses_dumbbells(row) and has_move_script(row) and not has_per_move_weights(row)
        ]
        lines.append(
            f"| {table} | {len(rows)} | {script} | {len(missing_id)} | {len(db_no_weight)} |"
        )
        recent_missing = [row for row in missing_id if (row.get("Date") or "") >= "2024-01-01"]
        if table in {"Strength", "Core", "HIIT"} and recent_missing:
            details.append(f"### {table}: recent rows without Apple ID")
            details.append("")
            for row in sorted(recent_missing, key=lambda item: item.get("Date") or "", reverse=True)[:12]:
                details.append(
                    f"- {row.get('Date') or '?'} — {row.get('Name') or 'Untitled'} ({row.get('Duration') or '?'})"
                )
            details.append("")
        if table == "Strength" and db_no_weight:
            details.append("### Strength: move scripts without light/medium/heavy tags")
            details.append("")
            for row in sorted(db_no_weight, key=lambda item: item.get("Date") or "", reverse=True)[:12]:
                details.append(
                    f"- {row.get('Date') or '?'} — {row.get('Name') or 'Untitled'}"
                )
            details.append("")
    if details:
        lines.extend(["", "## Highest-value gaps", ""])
        lines.extend(details)
    lines.append("The page infers Light vs Heavy from movement type when a script has no per-move tags.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    token, uuid = seatable_auth()
    tables: dict[str, list[dict]] = {}
    for table in TABLES:
        print(f"Fetching {table}...")
        rows = fetch_table(token, uuid, table)
        if not rows:
            raise RuntimeError(f"SeaTable returned no rows for {table}")
        tables[table] = rows
        print(f"  {len(rows)} rows")
    override_stats = apply_overrides(tables)
    print(f"Overrides: updated {override_stats['updated']}, added {override_stats['added']}")
    discovered_stats = apply_discovered(tables)
    print(
        f"Discovered URLs: updated {discovered_stats['updated']}, "
        f"ambiguous {discovered_stats['ambiguous']}, unmatched {discovered_stats['unmatched']}"
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stale = DATA_DIR / "catalog.json"
    if stale.exists():
        stale.unlink()
    files = write_table_files(tables)
    missing = write_missing(tables)
    print(f"Wrote {OUT_MISSING} ({len(missing)} rows still missing an Apple ID)")
    OUT_META.write_text(
        json.dumps(
            {
                "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": f"https://cloud.seatable.io/dtable/external-links/{SEATABLE_LINK}/",
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    OUT_AUDIT.write_text(audit(tables), encoding="utf-8")
    print(f"Wrote {OUT_META}")
    print(f"Wrote {OUT_AUDIT}")


if __name__ == "__main__":
    main()
