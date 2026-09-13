"""Tests for the vector store's document building (execution plan W6 D3-D4).

    pytest tests/test_vectordb.py -q

No embedding and no Chroma: what is pinned is how the project's tables and docs become
retrievable units, which is the part that decides whether retrieval answers anything.
The index build itself is exercised by `python -m src.common.vectordb --build`.
"""

from __future__ import annotations

import pandas as pd

from src.common import vectordb

AUDIT_ROW = {
    "corridor_id": "INDA>INDB", "n_legs": 41, "source_name": "Kanpur_Central_D",
    "destination_name": "Agra_Hub_2", "source_city": "Kanpur", "dest_city": "Agra",
    "source_state": "Uttar Pradesh", "dest_state": "Uttar Pradesh",
    "mean_osrm_time": 120.0, "mean_actual_time": 200.0, "median_gap_ratio": 1.62,
    "excess_ratio": 1.4, "is_significant": True, "direction": "worse",
    "q_value": 0.0012, "bottleneck_rank": 12, "ftl_share": 0.75,
}

HUB_ROW = {
    "friction_rank": 1, "centre_code": "INDX", "city": "Aluva", "state": "Kerala",
    "n_legs_out": 86, "n_corridors_out": 7, "median_dwell_share_out": 0.82,
    "median_dwell_min_out": 350.0, "p90_dwell_min_out": 467.0, "chain_break_rate": 0.11,
}


def _csv(tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# ── corridors ───────────────────────────────────────────────────────────────
def test_a_corridor_becomes_a_sentence_not_a_row(tmp_path):
    doc = vectordb.corridor_documents(_csv(tmp_path, "audit.csv", [AUDIT_ROW]))[0]
    assert "INDA>INDB" in doc.text
    assert "41 legs" in doc.text
    assert "1.40 times" in doc.text
    assert "bottleneck rank 12" in doc.text
    assert doc.id == "corridor::INDA>INDB"


def test_the_direction_is_spelled_out_for_a_reader(tmp_path):
    # "worse" is the audit's word (P-48 is what happens when that word travels raw);
    # a retrieval answer has to say what it means.
    rows = [dict(AUDIT_ROW), dict(AUDIT_ROW, corridor_id="INDC>INDD", direction="better")]
    docs = vectordb.corridor_documents(_csv(tmp_path, "audit.csv", rows))
    assert "slower than the network" in docs[0].text
    assert "faster than the network" in docs[1].text


def test_an_untested_corridor_says_it_is_not_distinguishable(tmp_path):
    row = dict(AUDIT_ROW, is_significant=False)
    doc = vectordb.corridor_documents(_csv(tmp_path, "audit.csv", [row]))[0]
    assert "not statistically distinguishable" in doc.text


def test_corridor_metadata_carries_the_filters_a_query_would_use(tmp_path):
    doc = vectordb.corridor_documents(_csv(tmp_path, "audit.csv", [AUDIT_ROW]))[0]
    assert doc.metadata["kind"] == "corridor"
    assert doc.metadata["n_legs"] == 41
    assert doc.metadata["is_significant"] is True


def test_a_missing_audit_file_is_survivable(tmp_path):
    assert vectordb.corridor_documents(tmp_path / "nope.csv") == []


# ── hubs ────────────────────────────────────────────────────────────────────
def test_a_hub_document_names_its_rank_and_dwell(tmp_path):
    doc = vectordb.hub_documents(_csv(tmp_path, "friction.csv", [HUB_ROW]))[0]
    assert "rank 1" in doc.text and "350 minutes" in doc.text and "Aluva" in doc.text
    assert doc.metadata == {"kind": "hub", "centre_code": "INDX", "friction_rank": 1}


# ── markdown splitting ──────────────────────────────────────────────────────
def test_a_section_is_kept_with_its_heading():
    text = "# Title\n\nintro\n\n## D-001 A decision\n\n" + ("body. " * 60) + "\n\n## D-002 Another\n\n" + ("more. " * 60)
    docs = vectordb.split_markdown(text, "decisions.md")
    assert len(docs) == 2
    assert docs[0].metadata["heading"].startswith("D-001")
    assert "body." in docs[0].text
    assert "D-002" not in docs[0].text


def test_a_short_section_folds_forward_rather_than_being_indexed_alone():
    # A heading with two lines under it retrieves against everything and answers nothing.
    text = "## Tiny\n\nshort\n\n## Real\n\n" + ("body. " * 60)
    docs = vectordb.split_markdown(text, "x.md")
    assert len(docs) == 1
    assert "Tiny" in docs[0].text and "Real" in docs[0].text


def test_a_document_with_no_headings_yields_at_most_one_chunk():
    assert len(vectordb.split_markdown("just prose. " * 40, "x.md")) <= 1


def test_chunks_get_unique_ids():
    text = "".join(f"## Section {i}\n\n" + ("body. " * 60) + "\n\n" for i in range(5))
    docs = vectordb.split_markdown(text, "x.md")
    assert len({d.id for d in docs}) == len(docs)


def test_every_document_kind_is_labelled(tmp_path):
    docs = (
        vectordb.corridor_documents(_csv(tmp_path, "a.csv", [AUDIT_ROW]))
        + vectordb.hub_documents(_csv(tmp_path, "f.csv", [HUB_ROW]))
        + vectordb.split_markdown("## H\n\n" + ("b. " * 80), "x.md")
    )
    assert {d.metadata["kind"] for d in docs} == {"corridor", "hub", "doc"}
    assert len({d.id for d in docs}) == len(docs)
