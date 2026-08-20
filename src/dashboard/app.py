"""Streamlit control tower — Week 1 skeleton.

    streamlit run src/dashboard/app.py

Navigation and the shared data-loading layer for every page that lands in Weeks 2-7.
Pages that have no data yet say so and name the week and owner that fill them, so the
skeleton is honest about what exists rather than showing placeholder charts.

**The dashboard reads only cached artefacts** — Parquet under ``data/processed`` and
CSVs under ``benchmarks/raw``. It never reads ``data/raw`` and never runs Spark. That
rule is what keeps it responsive during the live demo.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.common import config

st.set_page_config(
    page_title="Agentic AI Logistics Control Tower",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

CITY_COORDS = Path(__file__).parent / "reference" / "india_city_coords.csv"


# ── Cached loaders ───────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_csv(path: Path) -> pd.DataFrame | None:
    return pd.read_csv(path) if path.exists() else None


@st.cache_data(show_spinner=False)
def load_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@st.cache_data(show_spinner=False)
def load_city_coords() -> pd.DataFrame:
    """Facility-name prefix → canonical city, state, lat/lon.

    Hand-maintained because the dataset's city prefixes are inconsistent: `Bangalore`
    and `Bengaluru` both occur, `MAA` means Chennai and `FBD` means Faridabad. The
    Week 2 India map joins through this table, so an unmapped city is a silently
    missing dot — `coverage_report()` exists to make that visible instead.
    """
    return pd.read_csv(CITY_COORDS)


def city_of(facility_name: object) -> str | None:
    """`Anand_VUNagar_DC (Gujarat)` → `Anand`, `Mumbai Hub (Maharashtra)` → `Mumbai`.

    Two naming shapes occur and only the first was handled originally. Most rows are
    `City_Facility_Type (State)`, but 9 facilities separate the city with a space
    instead — those came through as null cities in the Week 2 audit and would have
    been silently missing dots here. Splitting on either separator covers both.
    """
    if not isinstance(facility_name, str) or not facility_name:
        return None
    head = facility_name.split("(")[0]          # drop the trailing "(State)"
    return re.split(r"[_\s]", head.strip(), maxsplit=1)[0].strip() or None


def coverage_report(names: pd.Series) -> tuple[int, int, list[str]]:
    """(mapped, total, unmapped city names) for a series of facility names."""
    coords = load_city_coords()
    known = set(coords["raw_city"])
    cities = names.dropna().map(city_of).dropna()
    unmapped = sorted(set(cities) - known)
    mapped = int(cities.isin(known).sum())
    return mapped, len(cities), unmapped


# ── India map ────────────────────────────────────────────────────────────────
# A diverging ramp, because `excess_ratio` has a real midpoint: 1.0 is a corridor
# that overruns exactly as much as the network typically does. Red arm = worse than
# that, blue arm = better, and the two arms carry the same number of steps so neither
# direction looks more finely resolved than the other. Line weight repeats the
# magnitude so severity survives a colourblind read; the two directions are also
# separated by dash pattern, never by hue alone.
SEVERITY_BINS = [
    #  upper bound, colour,     weight, label
    (1.20, "#ec9694", 2.5, "1.00–1.20× — mildly worse"),
    (1.50, "#e34948", 4.0, "1.20–1.50× — clearly worse"),
    (99.0, "#a02726", 5.5, "1.50×+ — worst corridors"),
]
FASTER_BINS = [
    (0.75, "#104281", 5.5, "under 0.75× — much better"),
    (0.90, "#2a78d6", 4.0, "0.75–0.90× — clearly better"),
    (1.00, "#86b6ef", 2.5, "0.90–1.00× — mildly better"),
]

SEVERITY_LEGEND = """
<div style="display:flex;flex-wrap:wrap;gap:1.5rem;font-size:0.85rem;line-height:1.6">
  <div>
    <b>Slower than the network</b> — solid<br>
    <span style="color:#ec9694">&#9644;&#9644;</span> 1.00–1.20&times;&nbsp;
    <span style="color:#e34948">&#9644;&#9644;</span> 1.20–1.50&times;&nbsp;
    <span style="color:#a02726">&#9644;&#9644;</span> 1.50&times;+
  </div>
  <div>
    <b>Faster than the network</b> — dashed<br>
    <span style="color:#86b6ef">&#9644;&#9644;</span> 0.90–1.00&times;&nbsp;
    <span style="color:#2a78d6">&#9644;&#9644;</span> 0.75–0.90&times;&nbsp;
    <span style="color:#104281">&#9644;&#9644;</span> under 0.75&times;
  </div>
</div>
"""


def severity_style(excess: float, direction: str) -> tuple[str, float]:
    """(colour, line weight) for one corridor's effect size."""
    bins = SEVERITY_BINS if direction == "worse" else FASTER_BINS
    for upper, colour, weight, _ in bins:
        if excess <= upper:
            return colour, weight
    return bins[-1][1], bins[-1][2]


@st.cache_data(show_spinner=False)
def locate_corridors(audit: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Attach lat/lon to both ends of every audited corridor.

    Cities are re-derived from the raw facility names rather than read from the
    audit's own city columns: the audit's parser nulls the space-separated names,
    and a null city here is a corridor silently absent from the map.
    """
    coords = load_city_coords().drop_duplicates("raw_city").set_index("raw_city")
    df = audit.copy()
    df["source_city"] = df["source_name"].map(city_of)
    df["dest_city"] = df["destination_name"].map(city_of)

    for end, col in (("src", "source_city"), ("dst", "dest_city")):
        joined = df[col].map(coords["canonical_city"])
        df[f"{end}_name"] = joined
        df[f"{end}_lat"] = df[col].map(coords["lat"])
        df[f"{end}_lon"] = df[col].map(coords["lon"])

    df["intra_city"] = df["src_name"] == df["dst_name"]
    placed = df["src_lat"].notna() & df["dst_lat"].notna()
    missing = sorted(
        {c for c in pd.concat([df.loc[~placed, "source_city"], df.loc[~placed, "dest_city"]])
         if isinstance(c, str) and c not in coords.index}
    )
    return df[placed], missing


def city_severity(corridors: pd.DataFrame) -> pd.DataFrame:
    """Audited corridors rolled up to the city they leave from.

    The rollup is not cosmetic. 19 of the 34 bottlenecks start and end in the same
    city and 33 of 34 span under 50 km, so drawn as great-circle lines they are
    zero-length marks at national zoom — the worst corridors in the network would be
    the ones you cannot see. Severity belongs to the city here, and the lines below
    are the minority of corridors that genuinely cross a distance.
    """
    g = corridors.groupby("src_name", as_index=False).agg(
        lat=("src_lat", "first"),
        lon=("src_lon", "first"),
        corridors=("corridor_id", "size"),
        legs=("n_legs", "sum"),
        worst=("excess_ratio", lambda x: x.max() if x.mean() >= 1 else x.min()),
        mean_excess=("excess_ratio", "mean"),
        intra=("intra_city", "sum"),
    )
    return g.sort_values("corridors")


def severity_map(corridors: pd.DataFrame) -> folium.Map:
    """Cities sized by how many audited corridors leave them, coloured by severity.

    Long corridors keep a line as well, drawn under the bubbles. Worst drawn last so
    the darkest marks sit on top where cities overlap.
    """
    m = folium.Map(location=[22.0, 79.0], zoom_start=5, tiles="CartoDB positron")

    spans = corridors[~corridors["intra_city"]]
    for _, r in spans.sort_values("excess_ratio").iterrows():
        colour, weight = severity_style(r["excess_ratio"], r["direction"])
        folium.PolyLine(
            [(r["src_lat"], r["src_lon"]), (r["dst_lat"], r["dst_lon"])],
            color=colour,
            weight=weight * 0.6,
            opacity=0.55,
            dash_array=None if r["direction"] == "worse" else "6,6",
            tooltip=(
                f"<b>{r['src_name']} &rarr; {r['dst_name']}</b><br>"
                f"<code>{r['corridor_id']}</code><br>"
                f"{r['excess_ratio']:.2f}&times; the network's typical overrun"
            ),
        ).add_to(m)

    cities = city_severity(corridors)
    for _, c in cities.iterrows():
        direction = "worse" if c["mean_excess"] >= 1 else "better"
        colour, _ = severity_style(c["worst"], direction)
        folium.CircleMarker(
            [c["lat"], c["lon"]],
            radius=5 + 2.6 * math.sqrt(c["corridors"]),
            color="#52514e",
            weight=1,
            fill=True,
            fill_color=colour,
            fill_opacity=0.85,
            tooltip=folium.Tooltip(
                f"<b>{c['src_name']}</b><br>"
                f"{int(c['corridors'])} audited corridor(s) &middot; "
                f"{int(c['legs']):,} legs<br>"
                f"worst {c['worst']:.2f}&times; &middot; mean {c['mean_excess']:.2f}&times;<br>"
                f"{int(c['intra'])} of them intra-city"
            ),
        ).add_to(m)

    pts = pd.concat([
        corridors[["src_lat", "src_lon"]].rename(columns={"src_lat": "lat", "src_lon": "lon"}),
        corridors[["dst_lat", "dst_lon"]].rename(columns={"dst_lat": "lat", "dst_lon": "lon"}),
    ]).dropna()
    if len(pts) > 1:
        m.fit_bounds([[pts.lat.min(), pts.lon.min()], [pts.lat.max(), pts.lon.max()]], padding=(30, 30))
    return m


# ── Hub friction ─────────────────────────────────────────────────────────────
# One measure, one hue — a leaderboard compares magnitude within a single series, so
# there is nothing for a second colour to mean and no legend to carry. Bars are direct-
# labelled instead of carrying a value axis, and the axis lines stay recessive.
INK_PRIMARY, INK_MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"
BAR_HUE = "#2a78d6"


def hub_bars(top: pd.DataFrame, col: str) -> go.Figure:
    """Horizontal bars for the ranked hubs, labelled at the end of each bar."""
    is_share = col.endswith("share_out")
    # `IND400072AAD` -> `Mumbai · 400072AAD`: several facilities share a city, so the
    # city alone would put two identical rows on the chart. The PIN carries the
    # distinction in a form a reader can place; the `IND` prefix is constant noise.
    labels = [
        f"{c} · {code[3:]}" if c else code
        for code, c in zip(top["centre_code"], top["city"].fillna(""), strict=True)
    ]
    text = [f"{v:.0%}" if is_share else f"{v:,.0f} min" for v in top[col]]

    fig = go.Figure(
        go.Bar(
            x=top[col],
            y=labels,
            orientation="h",
            marker={"color": BAR_HUE, "line": {"width": 0}},
            text=text,
            textposition="outside",
            textfont={"color": INK_PRIMARY, "size": 12},
            hovertemplate=(
                "<b>%{y}</b><br>"
                + ("dwell share %{x:.0%}" if is_share else "dwell %{x:,.0f} min")
                + "<extra></extra>"
            ),
            cliponaxis=False,
        )
    )
    fig.update_layout(
        height=28 * len(top) + 90,
        margin={"l": 210, "r": 72, "t": 8, "b": 34},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        bargap=0.45,
        showlegend=False,
        xaxis={
            "showgrid": True,
            "gridcolor": "#eceae4",
            "zeroline": False,
            "tickformat": ".0%" if is_share else ",",
            "tickfont": {"color": INK_MUTED, "size": 11},
            "title": {
                "text": "median share of a leg's wall clock spent stationary"
                if is_share
                else "median dwell minutes per outbound leg",
                "font": {"color": INK_MUTED, "size": 11},
            },
        },
        yaxis={"showgrid": False, "tickfont": {"color": INK_PRIMARY, "size": 11}},
    )
    return fig


def pending(week: str, owner: str, what: str) -> None:
    """Uniform 'not built yet' panel. Honest beats a fake chart."""
    st.info(f"**Not built yet — {week}, {owner}.**\n\n{what}")


# ── Sidebar ──────────────────────────────────────────────────────────────────
PAGES = [
    "Overview",
    "Corridor audit",
    "India map",
    "Hub friction",
    "Delay predictor",
    "Live alerts",
    "Agent console",
    "Analytics assistant",
    "Prompt library",
]

st.sidebar.title("🚚 Control Tower")
st.sidebar.caption("Agentic AI Logistics Control Tower")
page = st.sidebar.radio("Page", PAGES, label_visibility="collapsed")
st.sidebar.divider()


def artefact_status() -> list[tuple[str, bool, str]]:
    return [
        ("Cleaned Parquet (W1)", config.CLEAN_V1.exists(), "python -m src.pipeline.clean"),
        ("Leg summary (W1)", (config.BENCHMARKS_RAW_DIR / "w1_leg_summary.csv").exists(), "python -m src.ml.eda"),
        ("Corridor support (W1)", (config.BENCHMARKS_RAW_DIR / "w1_corridor_support.csv").exists(), "python -m src.ml.eda"),
        ("Corridor audit (W2)", (config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv").exists(), "week 2"),
        ("Feature table (W3)", config.FEATURES_V1.exists(), "week 3"),
        ("Trained model (W4)", (config.MODELS_DIR / "champion").exists(), "week 4"),
    ]


st.sidebar.subheader("Artefacts")
for label, exists, how in artefact_status():
    st.sidebar.write(f"{'✅' if exists else '⬜'} {label}")
    if not exists:
        st.sidebar.caption(f"    `{how}`")


# ── Pages ────────────────────────────────────────────────────────────────────
if page == "Overview":
    st.title("Agentic AI Logistics Control Tower")
    st.caption(
        "A multi-agent digital workforce on a distributed big-data delay-prediction "
        "pipeline, built on real Delhivery network data."
    )

    legs = load_csv(config.BENCHMARKS_RAW_DIR / "w1_leg_summary.csv")
    if legs is None:
        pending("Week 1", "Lahari", "Run `python -m src.ml.eda` to build the leg-level summary.")
    else:
        gap_ratio = legs["actual_time"] / legs["osrm_time"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("OD legs", f"{len(legs):,}")
        c2.metric("Corridors", f"{legs['corridor_id'].nunique():,}")
        c3.metric("Legs over plan", f"{(gap_ratio > 1).mean() * 100:.1f}%")
        c4.metric("Median time vs plan", f"{gap_ratio.median():.2f}×")

        st.subheader("The finding Week 1 established")
        st.markdown(
            f"""
The production OSRM routing engine under-predicts on **{(gap_ratio > 1).mean() * 100:.1f}%**
of legs, and the median leg takes **{gap_ratio.median():.2f}×** its planned time
(median gap **{(legs['actual_time'] - legs['osrm_time']).median():,.0f} min**).

That one-sidedness is the project's premise: the planner's error is *systematic*, not
noise, so it should be localisable to specific corridors — which is what the Week 2
audit tests, corridor by corridor, with significance testing.
"""
        )

        st.subheader("Distribution of realised time vs plan")
        # Bin explicitly to numeric centres: value_counts(bins=) yields an Interval
        # index, which the chart layer cannot type and renders as unordered categories.
        counts, edges = np.histogram(gap_ratio.clip(upper=8), bins=40, range=(0, 8))
        st.bar_chart(
            pd.DataFrame({"legs": counts}, index=pd.Index(((edges[:-1] + edges[1:]) / 2).round(2), name="realised / planned")),
            height=260,
        )
        st.caption("Clipped at 8× for display. A well-calibrated planner would peak at 1.0.")

elif page == "Corridor audit":
    st.title("Corridor audit")
    audit = load_csv(config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv")
    if audit is None:
        support = load_csv(config.BENCHMARKS_RAW_DIR / "w1_corridor_support.csv")
        pending(
            "Week 2",
            "Lahari",
            "Significance-tested actual-vs-OSRM gap per corridor, with Benjamini-Hochberg "
            "correction and a minimum-support threshold. Week 1's raw corridor table is "
            "shown below in the meantime — **ranked by traffic, not by badness.**",
        )
        if support is not None:
            st.dataframe(support.head(50), use_container_width=True, hide_index=True)
    else:
        st.dataframe(audit, use_container_width=True, hide_index=True)

elif page == "India map":
    st.title("India map — corridors by delay severity")
    audit = load_csv(config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv")

    if audit is None:
        pending(
            "Week 2",
            "Lahari",
            "The map draws Lahari's audited corridors. Run `python -m src.ml.audit` to "
            "build `benchmarks/raw/w2_corridor_audit.csv`, then reload.",
        )
    else:
        drawn, missing = locate_corridors(audit)
        sig = drawn[drawn["is_significant"]]

        st.caption(
            "Each line is a corridor whose overrun differs from the rest of the network "
            "at FDR 0.05 (Lahari's audit, D-002 grain). **Colour is the effect size, not "
            "the delay** — `excess_ratio` reads as this corridor's typical overrun as a "
            "multiple of the network's own, so 1.0 is an ordinary corridor on a network "
            "that already runs at twice its plan."
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("Corridors drawn", f"{len(sig)} of {int(audit['is_significant'].sum())}")
        c2.metric("Slower than the network", f"{int((sig['direction'] == 'worse').sum())}")
        c3.metric("Faster than the network", f"{int((sig['direction'] == 'better').sum())}")

        show = st.radio(
            "Show",
            ["Bottlenecks only", "Both directions", "Faster only"],
            horizontal=True,
            help="The audit found the planner wrong in both directions. Showing only the "
            "slow half would misdescribe it.",
        )
        keep = {"Bottlenecks only": ["worse"], "Faster only": ["better"]}.get(
            show, ["worse", "better"]
        )
        plot = sig[sig["direction"].isin(keep)]

        st_folium(severity_map(plot), use_container_width=True, height=560, returned_objects=[])
        st.markdown(SEVERITY_LEGEND, unsafe_allow_html=True)
        st.caption(
            f"**A bubble is a city, not a route.** {int(plot['intra_city'].sum())} of the "
            f"{len(plot)} corridors shown start and end in the same city, and almost all the "
            "rest are metro-fringe hops under 50 km — drawn as lines on a map of India they "
            "would be marks of zero length. Bubble size is how many audited corridors leave "
            "the city; colour is the worst effect size among them. Lines are drawn only for "
            "corridors that actually cross a distance, are great-circle and **not routed**: "
            "a corridor is a pair of facilities (D-002), so the line says which pair, not "
            "which road. Several facility pairs collapse onto one city pair, which is why "
            "`Delhi → Gurgaon` appears as both a bottleneck and a fast corridor."
        )

        with st.expander(f"The {len(plot)} corridors on the map"):
            cols = [
                "source_city", "dest_city", "corridor_id", "n_legs",
                "median_gap_ratio", "excess_ratio", "mean_gap_min", "q_value",
            ]
            st.dataframe(
                plot[cols].sort_values("excess_ratio", ascending=False),
                use_container_width=True, hide_index=True,
            )

        st.subheader("Coordinate coverage")
        if missing:
            st.warning(
                f"{len(missing)} corridor(s) could not be placed: "
                + ", ".join(sorted(missing)[:20])
            )
            st.caption("Add rows to `src/dashboard/reference/india_city_coords.csv`.")
        else:
            st.success(
                f"All {len(drawn)} audited corridors resolve to coordinates. The lookup "
                "carries the aliases that make that true — `Bangalore`/`Bengaluru`, "
                "`AMD`/`Amd`/`Amdavad`→Ahmedabad, `MAA`→Chennai, `GGN`→Gurugram — and "
                "`city_of()` handles the nine facilities that separate the city with a "
                "space (`Mumbai Hub (Maharashtra)`) rather than an underscore."
            )
        with st.expander(f"City-coordinate lookup ({len(load_city_coords())} prefixes)"):
            st.dataframe(load_city_coords(), use_container_width=True, hide_index=True)

elif page == "Hub friction":
    st.title("Hub friction — where shipments sit still")
    hubs = load_csv(config.BENCHMARKS_RAW_DIR / "w2_hub_dwell.csv")

    if hubs is None:
        pending(
            "Week 2",
            "Mounika",
            "Run `python -m src.pipeline.hubs` to build "
            "`benchmarks/raw/w2_hub_dwell.csv`, then reload.",
        )
    else:
        ranked = hubs[hubs["friction_rank"].notna()]
        st.caption(
            "Dwell is measured **inside** a leg — `start_scan_to_end_scan − actual_time`, "
            "the part of a leg's wall clock the shipment was not moving (D-015). The gap "
            "*between* legs is not dwell: the publisher closes one leg's window as it opens "
            "the next, so on a continuous handoff there is structurally nothing to measure."
        )

        c1, c2, c3 = st.columns(3)
        # the CSV carries only the ranked hubs, so "N of len(hubs)" would read "121 of 121"
        c1.metric("Hubs ranked", f"{len(ranked)}", help="Facilities with ≥30 outbound legs (D-015)")
        c2.metric("Median dwell share", f"{ranked['median_dwell_share_out'].median():.0%}")
        c3.metric("Worst hub", f"{ranked['median_dwell_share_out'].max():.0%}")

        metric = st.radio(
            "Rank by",
            ["Dwell share (D-015)", "Raw dwell minutes"],
            horizontal=True,
            help="The two rankings disagree. Switching shows how much.",
        )
        col = ("median_dwell_share_out" if metric.startswith("Dwell share")
               else "median_dwell_min_out")
        top = ranked.nlargest(20, col).iloc[::-1]
        st.plotly_chart(hub_bars(top, col), use_container_width=True)

        share_top = set(ranked.nlargest(20, "median_dwell_share_out")["centre_code"])
        min_top = set(ranked.nlargest(20, "median_dwell_min_out")["centre_code"])
        rho = ranked["median_dwell_share_out"].corr(
            ranked["median_dwell_min_out"], method="spearman"
        )
        st.info(
            f"**Why share, not minutes (D-015).** The two rankings share only "
            f"**{len(share_top & min_top)} of their top 20** hubs (Spearman {rho:.2f}) — flip "
            "the toggle and most of the leaderboard changes. Lahari's audit settled it against "
            "a column neither metric is built from: raw minutes correlate **+0.55** with how "
            "long a hub's legs are *planned* to take, so a leaderboard on minutes would "
            "substantially rank hubs by the length of the legs they happen to serve. Dwell "
            "share runs **−0.30** against the same column."
        )

        st.subheader("Dispatch is not receipt")
        both = ranked[["median_dwell_share_out", "median_dwell_share_in"]].dropna()
        st.caption(
            f"A leg's idle minutes cannot be split between its two ends from leg-grain data, "
            f"so both ends are credited and reported separately. Across ranked hubs the two "
            f"series correlate only **{both.corr(method='spearman').iloc[0, 1]:.2f}** — a hub "
            "can be slow to dispatch and quick to receive, and one number would hide that."
        )

        cols = [
            "friction_rank", "centre_code", "city", "state", "n_legs_out",
            "median_dwell_share_out", "median_dwell_min_out", "p90_dwell_min_out",
            "median_dwell_share_in", "chain_break_rate",
        ]
        st.dataframe(
            ranked.sort_values("friction_rank")[cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "friction_rank": st.column_config.NumberColumn("#", format="%d"),
                "median_dwell_share_out": st.column_config.ProgressColumn(
                    "Dwell share (out)", format="%.0f%%", min_value=0, max_value=1
                ),
                "median_dwell_share_in": st.column_config.NumberColumn(
                    "Dwell share (in)", format="%.2f"
                ),
                "chain_break_rate": st.column_config.NumberColumn(
                    "Chain breaks", format="%.2f",
                    help="Share of handoffs where the shipment reappears at a facility it "
                         "never travelled to — a data-quality signal, not dwell (D-015).",
                ),
            },
        )
        st.caption(
            "**Hub friction is not corridor friction.** Neither dwell metric tracks the "
            "overrun of the corridors leaving the hub (−0.05 and −0.00 against "
            "`excess_ratio`). The India map and this leaderboard are two separate claims."
        )

elif page == "Delay predictor":
    st.title("What-if delay predictor")
    pending("Week 4", "Krishna", "Enter a shipment, get the trained model's predicted delay.")

elif page == "Live alerts":
    st.title("Live alerts")
    pending(
        "Week 5",
        "Krishna / Mounika",
        "Alerts from the Kafka → Structured Streaming pipeline, with the flagged "
        "shipment, its corridor, and the predicted delay.",
    )

elif page == "Agent console":
    st.title("Agent console")
    pending(
        "Week 7",
        "Krishna",
        "Every agent call traced with inputs and outputs — the monitoring deliverable.",
    )

elif page == "Analytics assistant":
    st.title("Analytics assistant")
    pending(
        "Week 7",
        "Krishna",
        "RAG over the vector DB holding audit tables and results docs. Refuses "
        "out-of-scope questions; scored on groundedness over a fixed 30-question set.",
    )
    st.caption("Week 1 precursor: `python -m src.agents.hello_agent` runs the same graph shape.")

elif page == "Prompt library":
    st.title("Prompt library")
    st.caption("GIT_RULES §1 — prompt versions are never overwritten, so results stay comparable.")
    try:
        from src.agents.prompts.registry import inventory, load_prompt

        inv = inventory()
        for agent, versions in inv.items():
            with st.expander(f"**{agent}** — {', '.join(versions) if versions else 'no versions yet'}"):
                if not versions:
                    st.caption("Lands in a later week; see the folder's `_README.md`.")
                    continue
                chosen = st.selectbox("Version", versions, index=len(versions) - 1, key=agent)
                st.code(load_prompt(agent, chosen).text, language="markdown")
    except ImportError as exc:
        st.warning(f"Prompt registry unavailable: {exc}")

st.divider()
quality = load_json(config.CLEAN_V1 / "_quality_report.json")
if quality:
    st.caption(
        f"Cleaned cache: {quality['rows_out']:,} of {quality['rows_in']:,} rows kept · "
        f"{quality['distinct']['corridor_id']:,} corridors · built {quality['generated_at'][:16]}"
    )
else:
    st.caption("No cleaned Parquet cache yet — run `python -m src.pipeline.clean`.")
