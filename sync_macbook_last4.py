#!/usr/bin/env python3
"""
Check and sync last4.csv with MacBook-only Apple configuration codes.

Sources (in priority order for names):
  1. Apple support-sp product API  (authoritative when available)
  2. Existing last4.csv            (kept when Apple no longer knows the code)
  3. Community model_snippets.json (pudquick / krypted)
  4. Sibling OpenCore model codes  (fill gaps using same MacBook* model id)

Candidate codes come from:
  - OpenCorePkg macserial modelinfo (MacBook / MacBookAir / MacBookPro only)
  - Community snippets (MacBook* names only)
  - Current last4.csv

Only products whose marketing name starts with "MacBook" are kept
(MacBook, MacBook Air, MacBook Pro). iMac, Mac Pro, Mac mini, iPad, etc. are dropped.

Usage:
  python3 sync_macbook_last4.py --check
  python3 sync_macbook_last4.py --sync
  python3 sync_macbook_last4.py --sync --verify-all
  python3 sync_macbook_last4.py --lookup Q6LC
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "last4.csv"
CACHE_PATH = ROOT / ".last4_apple_cache.json"

OPENCORE_MODELINFO_URL = (
    "https://raw.githubusercontent.com/acidanthera/OpenCorePkg/"
    "master/Utilities/macserial/modelinfo_autogen.h"
)
SNIPPETS_URLS = [
    "https://raw.githubusercontent.com/pudquick/pyMacWarranty/master/model_snippets.json",
    "https://raw.githubusercontent.com/krypted/swiftwarrantylookup/"
    "master/src/swiftMacWarranty/model_snippets.json",
]
APPLE_PRODUCT_URL = "https://support-sp.apple.com/sp/product?cc={cc}"

# OpenCore comment labels look like MacBookPro16,1
MACBOOK_MODEL_RE = re.compile(r"^MacBook(?:Air|Pro)?\d+,\d+$")
CODE_RE = re.compile(r'"([A-Z0-9]{3,4})"')
# Only the AppleModelCode table — AppleBoardCode uses "0000" placeholders.
MODEL_CODE_TABLE_RE = re.compile(
    r"static const char \*AppleModelCode\[\]\[.*?\]\s*=\s*\{(.*?)\n\};",
    re.S,
)
BLOCK_RE = re.compile(
    r"/\*\s*(MacBook(?:Air|Pro)?\d+,\d+)\s*\*/\s*\{([^}]+)\}"
)
CONFIG_CODE_RE = re.compile(r"<configCode>(.*?)</configCode>", re.I | re.S)
ERROR_RE = re.compile(r"<error>(.*?)</error>", re.I | re.S)

# OpenCore / Apple placeholders and unusable marketing stubs
PLACEHOLDER_CODES = {"0000", "000"}
VAGUE_NAMES = {
    "MacBook",
    "MacBook Air",
    "MacBook Pro",
}

USER_AGENT = "MeepoScan-last4-sync/1.0"
SSL_CTX = ssl.create_default_context()


def is_macbook_name(name: str | None) -> bool:
    return bool(name) and name.startswith("MacBook")


def is_specific_name(name: str | None) -> bool:
    """True when the marketing name includes a useful model detail."""
    return (
        is_macbook_name(name)
        and name not in VAGUE_NAMES
        and "(" in name
    )


def name_quality(name: str | None) -> int:
    """Higher is better — used when merging conflicting sources."""
    if not is_macbook_name(name):
        return -1
    if name in VAGUE_NAMES or "(" not in name:
        return 0
    return 10 + len(name)


def http_get(url: str, timeout: float = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_csv(path: Path) -> dict[str, str]:
    """Load code -> model name. Later duplicate rows overwrite earlier ones."""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 2:
                continue
            code = row[0].strip().upper()
            name = row[1].strip()
            if code:
                data[code] = name
    return data


def write_csv(path: Path, data: dict[str, str]) -> None:
    rows = sorted(data.items(), key=lambda kv: kv[0])
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        for code, name in rows:
            writer.writerow([code, name])
    tmp.replace(path)


def load_cache(path: Path) -> dict[str, str | None]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Normalize: missing -> None sentinel stored as null
        return {str(k).upper(): (v if v is None else str(v)) for k, v in raw.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(path: Path, cache: dict[str, str | None]) -> None:
    path.write_text(json.dumps(cache, indent=0, sort_keys=True) + "\n", encoding="utf-8")


def fetch_opencore_macbook_codes() -> dict[str, str]:
    """Return {config_code: OpenCore model id} for MacBook* only, 4-char codes."""
    text = http_get(OPENCORE_MODELINFO_URL)
    table = MODEL_CODE_TABLE_RE.search(text)
    if not table:
        raise RuntimeError("AppleModelCode table not found in OpenCore modelinfo")
    mapping: dict[str, str] = {}
    for model, body in BLOCK_RE.findall(table.group(1)):
        if not MACBOOK_MODEL_RE.match(model):
            continue
        for code in CODE_RE.findall(body):
            if len(code) != 4 or code in PLACEHOLDER_CODES:
                continue
            # Prefer first model assignment if a code appears more than once
            mapping.setdefault(code, model)
    return mapping


def fetch_snippets_macbook() -> dict[str, str]:
    last_err: Exception | None = None
    for url in SNIPPETS_URLS:
        try:
            raw = json.loads(http_get(url))
            return {
                str(k).upper(): str(v).strip()
                for k, v in raw.items()
                if len(str(k)) == 4 and is_macbook_name(str(v).strip())
            }
        except Exception as exc:  # noqa: BLE001 - try next mirror
            last_err = exc
    raise RuntimeError(f"Failed to fetch model snippets: {last_err}")


def apple_lookup(cc: str) -> str | None:
    """Return marketing name from Apple, or None if unknown/error."""
    url = APPLE_PRODUCT_URL.format(cc=cc)
    try:
        text = http_get(url, timeout=15)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    match = CONFIG_CODE_RE.search(text)
    if match:
        return match.group(1).strip()
    return None


def lookup_many(
    codes: list[str],
    cache: dict[str, str | None],
    workers: int = 16,
    force: bool = False,
) -> dict[str, str | None]:
    pending = [c for c in codes if force or c not in cache]
    if not pending:
        return {c: cache.get(c) for c in codes}

    print(f"Looking up {len(pending)} codes via Apple API ({workers} workers)...")
    done = 0
    t0 = time.time()

    def work(code: str) -> tuple[str, str | None]:
        return code, apple_lookup(code)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, c) for c in pending]
        for fut in as_completed(futures):
            code, name = fut.result()
            cache[code] = name
            done += 1
            if done % 100 == 0 or done == len(pending):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed else 0
                print(f"  {done}/{len(pending)} ({rate:.1f}/s)")

    save_cache(CACHE_PATH, cache)
    return {c: cache.get(c) for c in codes}


def prefer_name(current: str | None, candidate: str | None) -> str | None:
    """Keep the higher-quality MacBook marketing name."""
    if name_quality(candidate) > name_quality(current):
        return candidate
    return current


def sibling_names(
    opencore: dict[str, str],
    known: dict[str, str],
) -> dict[str, str]:
    """
    For each OpenCore model id, if siblings share exactly one specific MacBook
    marketing name, reuse it for codes that still lack a name.
    Conflicting models (Mid 2013 vs Early 2014, etc.) are skipped.
    """
    by_model: dict[str, list[str]] = {}
    for code, model in opencore.items():
        by_model.setdefault(model, []).append(code)

    model_name: dict[str, str] = {}
    for model, codes in by_model.items():
        names = {
            known[c]
            for c in codes
            if c in known and is_specific_name(known[c])
        }
        if len(names) == 1:
            model_name[model] = next(iter(names))

    filled: dict[str, str] = {}
    for model, codes in by_model.items():
        name = model_name.get(model)
        if not name:
            continue
        for code in codes:
            if code not in known:
                filled[code] = name
    return filled


def build_desired(
    local: dict[str, str],
    snippets: dict[str, str],
    opencore: dict[str, str],
    apple: dict[str, str | None],
    use_siblings: bool = True,
) -> tuple[dict[str, str], dict]:
    """
    Merge sources into the desired MacBook-only map.
    Returns (desired_map, stats).
    """
    known: dict[str, str] = {}

    def absorb(code: str, name: str | None) -> None:
        if code in PLACEHOLDER_CODES or not is_macbook_name(name):
            return
        chosen = prefer_name(known.get(code), name)
        if chosen:
            known[code] = chosen

    for code, name in snippets.items():
        absorb(code, name)
    for code, name in local.items():
        absorb(code, name)

    apple_macbook = 0
    apple_non_macbook = 0
    apple_miss = 0
    apple_vague = 0
    for code, name in apple.items():
        if name is None:
            apple_miss += 1
            continue
        if not is_macbook_name(name):
            apple_non_macbook += 1
            # Apple says this config is not a MacBook — drop it.
            known.pop(code, None)
            continue
        if not is_specific_name(name):
            apple_vague += 1
            # Only keep vague Apple names if we have nothing better.
            absorb(code, name)
            continue
        absorb(code, name)
        apple_macbook += 1

    sibling_fill = sibling_names(opencore, known) if use_siblings else {}
    if use_siblings:
        for code, name in sibling_fill.items():
            absorb(code, name)

    # Final filter: specific MacBook names preferred; allow rare vague only if
    # that is all Apple/local ever had (e.g. FLCF -> "MacBook Air").
    desired = {
        code: name
        for code, name in known.items()
        if len(code) == 4 and is_macbook_name(name)
    }

    candidates = set(opencore) | set(snippets) | {
        c for c, n in local.items() if is_macbook_name(n)
    }

    stats = {
        "local_total": len(local),
        "local_macbook": sum(1 for n in local.values() if is_macbook_name(n)),
        "local_non_macbook": {
            c: n for c, n in local.items() if not is_macbook_name(n)
        },
        "opencore_codes": len(opencore),
        "snippets_macbook": len(snippets),
        "apple_macbook": apple_macbook,
        "apple_vague": apple_vague,
        "apple_non_macbook": apple_non_macbook,
        "apple_miss": apple_miss,
        "sibling_filled": len(sibling_fill),
        "desired": len(desired),
        "candidates": len(candidates),
        "unresolved_candidates": sorted(
            c for c in candidates if c not in desired
        ),
    }
    return desired, stats


def diff_maps(local: dict[str, str], desired: dict[str, str]) -> dict:
    local_mb = {c: n for c, n in local.items() if is_macbook_name(n)}
    non_mb = {c: n for c, n in local.items() if not is_macbook_name(n)}

    to_add = {c: desired[c] for c in desired.keys() - local.keys()}
    to_remove = dict(non_mb)
    # Also remove MacBook rows that are no longer desired (rare)
    to_remove.update({c: local[c] for c in local_mb.keys() - desired.keys()})

    to_update = {
        c: (local[c], desired[c])
        for c in local.keys() & desired.keys()
        if local[c] != desired[c]
    }
    return {
        "add": to_add,
        "remove": to_remove,
        "update": to_update,
        "unchanged": len(local.keys() & desired.keys()) - len(to_update),
    }


def print_report(stats: dict, diff: dict, limit: int = 25) -> None:
    print("\n=== MacBook last4 sync report ===")
    print(f"Local rows:              {stats['local_total']}")
    print(f"Local MacBook rows:      {stats['local_macbook']}")
    print(f"Local non-MacBook rows:  {len(stats['local_non_macbook'])}")
    for code, name in sorted(stats["local_non_macbook"].items()):
        print(f"  - DROP {code}: {name}")
    print(f"OpenCore MacBook codes:  {stats['opencore_codes']}")
    print(f"Snippet MacBook codes:   {stats['snippets_macbook']}")
    print(f"Apple confirmed MacBook: {stats['apple_macbook']}")
    print(f"Apple vague MacBook:     {stats['apple_vague']}")
    print(f"Apple non-MacBook:       {stats['apple_non_macbook']}")
    print(f"Apple unknown:           {stats['apple_miss']}")
    print(f"Sibling name fills:      {stats['sibling_filled']}")
    print(f"Desired MacBook rows:    {stats['desired']}")
    print(f"Unresolved candidates:   {len(stats['unresolved_candidates'])}")

    print(f"\nChanges: +{len(diff['add'])} / -{len(diff['remove'])} / ~{len(diff['update'])} / ={diff['unchanged']}")

    if diff["remove"]:
        print("\nRemove:")
        for i, (code, name) in enumerate(sorted(diff["remove"].items())):
            if i >= limit:
                print(f"  ... and {len(diff['remove']) - limit} more")
                break
            print(f"  - {code}: {name}")

    if diff["update"]:
        print("\nUpdate:")
        for i, (code, (old, new)) in enumerate(sorted(diff["update"].items())):
            if i >= limit:
                print(f"  ... and {len(diff['update']) - limit} more")
                break
            print(f"  ~ {code}: {old!r} -> {new!r}")

    if diff["add"]:
        print("\nAdd:")
        for i, (code, name) in enumerate(sorted(diff["add"].items())):
            if i >= limit:
                print(f"  ... and {len(diff['add']) - limit} more")
                break
            print(f"  + {code}: {name}")


def gather_lookup_targets(
    local: dict[str, str],
    snippets: dict[str, str],
    opencore: dict[str, str],
    verify_all: bool,
) -> list[str]:
    targets = set(opencore) | set(snippets)
    if verify_all:
        targets |= set(local)
    else:
        # Always re-check local non-MacBook and vague names; skip Apple for
        # local MacBook rows that already look complete unless --verify-all.
        for code, name in local.items():
            if not is_macbook_name(name) or name == "MacBook Air" or "(" not in name:
                targets.add(code)
        # Look up OpenCore/snippet codes that have no usable local name yet
        for code in set(opencore) | set(snippets):
            if code not in local or not is_macbook_name(local.get(code, "")):
                targets.add(code)
    return sorted(targets)


def run(check_only: bool, verify_all: bool, workers: int, no_siblings: bool) -> int:
    print(f"CSV: {CSV_PATH}")
    local = load_csv(CSV_PATH)
    print(f"Loaded {len(local)} unique codes from last4.csv")

    print("Fetching OpenCore MacBook config codes...")
    opencore = fetch_opencore_macbook_codes()
    print(f"  {len(opencore)} four-character MacBook* codes")

    print("Fetching community MacBook snippets...")
    snippets = fetch_snippets_macbook()
    print(f"  {len(snippets)} four-character MacBook snippets")

    cache = load_cache(CACHE_PATH)
    targets = gather_lookup_targets(local, snippets, opencore, verify_all)
    print(f"Apple lookup targets: {len(targets)} (cache has {len(cache)})")

    apple = lookup_many(targets, cache, workers=workers, force=verify_all)

    desired, stats = build_desired(
        local, snippets, opencore, apple, use_siblings=not no_siblings
    )
    diff = diff_maps(local, desired)
    print_report(stats, diff)

    if check_only:
        changed = bool(diff["add"] or diff["remove"] or diff["update"])
        print("\nCheck only — no files written." if changed else "\nAlready in sync.")
        return 1 if changed else 0

    if not (diff["add"] or diff["remove"] or diff["update"]):
        print("\nAlready in sync — nothing to write.")
        return 0

    backup = CSV_PATH.with_suffix(".csv.bak")
    if CSV_PATH.exists():
        backup.write_bytes(CSV_PATH.read_bytes())
        print(f"\nBackup written: {backup.name}")

    write_csv(CSV_PATH, desired)
    print(f"Synced {len(desired)} MacBook rows -> {CSV_PATH.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check/sync last4.csv with MacBook-only Apple config codes."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Report drift only")
    mode.add_argument("--sync", action="store_true", help="Write updated last4.csv")
    mode.add_argument("--lookup", metavar="CODE", help="Look up one config code via Apple")

    parser.add_argument(
        "--verify-all",
        action="store_true",
        help="Re-query Apple for every local/candidate code (ignores name cache hits)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Concurrent Apple lookups (default: 16)",
    )
    parser.add_argument(
        "--no-siblings",
        action="store_true",
        help="Do not fill missing names from sibling OpenCore model codes",
    )
    args = parser.parse_args(argv)

    if args.lookup:
        code = args.lookup.strip().upper()
        name = apple_lookup(code)
        if name is None:
            print(f"{code}: unknown")
            return 1
        kind = "MacBook" if is_macbook_name(name) else "OTHER"
        print(f"{code}: {name}  [{kind}]")
        return 0 if is_macbook_name(name) else 2

    try:
        return run(
            check_only=args.check,
            verify_all=args.verify_all,
            workers=max(1, args.workers),
            no_siblings=args.no_siblings,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
