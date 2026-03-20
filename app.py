import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import requests
import json
import os
from pathlib import Path
from archetypes import classify

st.set_page_config(page_title="NCAA Draft Scout", layout="wide", page_icon="🏀")

# ─── NCAA API ────────────────────────────────────────────────────────────────

_BASE = "https://ncaa-api.henrygd.me"

# Correct stat category IDs from ncaa.com/stats/basketball-men/d1
# Only PPG (136), RPG (137), APG (140) are currently parseable by the API.
# All other categories return HTTP 500 "Could not parse data" from ncaa.com.
_STAT_IDS = {
    "scoring":  136,   # Points Per Game  — fields: Name, Team, Cl, Height, Position, G, FGM, 3FG, FT, PTS, PPG
    "rebounds": 137,   # Rebounds Per Game — fields: Name, Team, Cl, Height, Position, G, REB, RPG
    "assists":  140,   # Assists Per Game  — fields: Name, Team, Cl, Height, Position, G, AST, APG
}

# School → conference lookup for API players that don't return conference directly
SCHOOL_CONF = {
    # Big 12
    "kansas": "Big 12", "baylor": "Big 12", "texas tech": "Big 12",
    "oklahoma state": "Big 12", "houston": "Big 12", "iowa state": "Big 12",
    "tcu": "Big 12", "west virginia": "Big 12", "cincinnati": "Big 12",
    "ucf": "Big 12", "byu": "Big 12", "texas": "Big 12",
    # ACC
    "duke": "ACC", "north carolina": "ACC", "unc": "ACC",
    "virginia": "ACC", "louisville": "ACC", "florida state": "ACC",
    "nc state": "ACC", "miami": "ACC", "pittsburgh": "ACC",
    "georgia tech": "ACC", "boston college": "ACC", "wake forest": "ACC",
    "notre dame": "ACC", "syracuse": "ACC", "clemson": "ACC",
    # Pac-12
    "ucla": "Pac-12", "arizona": "Pac-12", "oregon": "Pac-12", "usc": "Pac-12",
    "arizona state": "Pac-12", "utah": "Pac-12", "colorado": "Pac-12",
    "washington": "Pac-12", "oregon state": "Pac-12", "stanford": "Pac-12",
    "california": "Pac-12",
    # SEC
    "kentucky": "SEC", "alabama": "SEC", "tennessee": "SEC", "arkansas": "SEC",
    "florida": "SEC", "auburn": "SEC", "mississippi state": "SEC",
    "ole miss": "SEC", "lsu": "SEC", "south carolina": "SEC",
    "georgia": "SEC", "vanderbilt": "SEC", "missouri": "SEC", "texas a&m": "SEC",
    # Big Ten
    "michigan": "Big Ten", "michigan state": "Big Ten", "indiana": "Big Ten",
    "illinois": "Big Ten", "purdue": "Big Ten", "ohio state": "Big Ten",
    "wisconsin": "Big Ten", "iowa": "Big Ten", "minnesota": "Big Ten",
    "penn state": "Big Ten", "nebraska": "Big Ten", "northwestern": "Big Ten",
    "maryland": "Big Ten", "rutgers": "Big Ten",
    # Big East
    "connecticut": "Big East", "uconn": "Big East", "villanova": "Big East",
    "marquette": "Big East", "xavier": "Big East", "seton hall": "Big East",
    "creighton": "Big East", "providence": "Big East", "butler": "Big East",
    "st. john's": "Big East", "depaul": "Big East", "georgetown": "Big East",
    # WCC
    "gonzaga": "WCC", "saint mary's": "WCC", "san francisco": "WCC",
    # Mountain West
    "san diego state": "Mountain West", "nevada": "Mountain West",
    "utah state": "Mountain West", "new mexico": "Mountain West",
    # AAC
    "memphis": "AAC", "wichita state": "AAC",
}


def get_conference(school: str) -> str:
    return SCHOOL_CONF.get(school.lower().strip(), "Other")


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_leaders(stat_id: int) -> list:
    url = f"{_BASE}/stats/basketball-men/d1/current/individual/{stat_id}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        inner = data.get("data", data)
        if isinstance(inner, dict):
            return inner.get("player", [])
        if isinstance(inner, list):
            return inner
    return data if isinstance(data, list) else []


def _str(row: dict, *keys) -> str:
    for k in keys:
        v = row.get(k)
        if v:
            return str(v).strip()
    return ""


def _float(row: dict, *keys) -> float:
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return 0.0


def _format_name(raw: str) -> str:
    if "," in raw:
        last, first = raw.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return raw


def _class_label(cls: str) -> str:
    mapping = {
        "FR": "Freshman",  "SO": "Sophomore", "JR": "Junior",
        "SR": "Senior",    "GR": "Graduate",  "5TH": "5th Year",
        "FR.": "Freshman", "SO.": "Sophomore","JR.": "Junior",
        "SR.": "Senior",   "GR.": "Graduate",
    }
    return mapping.get(cls.upper().strip() if cls else "", cls or "Unknown")


def _fmt_height(h: str) -> str:
    """Convert '6-9' to 6'9\" """
    if "-" in h and "'" not in h:
        parts = h.split("-")
        if len(parts) == 2:
            return f"{parts[0]}'{parts[1]}\""
    return h


def _derive_skills(ppg, rpg, apg) -> dict:
    """Estimate 0-100 skill ratings from PPG, RPG, APG (the only live stats available)."""
    shooting      = int(min(100, max(0, ppg / 30.0 * 100)))
    defense       = int(min(100, max(0, rpg / 12.0 * 70 + apg / 9.0 * 30)))
    ball_handling = int(min(100, max(0, apg / 9.0 * 100)))
    athleticism   = int(min(100, max(0, (ppg / 30.0 * 50) + (rpg / 12.0 * 50))))
    iq            = int(min(100, max(0, apg / 9.0 * 60 + rpg / 12.0 * 40)))
    leadership    = int(min(100, max(0, (ppg / 30.0 * 50) + (apg / 9.0 * 50))))
    return {"Athleticism": athleticism, "Defense": defense, "Shooting": shooting,
            "Ball Handling": ball_handling, "IQ": iq, "Leadership": leadership}


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_all_leaders(stat_id: int, max_pages: int = 8) -> list:
    """Fetch up to max_pages pages and return all rows combined."""
    rows = []
    for page in range(1, max_pages + 1):
        url = f"{_BASE}/stats/basketball-men/d1/current/individual/{stat_id}"
        try:
            r = requests.get(url, params={"page": page}, timeout=10)
            r.raise_for_status()
            data = r.json()
            page_rows = []
            if isinstance(data, dict):
                inner = data.get("data", data)
                if isinstance(inner, dict):
                    page_rows = inner.get("player", [])
                elif isinstance(inner, list):
                    page_rows = inner
            elif isinstance(data, list):
                page_rows = data
            if not page_rows:
                break
            rows.extend(page_rows)
            if page >= data.get("pages", 1):
                break
        except Exception:
            break
    return rows


def _make_player_stub(row: dict, pid: int) -> dict:
    """Build a blank player profile from any stat endpoint row."""
    name = _str(row, "Name")
    team = _str(row, "Team")
    height_raw = _str(row, "Height")
    return {
        "id": pid,
        "name": name,
        "pos": _str(row, "Position") or "?",
        "school": team or "Unknown",
        "conference": get_conference(team),
        "year": _class_label(_str(row, "Cl")),
        "height": _fmt_height(height_raw) if height_raw else "—",
        "weight": "—",
        "hometown": "—",
        "stats": {
            "PPG": None, "RPG": None, "APG": None,
            "SPG": None, "BPG": None,
            "FG%": None, "3P%": None, "FT%": None,
            "MPG": None, "GS": None, "TOV": None, "FTA": None,
            "OREB": None, "DREB": None, "3PA": None, "FGA": None, "PF": None,
        },
        "advanced": {
            "PER": None, "TS%": None, "eFG%": None, "USG%": None,
            "AST%": None, "TOV%": None,
            "BPM": None, "OBPM": None, "DBPM": None,
            "OWS": None, "DWS": None, "Win Shares": None, "WS/40": None,
        },
        "skills": {}, "strengths": [], "weaknesses": [], "comps": [],
        "injury": "Clean",
        "tier": 2, "rank": pid,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def build_api_players() -> list:
    """
    Build player list from top 10 of each available stat category.
    Using multiple categories gives players complete (or near-complete) stat lines,
    since top scorers often aren't top rebounders/assisters.
    """
    player_map: dict[tuple, dict] = {}
    pid_counter = 0

    fetch_plan = [
        (_STAT_IDS["scoring"],  "PPG", 1),   # top 10 scorers
        (_STAT_IDS["rebounds"], "RPG", 1),   # top 10 rebounders
        (_STAT_IDS["assists"],  "APG", 1),   # top 10 assist leaders
    ]

    for stat_id, stat_key, pages in fetch_plan:
        try:
            rows = []
            for page in range(1, pages + 1):
                rows.extend(_fetch_leaders(stat_id) if page == 1 else
                            _fetch_all_leaders(stat_id, max_pages=1))
            for row in rows[:10]:
                name = _str(row, "Name")
                team = _str(row, "Team")
                if not name:
                    continue
                key = (name.lower(), team.lower())
                if key not in player_map:
                    pid_counter += 1
                    player_map[key] = _make_player_stub(row, pid_counter)
                player_map[key]["stats"][stat_key] = _float(row, stat_key)
        except Exception:
            pass

    if not player_map:
        return []

    # Also merge all 3 stat types into any player already in the map
    try:
        for row in _fetch_all_leaders(_STAT_IDS["rebounds"], max_pages=10):
            key = (_str(row, "Name").lower(), _str(row, "Team").lower())
            if key in player_map and player_map[key]["stats"]["RPG"] is None:
                player_map[key]["stats"]["RPG"] = _float(row, "RPG")
    except Exception:
        pass
    try:
        for row in _fetch_all_leaders(_STAT_IDS["assists"], max_pages=10):
            key = (_str(row, "Name").lower(), _str(row, "Team").lower())
            if key in player_map and player_map[key]["stats"]["APG"] is None:
                player_map[key]["stats"]["APG"] = _float(row, "APG")
    except Exception:
        pass
    try:
        for row in _fetch_all_leaders(_STAT_IDS["scoring"], max_pages=10):
            key = (_str(row, "Name").lower(), _str(row, "Team").lower())
            if key in player_map and player_map[key]["stats"]["PPG"] is None:
                player_map[key]["stats"]["PPG"] = _float(row, "PPG")
    except Exception:
        pass

    # Assign ranks by PPG, then RPG, then APG
    players = sorted(player_map.values(),
                     key=lambda p: (p["stats"]["PPG"] or 0), reverse=True)
    for i, p in enumerate(players):
        p["rank"] = i + 1
        p["id"]   = i + 1
        ppg = p["stats"]["PPG"] or 0
        p["tier"] = 1 if i < 5 else (2 if i < 15 else 3)

    # Derive skill ratings
    for p in players:
        s = p["stats"]
        p["skills"] = _derive_skills(s["PPG"] or 0.0, s["RPG"] or 0.0, s["APG"] or 0.0)

    return players


# ─── Sample Data ─────────────────────────────────────────────────────────────

TIER_LABELS = {1: "Tier 1 — Lottery", 2: "Tier 2 — Late 1st Round", 3: "Tier 3 — 2nd Round"}

# ─── Sidebar — data source ────────────────────────────────────────────────────

st.sidebar.markdown("## 🏀 NCAA Draft Scout")
st.sidebar.markdown("---")

_JSON_FILE = Path(__file__).parent / "players.json"
_json_exists = _JSON_FILE.exists()

_src_options = []
if _json_exists:
    _src_options.append("Scraped Data")
_src_options.append("Live NCAA API")

data_source = st.sidebar.radio("Data Source", _src_options, horizontal=True)

if data_source == "Scraped Data":
    try:
        _raw = json.loads(_JSON_FILE.read_text(encoding="utf-8"))
        PLAYERS = _raw["players"]
        _scraped_at = _raw.get("scraped_at", "")[:10]
        _season = _raw.get("season", "")
        st.sidebar.caption(f"Scraped {_season} · {len(PLAYERS)} players · {_scraped_at}")
    except Exception as e:
        st.error(f"Could not load players.json: {e}")
        st.stop()

elif data_source == "Live NCAA API":
    with st.spinner("Fetching live NCAA stats..."):
        PLAYERS = build_api_players()
    if not PLAYERS:
        st.error("Could not load live data. Run `python scrape.py` first.")
        st.stop()
    else:
        st.sidebar.caption(f"Live D1 leaders · {len(PLAYERS)} players · cached 1hr")

else:
    st.error("No data available. Run `python scrape.py` to generate players.json.")
    st.stop()

# ─── Session state ─────────────────────────────────────────────────────────

if st.session_state.get("_src") != data_source:
    st.session_state["_src"]      = data_source
    st.session_state["notes"]     = {p["id"]: "" for p in PLAYERS}
    st.session_state["tiers"]     = {p["id"]: p["tier"] for p in PLAYERS}
    st.session_state["watchlist"] = set()

# ─── Sidebar — filters ───────────────────────────────────────────────────────

st.sidebar.markdown("---")

# Pre-compute archetypes for all players (cached)
@st.cache_data(ttl=86400, show_spinner=False)
def _build_archetypes(player_ids: tuple) -> dict:
    return {p["id"]: classify(p) for p in PLAYERS}

_all_profiles = _build_archetypes(tuple(p["id"] for p in PLAYERS))

with st.sidebar.expander("🔽 Filters", expanded=False):
    all_positions   = sorted(set(p["pos"] for p in PLAYERS))
    all_conferences = sorted(set(p.get("conference", "Other") for p in PLAYERS))
    all_archetypes  = sorted(set(prof["primary"] for prof in _all_profiles.values()))

    pos_filter  = st.multiselect("Position",   all_positions,   default=all_positions,   key="f_pos")
    conf_filter = st.multiselect("Conference", all_conferences, default=all_conferences, key="f_conf")
    arch_filter = st.multiselect("Archetype",  all_archetypes,  default=all_archetypes,  key="f_arch")

FILTERED = [
    p for p in PLAYERS
    if p["pos"] in pos_filter
    and p.get("conference", "Other") in conf_filter
    and _all_profiles[p["id"]]["primary"] in arch_filter
] or PLAYERS

# ─── Sidebar — player selector ────────────────────────────────────────────────

player_lookup  = {p["name"]: p for p in PLAYERS}

_display_players = sorted(FILTERED, key=lambda p: p["rank"])[:200]
_all_names = [p["name"] for p in _display_players]

selected_name = st.sidebar.selectbox(
    "Search Player",
    _all_names,
    format_func=lambda n: f"#{player_lookup[n]['rank']} {n} · {player_lookup[n]['pos']} · {player_lookup[n]['school']}",
)
player = player_lookup[selected_name]

st.sidebar.markdown("---")
_ds = player.get('draft_score', 0)
st.sidebar.markdown(f"**#{player['rank']} Overall** · Score: **{_ds:.1f}**")
st.sidebar.markdown(f"{player['pos']} · {player['school']} · {player['year']}")
st.sidebar.markdown(f"{player['height']} · {player['weight']}")
if player.get("conference"):
    st.sidebar.markdown(f"*{player['conference']}*")
if player.get("hometown") and player["hometown"] != "—":
    st.sidebar.caption(f"📍 {player['hometown']}")
tier_num = st.session_state["tiers"][player["id"]]
badge_cls = f"tier-badge-{tier_num}"
st.sidebar.markdown(f'<span class="{badge_cls}">{TIER_LABELS[tier_num]}</span>', unsafe_allow_html=True)

st.sidebar.markdown("")
in_watchlist = player["id"] in st.session_state["watchlist"]
wl_label = "★ Remove from Watchlist" if in_watchlist else "☆ Add to Watchlist"
if st.sidebar.button(wl_label, use_container_width=True):
    if in_watchlist:
        st.session_state["watchlist"].discard(player["id"])
    else:
        st.session_state["watchlist"].add(player["id"])
    st.rerun()

if data_source == "Live NCAA API":
    st.sidebar.caption("Skill ratings estimated from stats.")

# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_player(name: str) -> dict:
    return player_lookup[name]


_RADAR_COLORS = [
    ("#f59e0b", "rgba(245,158,11,0.12)"),
    ("#3b82f6", "rgba(59,130,246,0.12)"),
    ("#10b981", "rgba(16,185,129,0.12)"),
    ("#ef4444", "rgba(239,68,68,0.12)"),
    ("#8b5cf6", "rgba(139,92,246,0.12)"),
    ("#ec4899", "rgba(236,72,153,0.12)"),
    ("#14b8a6", "rgba(20,184,166,0.12)"),
    ("#f97316", "rgba(249,115,22,0.12)"),
    ("#6366f1", "rgba(99,102,241,0.12)"),
    ("#84cc16", "rgba(132,204,22,0.12)"),
]


def radar_chart(*players: dict) -> go.Figure:
    """Radar chart supporting 1-5 players."""
    if not players:
        return go.Figure()
    cats = list(players[0]["skills"].keys())
    cats_c = cats + [cats[0]]

    fig = go.Figure()
    for i, p in enumerate(players):
        vals = list(p["skills"].values()) + [list(p["skills"].values())[0]]
        line_c, fill_c = _RADAR_COLORS[i % len(_RADAR_COLORS)]
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=cats_c, fill="toself", name=p["name"],
            line_color=line_c, fillcolor=fill_c,
            hovertemplate="%{theta}: %{r}<extra></extra>",
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=False,
                            gridcolor="rgba(128,128,128,0.2)"),
            angularaxis=dict(gridcolor="rgba(128,128,128,0.2)"),
            bgcolor="rgba(0,0,0,0)",
        ),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        height=360,
    )
    return fig


def stat_delta(v1: float, v2: float) -> str:
    diff = v1 - v2
    if abs(diff) < 0.01:
        return "—"
    color = "green" if diff > 0 else "red"
    return f":{color}[{'▲' if diff > 0 else '▼'} {abs(diff):.1f}]"




# ─── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
.stat-card {
    background: var(--background-color, #f8f9fa);
    border: 1px solid rgba(128,128,128,.15);
    border-radius: 10px;
    padding: 12px 16px;
    text-align: center;
}
.stat-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: .06em; }
.stat-value { font-size: 24px; font-weight: 600; margin: 2px 0; }
.stat-sub   { font-size: 11px; color: #aaa; }

.pill-str { background:#d1fae5; color:#065f46; padding:4px 10px; border-radius:20px; font-size:12px; margin:3px; display:inline-block; }
.pill-wk  { background:#fee2e2; color:#991b1b; padding:4px 10px; border-radius:20px; font-size:12px; margin:3px; display:inline-block; }
.pill-neu { background:#f3f4f6; color:#374151; padding:4px 10px; border-radius:20px; font-size:12px; margin:3px; display:inline-block; border:1px solid #e5e7eb; }

.tier-badge-1 { background:#fef3c7; color:#92400e; padding:4px 12px; border-radius:6px; font-size:12px; font-weight:600; }
.tier-badge-2 { background:#dbeafe; color:#1e40af; padding:4px 12px; border-radius:6px; font-size:12px; font-weight:600; }
.tier-badge-3 { background:#f3f4f6; color:#374151; padding:4px 12px; border-radius:6px; font-size:12px; font-weight:600; }

.wl-card {
    border: 1px solid rgba(128,128,128,.2);
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 8px;
}
</style>
""", unsafe_allow_html=True)

# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab_scout, tab_cmp, tab_bb, tab_wl, tab_scar = st.tabs([
    "🔍 Scouting", "⚖️ Compare",
    "📋 Big Board", "⭐ Watchlist", "📈 Scarcity",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SCOUTING (merged Dashboard + Scouting)
# ══════════════════════════════════════════════════════════════════════════════
with tab_scout:
    # ── Player header ────────────────────────────────────────────────────────
    h1, h2 = st.columns([6, 1])
    with h1:
        st.markdown(f"## {player['name']}")
        bio_parts = [
            player["pos"], player["school"], player.get("conference", ""),
            player["year"], player["height"], player["weight"],
        ]
        hometown = player.get("hometown", "—")
        if hometown and hometown != "—":
            bio_parts.append(f"📍 {hometown}")
        ds = player.get("draft_score", 0)
        st.markdown(
            " · ".join(p for p in bio_parts if p) +
            f"  |  **Draft Rank: #{player['rank']}**"
            f"  |  Draft Score: **{ds:.1f}**"
        )
    with h2:
        in_wl = player["id"] in st.session_state["watchlist"]
        if st.button("★ Watching" if in_wl else "☆ Watch", use_container_width=True):
            if in_wl:
                st.session_state["watchlist"].discard(player["id"])
            else:
                st.session_state["watchlist"].add(player["id"])
            st.rerun()

    inj = player["injury"]
    if inj == "Clean":
        st.success("No injury history on record")
    else:
        st.warning(f"⚠️ {inj}")

    # ── Player Archetypes ────────────────────────────────────────────────────
    st.markdown("---")
    profile = _all_profiles[player["id"]]

    # Primary + Defensive archetype header
    st.markdown(
        f'<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">'
        f'<span style="background:#f59e0b;color:#fff;padding:6px 16px;border-radius:20px;'
        f'font-weight:700;font-size:15px;">{profile["primary"]}</span>'
        f'<span style="background:#3b82f6;color:#fff;padding:6px 16px;border-radius:20px;'
        f'font-weight:700;font-size:15px;">{profile["defensive"]}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Tags
    if profile["tags"]:
        tag_html = " ".join(
            f'<span class="pill-str">{t}</span>' for t in profile["tags"]
        )
        st.markdown(f"**Traits**", unsafe_allow_html=True)
        st.markdown(tag_html, unsafe_allow_html=True)

    # Red flags
    if profile["red_flags"]:
        rf_html = " ".join(
            f'<span class="pill-wk">⚠️ {r}</span>' for r in profile["red_flags"]
        )
        st.markdown(f"**Concerns**", unsafe_allow_html=True)
        st.markdown(rf_html, unsafe_allow_html=True)

    # ── Radar chart + scout notes side by side ───────────────────────────────
    st.markdown("")
    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### Skill Ratings")
        st.plotly_chart(radar_chart(player), use_container_width=True)
    with right:
        st.markdown("#### Scout Notes")
        notes_val = st.text_area(
            label="notes", value=st.session_state["notes"][player["id"]],
            placeholder="Add your personal scouting notes here...", height=260,
            label_visibility="collapsed", key=f"notes_{player['id']}",
        )
        st.session_state["notes"][player["id"]] = notes_val

    # ── Season Stats ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Season Stats")
    stats = player["stats"]

    primary = ["PPG", "RPG", "APG", "SPG", "BPG", "FG%", "3P%", "FT%"]
    cols = st.columns(len(primary))
    for col, label in zip(cols, primary):
        val = stats.get(label)
        with col:
            if val is None:
                disp = "—"
            elif "%" in label:
                disp = "N/A" if val == 0.0 and label == "3P%" else f"{val:.1f}%"
            else:
                disp = f"{val:.1f}"
            st.markdown(
                f'<div class="stat-card"><div class="stat-label">{label}</div>'
                f'<div class="stat-value">{disp}</div></div>',
                unsafe_allow_html=True,
            )

    secondary = ["MPG", "GS", "TOV", "FTA", "OREB", "DREB", "3PA", "FGA"]
    sec_vals = {k: stats.get(k) for k in secondary if stats.get(k) is not None}
    if sec_vals:
        st.markdown("")
        sec_cols = st.columns(len(sec_vals))
        for col, (label, val) in zip(sec_cols, sec_vals.items()):
            disp = str(int(val)) if label == "GS" else f"{val:.1f}"
            st.markdown(
                f'<div class="stat-card"><div class="stat-label">{label}</div>'
                f'<div class="stat-value" style="font-size:20px">{disp}</div></div>',
                unsafe_allow_html=True,
            )

    # ── Advanced Metrics ─────────────────────────────────────────────────────
    st.markdown("")
    st.markdown("#### Advanced Metrics")
    adv = player["advanced"]
    adv_meta = {
        "PER": "Efficiency Rating", "TS%": "True Shooting", "eFG%": "Eff. FG%",
        "USG%": "Usage Rate", "BPM": "Box +/−", "OBPM": "Off. Box +/−",
        "DBPM": "Def. Box +/−", "Win Shares": "Season Total",
        "WS/40": "Per 40 min", "AST%": "Assist Rate", "TOV%": "TO Rate",
        "OWS": "Offensive WS", "DWS": "Defensive WS",
    }
    key_adv = ["PER", "TS%", "eFG%", "USG%", "BPM", "Win Shares"]
    adv_display = [(k, adv.get(k)) for k in key_adv]
    cols2 = st.columns(len(adv_display))
    for col, (label, val) in zip(cols2, adv_display):
        with col:
            if val is None:
                disp, note = "—", "Not available"
            else:
                disp = f"{val:.1f}%" if "%" in label else f"{val:.1f}"
                note = adv_meta.get(label, "")
            st.markdown(
                f'<div class="stat-card"><div class="stat-label">{label}</div>'
                f'<div class="stat-value">{disp}</div>'
                f'<div class="stat-sub">{note}</div></div>',
                unsafe_allow_html=True,
            )

    extra_adv = ["OBPM", "DBPM", "WS/40", "OWS", "DWS", "AST%", "TOV%"]
    extra_vals = [(k, adv.get(k)) for k in extra_adv if adv.get(k) is not None]
    if extra_vals:
        with st.expander("More Advanced Stats"):
            ex_cols = st.columns(len(extra_vals))
            for col, (label, val) in zip(ex_cols, extra_vals):
                disp = f"{val:.1f}%" if "%" in label else f"{val:.1f}"
                col.markdown(
                    f'<div class="stat-card"><div class="stat-label">{label}</div>'
                    f'<div class="stat-value" style="font-size:20px">{disp}</div>'
                    f'<div class="stat-sub">{adv_meta.get(label,"")}</div></div>',
                    unsafe_allow_html=True,
                )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — COMPARE
# ══════════════════════════════════════════════════════════════════════════════
with tab_cmp:
    _cmp_selected = st.multiselect(
        "Search and select players to compare (2-10)",
        _all_names,
        max_selections=10, key="cmp_picks",
    )

    if len(_cmp_selected) < 2:
        st.info("Select at least 2 players to compare.")
        st.stop()

    cmp_players = [player_lookup[n] for n in _cmp_selected]

    # Radar chart
    st.plotly_chart(radar_chart(*cmp_players), use_container_width=True)

    # Comparison table — highlight best value per stat
    st.markdown("#### Stat Comparison")

    # Gather all stat keys
    _stat_keys = list(cmp_players[0]["stats"].keys()) + list(cmp_players[0]["advanced"].keys())
    _stat_keys.insert(0, "Draft Score")

    # Lower-is-better stats
    _lower_better = {"TOV", "TOV%", "PF"}

    rows = []
    for key in _stat_keys:
        row = {"Stat": key}
        vals = []
        for p in cmp_players:
            if key == "Draft Score":
                v = p.get("draft_score", 0)
            else:
                v = {**p["stats"], **p["advanced"]}.get(key)
            vals.append(v)

        # Find the best value
        numeric_vals = [(i, v) for i, v in enumerate(vals) if v is not None and v != 0]
        best_idx = None
        if numeric_vals:
            if key in _lower_better:
                best_idx = min(numeric_vals, key=lambda x: x[1])[0]
            else:
                best_idx = max(numeric_vals, key=lambda x: x[1])[0]

        for i, (p, v) in enumerate(zip(cmp_players, vals)):
            if v is None:
                disp = "—"
            elif key == "3P%" and v == 0.0:
                disp = "N/A"
            elif "%" in key:
                disp = f"{v:.1f}%"
            elif key in ("GS",):
                disp = str(int(v))
            else:
                disp = f"{v:.1f}"
            if i == best_idx and v is not None:
                disp = f"**{disp}** ✓"
            row[p["name"]] = disp

        rows.append(row)

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — BIG BOARD
# ══════════════════════════════════════════════════════════════════════════════
with tab_bb:
    st.markdown("Move players between tiers to build your custom draft board.")

    _bb_pool = st.slider("Show top N prospects", 15, 500, 200, step=5, key="bb_pool")

    # Apply position/conference filters, limit to top N by rank
    bb_players = sorted(
        [p for p in PLAYERS
         if p["pos"] in pos_filter and p.get("conference", "Other") in conf_filter],
        key=lambda p: p["rank"],
    )[:_bb_pool]

    for tier_id, tier_label in TIER_LABELS.items():
        tier_players = sorted(
            [p for p in bb_players if st.session_state["tiers"][p["id"]] == tier_id],
            key=lambda p: p["rank"],
        )
        color_map = {1: "#fef3c7", 2: "#dbeafe", 3: "#f3f4f6"}
        st.markdown(
            f'<div style="background:{color_map[tier_id]};padding:6px 12px;'
            f'border-radius:6px;margin:1rem 0 .4rem;font-weight:600;font-size:13px;">'
            f'{tier_label} — {len(tier_players)} players</div>',
            unsafe_allow_html=True,
        )
        if not tier_players:
            st.caption("No players in this tier")
            continue

        for p in tier_players:
            in_wl = p["id"] in st.session_state["watchlist"]
            cols = st.columns([.04, .32, .12, .08, .08, .1, .1, .1])
            cols[0].markdown(f"**#{p['rank']}**")
            cols[1].markdown(
                f"{'★ ' if in_wl else ''}**{p['name']}** · {p['pos']} · "
                f"{p['school']} · {p.get('conference','')}"
            )
            cols[2].markdown(
                f'<span class="pill-neu">'
                f'{p["injury"] if p["injury"] == "Clean" else "⚠️ " + p["injury"]}'
                f'</span>', unsafe_allow_html=True,
            )
            ppg_v = p["stats"].get("PPG")
            cols[3].markdown(f"`{ppg_v:.1f}`" if ppg_v is not None else "`—`")
            bb_ds = p.get("draft_score", 0)
            cols[4].markdown(f"`{bb_ds:.1f}`")
            if tier_id > 1:
                if cols[5].button("▲", key=f"up_{p['id']}"):
                    st.session_state["tiers"][p["id"]] -= 1
                    st.rerun()
            if tier_id < 3:
                if cols[6].button("▼", key=f"dn_{p['id']}"):
                    st.session_state["tiers"][p["id"]] += 1
                    st.rerun()

    # Export Big Board
    st.markdown("---")
    bb_export = []
    for p in sorted(bb_players, key=lambda x: x["rank"]):
        prof = _all_profiles[p["id"]]
        bb_export.append({
            "Rank": p["rank"], "Name": p["name"], "Pos": p["pos"],
            "School": p["school"], "Conference": p.get("conference", ""),
            "Year": p["year"], "Height": p["height"],
            "Draft Score": p.get("draft_score", 0),
            "Tier": TIER_LABELS[st.session_state["tiers"][p["id"]]],
            "Archetype": prof["primary"],
            "PPG": p["stats"].get("PPG"), "RPG": p["stats"].get("RPG"),
            "APG": p["stats"].get("APG"), "PER": p["advanced"].get("PER"),
            "BPM": p["advanced"].get("BPM"),
        })
    bb_df = pd.DataFrame(bb_export)
    st.download_button(
        "📥 Download Big Board (CSV)", bb_df.to_csv(index=False),
        file_name="big_board.csv", mime="text/csv",
    )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — WATCHLIST
# ══════════════════════════════════════════════════════════════════════════════
with tab_wl:
    watched = [p for p in PLAYERS if p["id"] in st.session_state["watchlist"]]

    if not watched:
        st.info("No players on your watchlist yet. Click ☆ Watch on any player to add them.")
    else:
        st.markdown(f"### Watchlist — {len(watched)} player{'s' if len(watched) != 1 else ''}")
        st.markdown("---")

        for p in sorted(watched, key=lambda x: x["rank"]):
            tier_num_p = st.session_state["tiers"][p["id"]]
            w1, w2, w3 = st.columns([3, 5, 1])

            with w1:
                st.markdown(
                    f"**#{p['rank']} {p['name']}**  \n"
                    f"{p['pos']} · {p['school']} · {p.get('conference', '')}  \n"
                    f"{p['year']} · {p['height']}"
                )
                st.markdown(
                    f'<span class="tier-badge-{tier_num_p}">{TIER_LABELS[tier_num_p]}</span>',
                    unsafe_allow_html=True,
                )

            with w2:
                s = p["stats"]
                mc = st.columns(5)
                for col, (lbl, val) in zip(mc, [
                    ("PPG", s.get("PPG")), ("RPG", s.get("RPG")), ("APG", s.get("APG")),
                    ("FG%", s.get("FG%")), ("3P%", s.get("3P%")),
                ]):
                    if val is None:
                        disp = "—"
                    elif lbl == "3P%" and val == 0.0:
                        disp = "N/A"
                    elif "%" in lbl:
                        disp = f"{val:.1f}%"
                    else:
                        disp = f"{val:.1f}"
                    col.markdown(
                        f'<div class="stat-card"><div class="stat-label">{lbl}</div>'
                        f'<div class="stat-value" style="font-size:18px">{disp}</div></div>',
                        unsafe_allow_html=True,
                    )

            with w3:
                if st.button("✕ Remove", key=f"wl_rm_{p['id']}"):
                    st.session_state["watchlist"].discard(p["id"])
                    st.rerun()

            # Scout notes preview
            note = st.session_state["notes"].get(p["id"], "")
            if note:
                st.caption(f"📝 {note[:120]}{'...' if len(note) > 120 else ''}")

            st.markdown("---")

        # Export Watchlist
        wl_export = []
        for p in sorted(watched, key=lambda x: x["rank"]):
            prof = _all_profiles[p["id"]]
            wl_export.append({
                "Rank": p["rank"], "Name": p["name"], "Pos": p["pos"],
                "School": p["school"], "Conference": p.get("conference", ""),
                "Year": p["year"], "Draft Score": p.get("draft_score", 0),
                "Archetype": prof["primary"],
                "PPG": p["stats"].get("PPG"), "RPG": p["stats"].get("RPG"),
                "APG": p["stats"].get("APG"),
                "Notes": st.session_state["notes"].get(p["id"], ""),
            })
        wl_df = pd.DataFrame(wl_export)
        st.download_button(
            "📥 Download Watchlist (CSV)", wl_df.to_csv(index=False),
            file_name="watchlist.csv", mime="text/csv",
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — ARCHETYPE SCARCITY
# ══════════════════════════════════════════════════════════════════════════════
with tab_scar:
    st.markdown("### Archetype Scarcity")
    st.markdown("Draft class depth by player archetype — find the thin spots and the deep pools.")

    # Player pool slider — pull from highest ranked first
    _total_players = len(PLAYERS)
    _pool_size = st.slider(
        "Player pool size (top N prospects by draft rank)",
        min_value=15, max_value=_total_players,
        value=min(200, _total_players), step=5, key="scar_pool",
    )
    _scar_players = sorted(PLAYERS, key=lambda p: p["rank"])[:_pool_size]
    st.caption(f"Analyzing top {_pool_size} prospects (ranks #1–#{_pool_size})")

    tier_colors = {1: "#f59e0b", 2: "#3b82f6", 3: "#9ca3af"}

    # Build archetype → tier counts
    arch_counts = {}
    arch_scores = {}   # archetype → list of draft scores
    arch_top = {}      # archetype → best player
    for p in _scar_players:
        prof = _all_profiles[p["id"]]
        arch = prof["primary"]
        t = st.session_state["tiers"][p["id"]]
        if arch not in arch_counts:
            arch_counts[arch] = {1: 0, 2: 0, 3: 0}
            arch_scores[arch] = []
            arch_top[arch] = p
        arch_counts[arch][t] += 1
        arch_scores[arch].append(p.get("draft_score", 0))
        if p["rank"] < arch_top[arch]["rank"]:
            arch_top[arch] = p

    archetypes_sorted = sorted(arch_counts.keys(), key=lambda a: sum(arch_counts[a].values()), reverse=True)

    # ── Stacked bar chart by archetype ───────────────────────────────────────
    fig_arch = go.Figure()
    for tier_id, tier_label in TIER_LABELS.items():
        fig_arch.add_trace(go.Bar(
            name=tier_label,
            x=archetypes_sorted,
            y=[arch_counts[a][tier_id] for a in archetypes_sorted],
            marker_color=tier_colors[tier_id],
            text=[arch_counts[a][tier_id] if arch_counts[a][tier_id] > 0 else "" for a in archetypes_sorted],
            textposition="inside",
        ))
    fig_arch.update_layout(
        barmode="stack",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=20, b=0), height=380,
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, xanchor="center", x=0.5),
        yaxis=dict(gridcolor="rgba(128,128,128,0.15)", title="# of prospects"),
        xaxis=dict(tickangle=-45),
    )
    st.plotly_chart(fig_arch, use_container_width=True)

    # ── Archetype depth table ────────────────────────────────────────────────
    st.markdown("#### Archetype Depth")
    arch_rows = []
    for arch in archetypes_sorted:
        total = sum(arch_counts[arch].values())
        lottery = arch_counts[arch][1]
        late1 = arch_counts[arch][2]
        second = arch_counts[arch][3]
        scores = arch_scores[arch]
        avg_score = sum(scores) / len(scores) if scores else 0
        top = arch_top[arch]

        if lottery == 0 and total <= 2:
            signal = "🔴 Very Scarce"
        elif lottery == 0 and total <= 5:
            signal = "🟠 Scarce"
        elif total <= 10:
            signal = "🟡 Moderate"
        else:
            signal = "🟢 Deep"

        # Top-heavy check
        if lottery > 0 and second == 0:
            signal += " (top-heavy)"

        arch_rows.append({
            "Archetype": arch,
            "Total": total,
            "Lottery": lottery,
            "Late 1st": late1,
            "2nd Rd": second,
            "Avg Score": round(avg_score, 1),
            "Top Prospect": f"#{top['rank']} {top['name']}",
            "Depth": signal,
        })

    arch_df = pd.DataFrame(arch_rows)
    st.dataframe(arch_df, use_container_width=True, hide_index=True)

    # ── Draft Score Distribution by Archetype ────────────────────────────────
    st.markdown("---")
    st.markdown("#### Draft Score Distribution")
    st.markdown("Box plot showing the spread of draft scores per archetype.")

    # Only show archetypes with 3+ players for meaningful box plots
    box_archetypes = [a for a in archetypes_sorted if len(arch_scores[a]) >= 3]
    fig_box = go.Figure()
    for arch in box_archetypes:
        fig_box.add_trace(go.Box(
            y=arch_scores[arch], name=arch,
            boxpoints="outliers", marker_color=tier_colors[1],
        ))
    fig_box.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=20, b=0), height=350,
        yaxis=dict(gridcolor="rgba(128,128,128,0.15)", title="Draft Score"),
        xaxis=dict(tickangle=-45),
        showlegend=False,
    )
    st.plotly_chart(fig_box, use_container_width=True)

    # ── Positional Gaps ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Positional Gaps")
    st.markdown("Cross-reference of position and archetype — find where the class is thin.")

    positions = sorted(set(p["pos"] for p in _scar_players))
    gap_data = {}
    for p in _scar_players:
        prof = _all_profiles[p["id"]]
        key = (p["pos"], prof["primary"])
        if key not in gap_data:
            gap_data[key] = {"total": 0, "lottery": 0, "best_rank": 9999}
        gap_data[key]["total"] += 1
        t = st.session_state["tiers"][p["id"]]
        if t == 1:
            gap_data[key]["lottery"] += 1
        gap_data[key]["best_rank"] = min(gap_data[key]["best_rank"], p["rank"])

    gap_rows = []
    for (pos, arch), data in sorted(gap_data.items(), key=lambda x: x[1]["total"]):
        if data["total"] <= 3:  # only show thin combos
            gap_rows.append({
                "Position": pos,
                "Archetype": arch,
                "Total": data["total"],
                "In Lottery": data["lottery"],
                "Best Rank": f"#{data['best_rank']}",
                "Alert": "🔴 Gap" if data["total"] == 1 else "🟠 Thin",
            })

    if gap_rows:
        gap_df = pd.DataFrame(gap_rows).sort_values("Total")
        st.dataframe(gap_df, use_container_width=True, hide_index=True)
    else:
        st.success("No major positional gaps found in this draft class.")

    # ── Conference Archetype Distribution ────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Conference Archetype Production")
    st.markdown("Which conferences produce which archetypes.")

    conferences = sorted(set(p.get("conference", "Other") for p in _scar_players))
    # Build conference × archetype matrix
    conf_arch = {}
    for p in _scar_players:
        conf = p.get("conference", "Other")
        arch = _all_profiles[p["id"]]["primary"]
        if conf not in conf_arch:
            conf_arch[conf] = {}
        conf_arch[conf][arch] = conf_arch[conf].get(arch, 0) + 1

    conf_rows = []
    for conf in conferences:
        if conf not in conf_arch:
            continue
        dist = conf_arch[conf]
        total = sum(dist.values())
        # Top 3 archetypes for this conference
        top3 = sorted(dist.items(), key=lambda x: x[1], reverse=True)[:3]
        top_player = min(
            [p for p in _scar_players if p.get("conference") == conf],
            key=lambda x: x["rank"],
        )
        conf_rows.append({
            "Conference": conf,
            "Prospects": total,
            "Top Archetypes": ", ".join(f"{a} ({n})" for a, n in top3),
            "Top Prospect": f"#{top_player['rank']} {top_player['name']}",
        })

    conf_df = pd.DataFrame(conf_rows).sort_values("Prospects", ascending=False)
    st.dataframe(conf_df, use_container_width=True, hide_index=True)
