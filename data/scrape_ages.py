#!/usr/bin/env python3
"""
data.scrape_ages — true draft-day ages from Tankathon.

Why: the model's age feature is a class-year ordinal ("Freshman"), but
freshmen span 18.4-20.1 years old — a huge projection difference the model
can't currently see. Tankathon lists draft-day age to one decimal for every
pick on its past-draft pages and for current prospects on the big board.

Sources (one page per year — no per-player crawling):
    https://www.tankathon.com/past_drafts/<year>   2020-2025 drafted players
    https://www.tankathon.com/big_board            current (2026) prospects

Coverage is drafted players + current board only; undrafted training rows
fall back to a class-year average at featurize time (honest imputation).

Usage:
    python -m data.scrape_ages              # writes datasets/ages.json
"""

import html as html_mod
import re
import sys
import time

import requests

from core.config import DATASETS_DIR
from core.jsonio import save_json
from core.names import normalize_name

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
}
DELAY = 3.0
DRAFT_YEARS = (2020, 2021, 2022, 2023, 2024, 2025)
CURRENT_YEAR = 2026

RE_NAME = re.compile(r'mock-row-name">([^<]+)</div>')
RE_SCHOOL = re.compile(r'mock-row-school-position">([^<]*?)(?:\|([^<]*))?</')
RE_AGE = re.compile(r'<div>([\d.]+) yrs</div>')
RE_CLASS = re.compile(r'year-age[^"]*"><div>([^<]*)</div>')


def parse_rows(html: str) -> list[dict]:
    """Each mock-row block independently — name/age counts differ per page."""
    out = []
    for block in re.split(r'<div class="mock-row(?: future)?"[^>]*>', html)[1:]:
        block = block.split('mock-row-stats')[0]  # one player's header only
        name = RE_NAME.search(block)
        if not name:
            continue
        age = RE_AGE.search(block)
        cls = RE_CLASS.search(block)
        sp = RE_SCHOOL.search(block)
        school = (sp.group(2) or "").strip() if sp else ""
        out.append({
            "name": html_mod.unescape(name.group(1)).strip(),
            "school": html_mod.unescape(school),
            "class": cls.group(1).strip() if cls else "",
            "age": float(age.group(1)) if age else None,
        })
    return out


def main():
    ages: dict[str, list] = {}
    pages = [(y, f"https://www.tankathon.com/past_drafts/{y}") for y in DRAFT_YEARS]
    pages.append((CURRENT_YEAR, "https://www.tankathon.com/big_board"))

    for year, url in pages:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        rows = parse_rows(r.text)
        with_age = [x for x in rows if x["age"] is not None]
        print(f"{year}: {len(rows)} rows, {len(with_age)} with age  ({url})")
        ages[str(year)] = with_age
        time.sleep(DELAY)

    # name-keyed lookup per year for fast matching downstream
    out = {
        "by_year": {
            y: {normalize_name(x["name"]): {"age": x["age"], "school": x["school"],
                                            "class": x["class"], "name": x["name"]}
                for x in rows}
            for y, rows in ages.items()
        },
    }
    path = DATASETS_DIR / "ages.json"
    save_json(path, out)
    n = sum(len(v) for v in out["by_year"].values())
    print(f"\nSaved {n} player ages -> {path.name}")


if __name__ == "__main__":
    main()
