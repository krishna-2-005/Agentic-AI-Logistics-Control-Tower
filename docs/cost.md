# What this build has cost (execution plan v3.1 W8 D5)

**Owner: Mounika.** Written down so the project's cost is a stated number, not an assumption.
The AWS phase the v3.1 plan proposed was dropped (D-074); the project runs on free tiers only.

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

## What money would buy, if it were ever spent

No paid service is used, and none is planned (D-074). If one were, the comparison is not
"this costs $X" but "this costs $X to remove these three constraints", in this order:

1. **A multi-node broker** — G-05 is closed on a single local broker; a cluster is what turns
   the throughput figure into a capacity figure.
2. **LLM quota** — the extraction evaluation is 40 rows over three days at 20/day; paid
   throughput makes it one run, and makes a second prompt iteration affordable.
3. **A machine with more than one disk** — the scale appendix's ceiling is IO, so the next
   scale number needs storage that is not one laptop SSD.

Hosting is deliberately *not* on that list: the site runs on Vercel's free plan and the API on
Render's free plan (D-073), and paying for either buys a nicer URL rather than a better result.

## B7 agent ablation: calls, tokens, cost (D-086, D-088)

The LLM-decides arm uses open models on Groq's free tier, not the Gemini model that writes the
project's prose. Measured cost: **$0**. Every response is cached on disk, so a rerun makes no calls.

| arm | provider calls | input / output tokens | summed latency | cases |
|---|---|---|---|---|
| `openai/gpt-oss-120b`, ablation (3 smoke calls included) | 248 | 193,573 / 54,583 | 2,148 s | order 18, invoice 8, exception 8 |
| `openai/gpt-oss-20b`, ablation | 168 | 119,658 / 25,702 | 1,243 s | 8 per agent |
| `openai/gpt-oss-20b`, held-out hard sets, temperature 0 | 40 | see `b7_llm_ledger_hard_sets_gpt-oss-20b.json` | | 20 per agent |
| Gemini, document extraction rows 21 to 40 (same model as rows 1 to 20) | 5 | not recorded | | 5 clean extractions, kept out of the repository (P-75) |

**The limit that bound, and what it cost the design.** The key's limits for `gpt-oss-120b` are
1,000 requests a day, 8,000 tokens a minute and **200,000 tokens a day**. The daily token cap
ended the run after 248 calls (the provider's own message: "Limit 200000, Used 199374,
Requested 1072"); it refills continuously, about 8 calls an hour after that. The design needs
about 840 calls per model, so the pre-registered 40 cases per agent would take about four
days of allowance, and the results are reported at the completed prefix (D-088). A paid tier
would remove the constraint; this was not bought (D-074).

**Paid-equivalent estimate, clearly an estimate.** At an assumed list price of $0.15 per million
input tokens and $0.60 per million output tokens for `gpt-oss-120b` (entered by hand from the
provider's public pricing; check it before quoting), the measured mean token use gives about
**$0.25 per 1,000 verdicts** (`gpt-oss-120b`, 7 calls per case included) and about $0.20 for
`gpt-oss-20b` at the same assumed prices, which are not 20b's own. The deterministic arm
costs no tokens and its decision takes microseconds. Latency per verdict was 4.9 s (exception),
8.6 s (invoice) and 10.9 s (order entry) mean for `gpt-oss-120b`, against 0.04 ms for the
exception agent's arithmetic (`w6_exception_eval.json`).
