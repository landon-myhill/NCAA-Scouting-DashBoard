#!/usr/bin/env python3
"""
NBA Draft Declared-Entrants Scraper
------------------------------------
Builds draft_eligible.json from HoopsRumors (the most complete early-entrants
list, with explicit in_draft / testing_waters / withdrawn / international
status), with Wikipedia as a cross-check fallback.

Note: auto-eligible seniors are NOT scraped here — Wikipedia only documents
the eligibility *criteria*, not a roster. rerank.py infers auto-eligibility
directly from each player's class year (Senior / Graduate / 5th Year).

Usage:
    python scrape_draft.py

Run before rerank.py to refresh the declared list. rerank.py reads
draft_eligible.json and stamps each matching players.json entry with
a `draft_status` field.
"""

import json
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

YEAR = 2026
OUT_FILE = Path(__file__).parent / "draft_eligible.json"
OVERRIDES_FILE = Path(__file__).parent / "draft_overrides.json"

WIKI_URL = f"https://en.wikipedia.org/wiki/{YEAR}_NBA_draft"
HOOPSRUMORS_URL = f"https://www.hoopsrumors.com/{YEAR}/04/{YEAR}-nba-draft-early-entrants-list.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept-Language": "en-US,en;q=0.9",
}


def _norm(name: str) -> str:
    """Normalize a name for matching: strip accents, lowercase, drop suffixes."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def _fetch(url: str, retries: int = 3, delay: float = 1.5) -> str:
    """GET with polite retries."""
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            time.sleep(delay * (i + 1))
    raise RuntimeError(f"Could not fetch {url}: {last_err}")


def parse_wikipedia(html: str) -> list[dict]:
    """
    Extract declared entrants from Wikipedia. The article lists them under
    section headings: 'Early entrants' (with sub-headings 'College
    underclassmen' and 'International players') and 'Automatically eligible
    entrants'. Each list item is plain text like
    'Player Name – G, Arkansas (freshman)'.
    """
    soup = BeautifulSoup(html, "html.parser")
    entrants: list[dict] = []

    section_keywords = {
        "college underclassmen": "early_entrant",
        "international players": "international",
        "automatically eligible": "auto_eligible",
        "auto eligible": "auto_eligible",
    }

    for heading in soup.find_all(["h3", "h4"]):
        title = heading.get_text(strip=True).lower()
        etype = next((v for k, v in section_keywords.items() if k in title), None)
        if etype is None:
            continue

        # Wikipedia wraps modern headings in <div class="mw-heading">, so the
        # <ul> isn't a direct sibling. Grab the next <ul> in document order;
        # each entrant section has exactly one such list immediately following.
        ul = heading.find_next("ul")
        if ul is None:
            continue
        for li in ul.find_all("li", recursive=False):
            txt = li.get_text(" ", strip=True)
            if not txt or len(txt) < 4:
                continue
            # Strip a leading parenthetical (rare nationality prefix)
            txt_clean = re.sub(r"^\([^)]*\)\s*", "", txt)
            # Name is everything up to the first " – " (en dash) or " - "
            m = re.match(r"^([A-Z][\w'\-\.À-ɏ\s]+?)(?:\s*[–\-]\s*|\s*\()", txt_clean)
            name = m.group(1).strip() if m else txt_clean.split(",")[0].strip()
            if len(name.split()) < 2:
                continue
            entrants.append({
                "name": name,
                "raw": txt,
                "type": etype,
                "source": "wikipedia",
            })

    # Dedupe by normalized name
    seen: set[str] = set()
    deduped: list[dict] = []
    for e in entrants:
        n = _norm(e["name"])
        if n in seen:
            continue
        seen.add(n)
        deduped.append(e)
    return deduped


def parse_hoopsrumors(html: str) -> dict[str, str]:
    """
    Extract status flags from HoopsRumors. The article uses <strong> tags both
    for section headers (ending with ':', e.g. "Expected to remain in draft:")
    AND for individual player names. We walk <strong>/<h3> tags in order,
    flipping the current_status when we see a header and otherwise treating
    each <strong> as a player name.

    Some names are split across two <strong> tags (e.g. "Cameron" / "Boozer")
    due to inline markup glitches; we rejoin a trailing single-word <strong>
    with a preceding single-word <strong>.
    """
    soup = BeautifulSoup(html, "html.parser")
    entry = soup.find("div", class_="entry-content")
    if entry is None:
        return {}

    status_map = {
        "remain in draft": "in_draft",
        "remaining in draft": "in_draft",
        "testing the waters": "testing_waters",
        "testing the draft waters": "testing_waters",
        "testing waters": "testing_waters",
        "withdrawing from the draft": "withdrawn",
        "withdrawn": "withdrawn",
        "international players": "international",
    }

    statuses: dict[str, str] = {}
    current_status = None
    pending: list[str] = []  # accumulator for split-name parts

    def flush_pending():
        """Combine any pending single-word fragments into one name."""
        if not pending:
            return
        joined = " ".join(pending).strip()
        if current_status and len(joined.split()) >= 2:
            statuses[_norm(joined)] = current_status
        pending.clear()

    for tag in entry.find_all(["strong", "h3", "h4"]):
        txt = tag.get_text(" ", strip=True)
        if not txt:
            continue

        # Section header detection: ends with ':' or matches a known section title
        low = txt.lower().rstrip(":").strip()
        new_status = None
        for k, v in status_map.items():
            if k in low:
                new_status = v
                break

        if new_status:
            flush_pending()
            current_status = new_status
            continue

        # Otherwise treat as a player name (possibly fragmented).
        # If this fragment is a single word and a previous fragment was also
        # single-word, treat them as parts of one name. If this fragment has
        # 2+ words, flush any pending and store immediately.
        if len(txt.split()) >= 2:
            flush_pending()
            if current_status:
                statuses[_norm(txt)] = current_status
        else:
            # Single word — buffer it, will be combined with next single-word
            pending.append(txt)
            if len(pending) == 2:
                # Two single words → assume "First Last"
                flush_pending()

    flush_pending()
    return statuses


def _parse_hoopsrumors_named(html: str) -> dict[str, dict]:
    """
    Same walker as parse_hoopsrumors but keeps the display name alongside
    the status. Returns {normalized_name: {"name": str, "status": str}}.
    """
    soup = BeautifulSoup(html, "html.parser")
    entry = soup.find("div", class_="entry-content")
    if entry is None:
        return {}

    status_map = {
        "remain in draft": "in_draft",
        "remaining in draft": "in_draft",
        "testing the waters": "testing_waters",
        "testing the draft waters": "testing_waters",
        "testing waters": "testing_waters",
        "withdrawing from the draft": "withdrawn",
        "withdrawn": "withdrawn",
        "international players": "international",
    }

    out: dict[str, dict] = {}
    current_status: str | None = None
    pending: list[str] = []

    def flush_pending():
        if not pending or not current_status:
            pending.clear()
            return
        joined = " ".join(pending).strip()
        if len(joined.split()) >= 2:
            out[_norm(joined)] = {"name": joined, "status": current_status}
        pending.clear()

    for tag in entry.find_all(["strong", "h3", "h4"]):
        txt = tag.get_text(" ", strip=True)
        if not txt:
            continue
        low = txt.lower().rstrip(":").strip()
        new_status = next((v for k, v in status_map.items() if k in low), None)

        if new_status:
            flush_pending()
            current_status = new_status
            continue

        if len(txt.split()) >= 2:
            flush_pending()
            if current_status:
                out[_norm(txt)] = {"name": txt, "status": current_status}
        else:
            pending.append(txt)
            if len(pending) == 2:
                flush_pending()

    flush_pending()
    return out


def main():
    # HoopsRumors is the primary source — it has the most complete list of
    # early entrants with explicit status. We need to recover full names from
    # it (the parser returns {normalized_name: status}), so we also pull the
    # raw <strong> tags below to keep display-friendly names.
    print(f"Fetching HoopsRumors ({HOOPSRUMORS_URL})...")
    hr_entries: dict[str, dict] = {}
    try:
        hr_html = _fetch(HOOPSRUMORS_URL)
        hr_entries = _parse_hoopsrumors_named(hr_html)
        print(f"  -> parsed {len(hr_entries)} entrants from HoopsRumors")
    except Exception as e:
        print(f"  !! HoopsRumors fetch failed: {e}")

    # Wikipedia as cross-check + source of display names (some HoopsRumors
    # entries are first-name-only fragments due to inline markup glitches).
    print(f"Fetching Wikipedia ({WIKI_URL})...")
    wiki_entrants: list[dict] = []
    try:
        wiki_html = _fetch(WIKI_URL)
        wiki_entrants = parse_wikipedia(wiki_html)
        print(f"  -> parsed {len(wiki_entrants)} entrants from Wikipedia")
    except Exception as e:
        print(f"  !! Wikipedia fetch failed: {e}")

    declared: list[dict] = []
    seen_norms: set[str] = set()

    # 1. HoopsRumors entries (canonical source for status)
    for n, info in hr_entries.items():
        declared.append({
            "name": info["name"],
            "norm_name": n,
            "status": info["status"],
            "type": "early_entrant" if info["status"] != "international" else "international",
            "source": "hoopsrumors",
        })
        seen_norms.add(n)

    # 2. Wikipedia entries that HoopsRumors didn't include (rare, but covers
    # late-breaking international additions and any naming mismatches)
    for e in wiki_entrants:
        n = _norm(e["name"])
        if n in seen_norms:
            continue
        # Skip the Wikipedia "auto_eligible" type — that section is criteria,
        # not a roster (handled by rerank.py from player class year instead).
        if e["type"] == "auto_eligible":
            continue
        declared.append({
            "name": e["name"],
            "norm_name": n,
            "status": "in_draft" if e["type"] != "international" else "international",
            "type": e["type"],
            "source": "wikipedia",
        })
        seen_norms.add(n)

    # 3. Manual overrides
    if OVERRIDES_FILE.exists():
        overrides = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
        print(f"Applying {len(overrides)} manual overrides from draft_overrides.json")
        for o in overrides:
            n = _norm(o["name"])
            if n not in seen_norms:
                declared.append({
                    "name": o["name"],
                    "norm_name": n,
                    "status": o.get("status", "in_draft"),
                    "type": o.get("type", "early_entrant"),
                    "source": "manual",
                })
                seen_norms.add(n)

    declared.sort(key=lambda d: d["name"])
    OUT_FILE.write_text(json.dumps(declared, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(declared)} entries to draft_eligible.json")

    by_status: dict[str, int] = {}
    for d in declared:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    for s, n in sorted(by_status.items()):
        print(f"  {s}: {n}")


if __name__ == "__main__":
    main()
