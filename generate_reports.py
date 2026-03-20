#!/usr/bin/env python3
"""
Pre-generate AI scouting reports for all players using Ollama.

Usage:
    python generate_reports.py

Reads players.json, generates a scouting report for each player via
Ollama (llama3.1), and saves results to reports.json. The app reads
this file at runtime — no Ollama needed when running the app.

Takes ~30-60 min for ~1000 players depending on hardware.
"""

import json
import time
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"
PLAYERS_FILE = Path(__file__).parent / "players.json"
REPORTS_FILE = Path(__file__).parent / "reports.json"


def build_prompt(p: dict) -> str:
    stat_lines = [f"  {k}: {v}" for k, v in p.get("stats", {}).items() if v is not None]
    adv_lines = [f"  {k}: {v}" for k, v in p.get("advanced", {}).items() if v is not None]

    return f"""You are an expert NBA draft scout. Write a detailed scouting report for this college basketball player.
Be specific about their game — reference their actual stats. Write 3-4 paragraphs covering:
1. Overall profile and role
2. Offensive strengths and scoring ability
3. Defensive impact and areas of concern
4. NBA projection and draft outlook

Player: {p['name']}
Position: {p['pos']} | School: {p['school']} ({p.get('conference', '')}) | Class: {p.get('year', '')} | Height: {p.get('height', '')}

Season Stats:
{chr(10).join(stat_lines)}

Advanced Metrics:
{chr(10).join(adv_lines)}

Write the report directly — no headers, no bullet points, just flowing paragraphs. Be honest about weaknesses."""


def generate_report(prompt: str) -> str:
    r = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 600},
    }, timeout=180)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def main():
    # Check Ollama is running
    try:
        requests.get("http://localhost:11434/api/tags", timeout=5)
    except requests.ConnectionError:
        print("ERROR: Ollama is not running. Start it with: ollama serve")
        return

    # Load players
    if not PLAYERS_FILE.exists():
        print("ERROR: players.json not found. Run scrape.py first.")
        return

    raw = json.loads(PLAYERS_FILE.read_text(encoding="utf-8"))
    players = raw["players"]
    total = len(players)

    # Load existing reports to allow resuming
    existing = {}
    if REPORTS_FILE.exists():
        existing = json.loads(REPORTS_FILE.read_text(encoding="utf-8"))
    skip_count = sum(1 for p in players if str(p["id"]) in existing)

    print(f"\nScouting Report Generator")
    print(f"=" * 50)
    print(f"  Players: {total}")
    print(f"  Already generated: {skip_count}")
    print(f"  Remaining: {total - skip_count}")
    print(f"  Model: {MODEL}")
    print(f"=" * 50)

    errors = 0
    for i, p in enumerate(players, 1):
        pid = str(p["id"])

        # Skip already generated
        if pid in existing:
            continue

        bar = "#" * int(i / total * 30) + "-" * (30 - int(i / total * 30))
        print(f"\r  [{bar}] {i}/{total}  {p['name']:<30}", end="", flush=True)

        try:
            prompt = build_prompt(p)
            report = generate_report(prompt)
            existing[pid] = report

            # Save after every player so we can resume if interrupted
            with open(REPORTS_FILE, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)

        except Exception as e:
            errors += 1
            existing[pid] = f"Report generation failed: {e}"

    print(f"\n\nDone! Generated {len(existing)} reports ({errors} errors)")
    print(f"Saved to {REPORTS_FILE.name}")


if __name__ == "__main__":
    main()
