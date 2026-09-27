# What this build has cost (execution plan v3.1 W8 D5)

**Owner: Mounika.** Written down because Phase 3 proposes moving to AWS, and a cost table
needs a baseline to be a comparison rather than a number.

## Direct spend to date: **$0.00**

Not "roughly nothing" — zero. Every line below is either free-tier or already owned.

| what | how it is free | what would end that |
|---|---|---|
| **LLM calls** (Gemini 3.6 Flash) | free tier, **20 requests/day**, no card on file | the daily cap is the binding constraint on this project's evaluation work: the Week 5 order-entry set took five days, and Week 7's extraction run is spread over three |
| **Compute** | three personal laptops; Spark runs `local[*]` | a dataset that does not fit in 16 GB, or a model that needs a GPU |
| **Storage** | local disk, 1.1 GB in `data/`: 914 MB of downloaded NYC taxi parquet, 55 MB of the source CSV, and **55 MB of everything this project generates** (24 MB parquet caches, 23 MB document corpus, 7.6 MB models) | the release assets, if they outgrow GitHub's 2 GB per-file limit |
| **Data** | Delhivery's public dataset; NYC TLC public parquet | neither is redistributed by this repository |
| **Code hosting** | GitHub free tier, public repository | private repos with Actions minutes |
| **Dashboard hosting** | Streamlit Community Cloud free tier (G-08, not yet deployed) | an app that needs more than the free container, which is why the deploy drops PySpark |
| **Vector store** | ChromaDB, local, on-disk | a hosted vector database |
| **Everything else** | open source: Spark, FastAPI, scikit-learn, Chroma, Tesseract | — |

## What the zero actually cost

The honest accounting is that the money was traded for constraints, and the constraints
shaped the work:

- **The 20-a-day LLM cap** is why every agent computes its verdict and generates only
  prose (D-041). That started as a quota workaround and became the project's clearest
  design position — deterministic decisions are reproducible and therefore scorable. It is
  also why evaluations resume from a cache and stop cleanly on a 429 rather than scoring a
  refusal as a failure.
- **One laptop, 20 cores, 4 GB of Spark driver memory** is why the scale appendix reports
  a 1.24× speedup from 5× the cores: 914 MB from one disk is IO-bound. A cluster would not
  have that ceiling, and the appendix says so rather than implying the curve continues.
- **No Docker** kept the Kafka path off a broker for two weeks (D-035). The constraint turned
  out to be softer than it looked: Kafka runs natively on the JDK the machine already had,
  and G-05 closed that way (D-055).

## The baseline for Phase 3

If the cloud phase is priced against this, the comparison is not "cloud costs $X" but
"cloud costs $X to remove these three constraints". Phase 3's own budget is a $40 credit,
and the three things worth spending it on, in order:

1. **A multi-node broker** — G-05 is closed on a single local broker; a cluster is what turns
   the throughput figure into a capacity figure.
2. **LLM quota** — the extraction evaluation is 40 rows over three days at 20/day; paid
   throughput makes it one run, and makes a second prompt iteration affordable.
3. **A machine with more than one disk** — the scale appendix's ceiling is IO, so the next
   scale number needs storage that is not one laptop SSD.

Hosting the dashboard is deliberately *not* on that list: the free tier already serves a
read-only dashboard, and paying for it buys a nicer URL rather than a better result.
