"""Plotly chart JSON + display formatting helpers."""

import plotly.graph_objects as go

# Birddog palette: hunter orange leads, then field-muted companions
_RADAR_COLORS = [
    ("#e8662a", "rgba(232,102,42,0.14)"),
    ("#7fb2d9", "rgba(127,178,217,0.12)"),
    ("#57b27e", "rgba(87,178,126,0.12)"),
    ("#d9a521", "rgba(217,165,33,0.12)"),
    ("#d65745", "rgba(214,87,69,0.12)"),
    ("#ece5d3", "rgba(236,229,211,0.10)"),
]


# Radar axes from the MEASURED strengths (class-relative percentiles) when
# available; the legacy hand-rolled skills only as fallback for players
# outside the draft pool.
_RADAR_AXES = [
    ("Scoring", "scoring"), ("Shooting", "shooting"), ("Playmaking", "playmaking"),
    ("Finishing", "finishing"), ("Rebounding", "rebounding"),
    ("Rim Protection", "rim_protection"), ("Perimeter D", "perimeter_defense"),
    ("Ball Security", "ball_security"),
]


def _axes(p: dict) -> dict:
    s = p.get("strengths")
    if s:
        return {label: (s.get(k) if s.get(k) is not None else 0)
                for label, k in _RADAR_AXES}
    return p.get("skills", {})


def make_radar_json(*players) -> str:
    if not players:
        return "{}"
    # Mixed sources don't compare — use strengths only if every player has them
    use_strengths = all(p.get("strengths") for p in players)
    axes = [_axes(p) if use_strengths else p.get("skills", {}) for p in players]
    if not axes[0]:
        return "{}"
    cats = list(axes[0].keys())
    cats_c = cats + [cats[0]]
    fig = go.Figure()
    for i, p in enumerate(players):
        vals = list(axes[i].values()) + [list(axes[i].values())[0]]
        lc, fc = _RADAR_COLORS[i % len(_RADAR_COLORS)]
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=cats_c, fill="toself", name=p["name"],
            line_color=lc, fillcolor=fc,
        ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=False,
                            gridcolor="rgba(128,128,128,0.2)"),
            angularaxis=dict(gridcolor="rgba(128,128,128,0.2)"),
            bgcolor="rgba(0,0,0,0)",
        ),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Barlow, sans-serif", color="#d5cfc0"),
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        height=360,
    )
    return fig.to_json()


def fmt_stat(val, label) -> str:
    if val is None:
        return "—"
    if label == "3P%" and val == 0.0:
        return "N/A"
    if "%" in label:
        return f"{val:.1f}%"
    if label == "GS":
        return str(int(val))
    return f"{val:.1f}"
