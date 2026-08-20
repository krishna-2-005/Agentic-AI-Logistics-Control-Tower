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
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

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
    pending(
        "Week 2",
        "Krishna",
        "Folium map of corridors coloured by audited delay severity, drawn from the "
        "Week 2 audit table and the city-coordinate lookup.",
    )
    coords = load_city_coords()
    st.subheader("City-coordinate lookup")
    st.caption(
        f"{len(coords)} facility-name prefixes mapped to {coords['canonical_city'].nunique()} "
        "canonical cities. Aliases are the point: `Bangalore`/`Bengaluru`, `MAA`→Chennai, "
        "`FBD`→Faridabad all resolve to one dot."
    )
    st.dataframe(coords, use_container_width=True, hide_index=True, height=300)

    support = load_csv(config.BENCHMARKS_RAW_DIR / "w1_corridor_support.csv")
    if support is not None:
        mapped, total, unmapped = coverage_report(support["source_name"])
        st.metric("Corridor sources resolvable to coordinates", f"{mapped / total * 100:.1f}%")
        if unmapped:
            with st.expander(f"{len(unmapped)} unmapped city prefixes"):
                st.write(", ".join(unmapped[:200]))
                st.caption("Add rows to `src/dashboard/reference/india_city_coords.csv` to map these.")

elif page == "Hub friction":
    st.title("Hub friction")
    pending(
        "Week 2",
        "Mounika",
        "Dwell time between segments, ranked per hub. Week 1 already established that "
        "`start_scan_to_end_scan − actual_time` is dwell (median ~49 min per leg), so "
        "this needs no new columns — only the Spark reconstruction.",
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
