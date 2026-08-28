#!/usr/bin/env python3
"""Collect Fitness+ workout URLs from Wayback/Common Crawl and attach IDs we can match."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refresh_catalog as catalog

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}
WORKOUT_RE = re.compile(
    r"https?://fitness\.apple\.com/[a-z]{2}/workout/([^/?#]+)/(\d+)",
    re.I,
)
KIND_RE = re.compile(
    r"(?:absolute-beginner-|upper-body-|lower-body-|total-body-)?(strength|core|hiit|pilates|kickboxing)",
    re.I,
)
KIND_TABLE = {
    "strength": "Strength",
    "core": "Core",
    "hiit": "HIIT",
    "pilates": "Pilates",
    "kickboxing": "Kickboxing",
}
CC_INDEXES = (
    "CC-MAIN-2026-34",
    "CC-MAIN-2026-30",
    "CC-MAIN-2026-25",
    "CC-MAIN-2026-21",
    "CC-MAIN-2025-51",
    "CC-MAIN-2025-43",
    "CC-MAIN-2024-51",
)


def get(url: str, timeout: int = 70) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def trainer_from_slug(slug: str) -> str:
    cleaned = re.sub(r"-music-by-.+$", "", slug.lower())
    cleaned = re.sub(r"-week-\d+$", "", cleaned)
    match = re.search(r"-with-(.+)$", cleaned)
    if not match:
        return ""
    trainer = match.group(1).replace("-", " ").title()
    if trainer.lower() == "jamie ray":
        return "Jamie-Ray"
    return trainer


def parse_workout_url(url: str) -> dict | None:
    match = WORKOUT_RE.search(url.split("?")[0])
    if not match:
        return None
    slug = urllib.parse.unquote(match.group(1)).lower()
    kind = KIND_RE.search(slug)
    table = KIND_TABLE.get(kind.group(1).lower()) if kind else None
    if not table:
        return None
    apple_id = match.group(2)
    return {
        "appleId": apple_id,
        "url": f"https://fitness.apple.com/us/workout/{slug}/{apple_id}",
        "slug": slug,
        "table": table,
        "trainer": trainer_from_slug(slug),
    }


def merge_record(existing: dict, incoming: dict) -> dict:
    out = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", []) and (key not in out or out[key] in (None, "", [])):
            out[key] = value
    return out


def wayback_prefix(prefix: str) -> list[str]:
    query = urllib.parse.urlencode(
        {
            "url": prefix,
            "matchType": "prefix",
            "output": "json",
            "fl": "original",
            "collapse": "urlkey",
            "limit": "2000",
            "filter": "statuscode:200",
        }
    )
    raw = get("https://web.archive.org/cdx/search/cdx?" + query)
    rows = json.loads(raw)
    return [row[0] if isinstance(row, list) else row for row in rows[1:]]


def common_crawl_urls(pattern: str) -> list[str]:
    urls = []
    query = urllib.parse.urlencode(
        {
            "url": pattern,
            "output": "json",
            "filter": "status:200",
            "limit": "2000",
        }
    )
    for index in CC_INDEXES:
        try:
            raw = get(f"https://index.commoncrawl.org/{index}-index?" + query, timeout=90)
        except Exception:
            continue
        for line in raw.decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("url"):
                urls.append(obj["url"])
    return urls


def harvest_prefixes() -> list[str]:
    prefixes = []
    for kind in KIND_TABLE:
        prefixes.append(f"fitness.apple.com/us/workout/{kind}-with-")
        prefixes.append(f"fitness.apple.com/us/workout/absolute-beginner-{kind}-with-")
        prefixes.append(f"fitness.apple.com/us/workout/upper-body-{kind}-with-")
        prefixes.append(f"fitness.apple.com/us/workout/lower-body-{kind}-with-")
        prefixes.append(f"fitness.apple.com/us/workout/total-body-{kind}-with-")
    tables = catalog.load_tables_from_jsonl()
    for table, rows in tables.items():
        slug = catalog.table_slug(table)
        trainers = {row.get("Trainer") for row in rows if row.get("Trainer")}
        for trainer in trainers:
            trainer_slug = str(trainer).lower().replace(" ", "-")
            prefixes.append(f"fitness.apple.com/us/workout/{slug}-with-{trainer_slug}/")
    return prefixes


def collect_urls() -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for record in catalog.load_discovered():
        apple_id = str(record.get("appleId") or "")
        if apple_id:
            by_id[apple_id] = record

    prefixes = harvest_prefixes()
    print(f"Querying Wayback for {len(prefixes)} prefixes...")
    for prefix in prefixes:
        try:
            urls = wayback_prefix(prefix)
        except Exception as error:
            print(f"  wayback skip {prefix}: {error}")
            continue
        added = 0
        for url in urls:
            parsed = parse_workout_url(url)
            if not parsed:
                continue
            apple_id = parsed["appleId"]
            by_id[apple_id] = merge_record(by_id.get(apple_id, {}), parsed)
            added += 1
        if added:
            print(f"  {prefix} -> {added}")

    print("Querying Common Crawl...")
    for kind in KIND_TABLE:
        urls = common_crawl_urls(f"fitness.apple.com/us/workout/{kind}-with-*")
        added = 0
        for url in urls:
            parsed = parse_workout_url(url)
            if not parsed:
                continue
            apple_id = parsed["appleId"]
            by_id[apple_id] = merge_record(by_id.get(apple_id, {}), parsed)
            added += 1
        print(f"  {kind}-with-* -> {added}")
    return by_id


def parse_apple_html(html: str, fallback: dict) -> dict:
    match = re.search(
        r'<script type="fastboot/shoebox" id="shoebox-media-api-cache-amp-fitness">([\s\S]*?)</script>',
        html,
    )
    if not match:
        raise ValueError("no shoebox")
    raw = match.group(1)
    try:
        cache = json.loads(raw)
    except json.JSONDecodeError:
        cache = json.loads(
            raw.replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&")
        )
    first = json.loads(next(iter(cache.values())))
    item = (first.get("d") or [None])[0] or {}
    attrs = item.get("attributes") or {}
    name = attrs.get("name") or ""
    with_match = re.search(r"\bwith\s+(.+)$", name, flags=re.I)
    return {
        **fallback,
        "name": name,
        "trainer": (with_match.group(1) if with_match else fallback.get("trainer") or ""),
        "releaseDate": catalog.date_only(attrs.get("releaseDate")),
        "duration": catalog.duration_label_from_ms(attrs.get("durationInMilliseconds")),
        "episodeNumber": attrs.get("episodeNumber"),
    }


def fetch_metadata(record: dict) -> dict | None:
    url = record.get("url")
    if not url:
        return None
    try:
        html = get(url, timeout=25).decode("utf-8", "replace")
        return parse_apple_html(html, record)
    except Exception:
        return None


def catalog_ids(tables: dict[str, list[dict]]) -> set[str]:
    return {
        str(row["appleId"])
        for rows in tables.values()
        for row in rows
        if row.get("appleId")
    }


def fill_metadata(by_id: dict[str, dict], known_ids: set[str]) -> None:
    pending = [
        record
        for apple_id, record in by_id.items()
        if apple_id not in known_ids and not record.get("releaseDate")
    ]
    print(f"Fetching Apple metadata for {len(pending)} new IDs...")
    if not pending:
        return
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_metadata, record): record["appleId"] for record in pending}
        for future in as_completed(futures):
            apple_id = futures[future]
            done += 1
            try:
                updated = future.result()
            except Exception:
                updated = None
            if updated:
                by_id[apple_id] = merge_record(by_id[apple_id], updated)
            if done % 25 == 0 or done == len(pending):
                catalog.write_discovered(list(by_id.values()))
                print(f"  {done}/{len(pending)}")


def main() -> None:
    catalog.DATA_DIR.mkdir(parents=True, exist_ok=True)
    by_id = collect_urls()
    print(f"Collected {len(by_id)} unique workout IDs")
    tables = catalog.load_tables_from_jsonl()
    fill_metadata(by_id, catalog_ids(tables))
    catalog.write_discovered(list(by_id.values()))
    print(f"Wrote {catalog.OUT_DISCOVERED}")
    stats = catalog.apply_discovered(tables, list(by_id.values()))
    print(
        f"Matched {stats['updated']} catalog rows "
        f"({stats['ambiguous']} ambiguous, {stats['unmatched']} unmatched)"
    )
    catalog.write_table_files(tables)
    missing = catalog.write_missing(tables)
    print(f"Wrote {catalog.OUT_MISSING} ({len(missing)} rows still missing an Apple ID)")
    catalog.OUT_AUDIT.write_text(catalog.audit(tables), encoding="utf-8")
    print(f"Wrote {catalog.OUT_AUDIT}")


if __name__ == "__main__":
    main()
