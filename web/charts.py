"""Plotly chart JSON + display formatting helpers."""

import plotly.graph_objects as go

_RADAR_COLORS = [
    ("#f59e0b", "rgba(245,158,11,0.12)"),
    ("#3b82f6", "rgba(59,130,246,0.12)"),
    ("#10b981", "rgba(16,185,129,0.12)"),
    ("#ef4444", "rgba(239,68,68,0.12)"),
    ("#8b5cf6", "rgba(139,92,246,0.12)"),
    ("#ec4899", "rgba(236,72,153,0.12)"),
]


def make_radar_json(*players) -> str:
    if not players:
        return "{}"
    cats = list(players[0]["skills"].keys())
    cats_c = cats + [cats[0]]
    fig = go.Figure()
    for i, p in enumerate(players):
        vals = list(p["skills"].values()) + [list(p["skills"].values())[0]]
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
