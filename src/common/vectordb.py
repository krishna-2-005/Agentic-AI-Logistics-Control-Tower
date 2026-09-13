"""Vector store over the project's own knowledge (execution plan W6 D3-D4).

    python -m src.common.vectordb --build
    python -m src.common.vectordb --query "which corridors are worst for delays"
    python -m src.common.vectordb --stats

Indexes three things the project already knows and cannot currently be asked in
sentences:

* **every audited corridor** (Week 2) -- one document per corridor, with its verdict,
  its overrun and its rank;
* **the hub friction table** -- one per congested centre;
* **the documentation** -- `docs/*.md` split at its own headings, so decisions and
  problems are retrievable by what they say rather than by their number.

Built for Week 7's RAG assistant, and exposed now as an MCP tool so the agents can use
it this week.

Why a document per corridor rather than a document per table
------------------------------------------------------------
A retrieval answer is only as good as the unit it retrieves. "Here is the corridor audit
CSV" answers nothing; "IND283104AAA>IND209304AAA runs 1.4x the network's typical
overrun over 41 legs, confirmed significant, bottleneck rank 12" is an answer on its
own. The same reasoning splits the docs at headings instead of at a fixed character
count: a decision entry is a unit of meaning, and cutting it in half mid-argument
retrieves the half that does not contain the decision.

Embeddings
----------
Chroma's default, a small ONNX MiniLM that runs on CPU and is **downloaded once on
first build**. That download is the only network dependency in this module, and
`--build` says so before it starts. `sentence-transformers` is deliberately *not* used:
it pulls ~2.5 GB of torch onto a machine with about 5.6 GB of usable RAM, for an
embedding of the same family.

This is a retrieval index, not a source of truth. Every document it holds is generated
from a table or a file that remains the authority; rebuilding is always safe, and
nothing reads from here to compute a number.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("common.vectordb")

COLLECTION = "control-tower"
AUDIT_CSV = config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv"
FRICTION_CSV = config.BENCHMARKS_RAW_DIR / "w2_hub_friction_top20.csv"
DOCS_DIR = config.DOCS_DIR

#: Headings split a document; anything shorter than this is folded into the next chunk
#: rather than indexed alone. A three-word heading retrieves against everything and
#: means nothing on its own.
MIN_CHUNK_CHARS = 200


@dataclass
class Document:
    id: str
    text: str
    metadata: dict


# ── building the documents ───────────────────────────────────────────────────
def corridor_documents(path: Path = AUDIT_CSV) -> list[Document]:
    """One document per audited corridor, written as a sentence rather than a row."""
    if not path.exists():
        log.warning("no corridor audit at %s", path)
        return []
    frame = pd.read_csv(path)
    documents = []
    for row in frame.itertuples():
        verdict = (
            f"statistically confirmed {'slower' if row.direction == 'worse' else 'faster'} "
            f"than the network"
            if row.is_significant else "not statistically distinguishable from the network"
        )
        rank = f" It is bottleneck rank {int(row.bottleneck_rank)}." if pd.notna(row.bottleneck_rank) else ""
        text = (
            f"Corridor {row.corridor_id} runs from {row.source_name} in {row.source_city} "
            f"to {row.destination_name} in {row.dest_city}, {row.dest_state}. "
            f"Over {int(row.n_legs)} legs it averages {row.mean_actual_time:.0f} minutes against "
            f"an OSRM plan of {row.mean_osrm_time:.0f} minutes, a median gap ratio of "
            f"{row.median_gap_ratio:.2f}. It runs {row.excess_ratio:.2f} times the network's "
            f"typical overrun and is {verdict} (q = {row.q_value:.4f}).{rank} "
            f"{row.ftl_share:.0%} of its legs are FTL."
        )
        documents.append(Document(
            id=f"corridor::{row.corridor_id}",
            text=text,
            metadata={
                "kind": "corridor", "corridor_id": row.corridor_id,
                "n_legs": int(row.n_legs), "excess_ratio": float(row.excess_ratio),
                "is_significant": bool(row.is_significant), "direction": str(row.direction),
            },
        ))
    return documents


def hub_documents(path: Path = FRICTION_CSV) -> list[Document]:
    """One document per congested hub."""
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    documents = []
    for row in frame.itertuples():
        # A NaN rendered into the text would be indexed and retrieved as the literal
        # string "nan%", which is worse than silence: it reads as a measurement.
        chain_break = (
            f" Its chain-break rate is {row.chain_break_rate:.1%}."
            if pd.notna(row.chain_break_rate) else ""
        )
        text = (
            f"Hub {row.centre_code} in {row.city}, {row.state} is rank {int(row.friction_rank)} "
            f"in the network's hub-friction table. Shipments leaving it sit a median of "
            f"{row.median_dwell_min_out:.0f} minutes ({row.median_dwell_share_out:.0%} of leg time), "
            f"and {row.p90_dwell_min_out:.0f} minutes at the 90th percentile. It serves "
            f"{int(row.n_corridors_out)} outbound corridors over {int(row.n_legs_out)} legs."
            f"{chain_break}"
        )
        documents.append(Document(
            id=f"hub::{row.centre_code}",
            text=text,
            metadata={"kind": "hub", "centre_code": row.centre_code,
                      "friction_rank": int(row.friction_rank)},
        ))
    return documents


def split_markdown(text: str, source: str) -> list[Document]:
    """Split a document at its own headings, keeping each heading with its body.

    Short sections fold forward into the next one: a heading with two lines under it
    retrieves against everything and answers nothing.
    """
    parts = re.split(r"^(#{2,4} .+)$", text, flags=re.MULTILINE)
    documents: list[Document] = []
    preamble, chunks = parts[0], parts[1:]
    pending = preamble.strip()

    for index in range(0, len(chunks) - 1, 2):
        heading, body = chunks[index].strip(), chunks[index + 1]
        block = f"{heading}\n{body}".strip()
        pending = f"{pending}\n\n{block}".strip() if pending else block
        if len(pending) >= MIN_CHUNK_CHARS:
            documents.append(Document(
                id=f"doc::{source}::{len(documents)}",
                text=pending,
                metadata={"kind": "doc", "source": source, "heading": heading.lstrip("# ")},
            ))
            pending = ""
    if pending and len(pending) >= MIN_CHUNK_CHARS:
        documents.append(Document(
            id=f"doc::{source}::{len(documents)}",
            text=pending,
            metadata={"kind": "doc", "source": source, "heading": ""},
        ))
    return documents


def doc_documents(directory: Path = DOCS_DIR) -> list[Document]:
    """Every `docs/*.md`, split at its headings."""
    documents: list[Document] = []
    for path in sorted(directory.glob("*.md")):
        documents.extend(split_markdown(path.read_text(encoding="utf-8"), path.name))
    return documents


def all_documents() -> list[Document]:
    corridors, hubs, docs = corridor_documents(), hub_documents(), doc_documents()
    log.info("%d corridor(s), %d hub(s), %d doc chunk(s)", len(corridors), len(hubs), len(docs))
    return corridors + hubs + docs


# ── the store ────────────────────────────────────────────────────────────────
def get_collection(persist_dir: Path | None = None, reset: bool = False):
    """The Chroma collection, created on first use.

    Imported lazily: `chromadb` pulls onnxruntime and a few hundred megabytes of
    transitive dependencies, and nothing else in the project should pay that import cost
    to read a config value.
    """
    import chromadb

    persist_dir = persist_dir or config.CHROMA_PERSIST_DIR
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    if reset:
        try:
            client.delete_collection(COLLECTION)
        except Exception as exc:  # noqa: BLE001 -- absent is the normal case on a first build
            log.debug("no existing collection to drop: %s", exc)
    return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


def build(persist_dir: Path | None = None, batch_size: int = 256) -> dict:
    """(Re)build the whole index. Safe to run repeatedly -- it replaces the collection."""
    documents = all_documents()
    if not documents:
        raise RuntimeError("nothing to index -- build the Week 2 audit tables first")

    log.info("embedding %d document(s); the first build downloads a ~80 MB ONNX model", len(documents))
    collection = get_collection(persist_dir, reset=True)
    for start in range(0, len(documents), batch_size):
        batch = documents[start:start + batch_size]
        collection.add(
            ids=[d.id for d in batch],
            documents=[d.text for d in batch],
            metadatas=[d.metadata for d in batch],
        )
        log.info("  %d / %d", min(start + batch_size, len(documents)), len(documents))

    kinds: dict[str, int] = {}
    for document in documents:
        kinds[document.metadata["kind"]] = kinds.get(document.metadata["kind"], 0) + 1
    return {"indexed": len(documents), "by_kind": kinds, "persist_dir": str(persist_dir or config.CHROMA_PERSIST_DIR)}


def search(query: str, k: int = 5, kind: str | None = None, persist_dir: Path | None = None) -> list[dict]:
    """Nearest documents to `query`, optionally restricted to one kind."""
    collection = get_collection(persist_dir)
    result = collection.query(
        query_texts=[query], n_results=k,
        where={"kind": kind} if kind else None,
    )
    hits = []
    for index, document in enumerate(result["documents"][0]):
        hits.append({
            "text": document,
            "metadata": result["metadatas"][0][index],
            # Cosine distance: 0 is identical. Reported rather than converted to a
            # similarity score, because a "92% match" invites a confidence reading the
            # number does not support.
            "distance": round(float(result["distances"][0][index]), 4),
        })
    return hits


def stats(persist_dir: Path | None = None) -> dict:
    collection = get_collection(persist_dir)
    return {"collection": COLLECTION, "documents": collection.count(),
            "persist_dir": str(persist_dir or config.CHROMA_PERSIST_DIR)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Vector store over the project's own knowledge")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--query", type=str, default=None)
    parser.add_argument("--kind", type=str, default=None, choices=["corridor", "hub", "doc"])
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if not (args.build or args.query or args.stats):
        parser.error("choose --build, --query or --stats")

    if args.build:
        report = build()
        log.info("indexed %d document(s): %s", report["indexed"], report["by_kind"])
    if args.stats:
        print(stats())
    if args.query:
        for hit in search(args.query, k=args.k, kind=args.kind):
            head = hit["metadata"].get("heading") or hit["metadata"].get("corridor_id") or hit["metadata"].get("centre_code")
            print(f"\n[{hit['distance']:.4f}] {hit['metadata']['kind']} :: {head}")
            print(hit["text"][:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
