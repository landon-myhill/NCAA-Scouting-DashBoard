"""core.jsonio — small, consistent JSON load/save helpers (UTF-8, pretty)."""

import json
from pathlib import Path


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_players(path) -> list[dict]:
    """Load a players file, returning the players list whether the file is a
    bare list or the standard {'players': [...]} envelope."""
    raw = load_json(path, default=[])
    if isinstance(raw, dict):
        return raw.get("players", [])
    return raw
