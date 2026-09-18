# References

**Owner: Mounika**, consolidated W8 D5 from everyone's reading. Grouped by what each entry
is *for*, because a reference list sorted alphabetically tells a reader nothing about why
anything is in it.

**Verification status is marked on every entry.** `[read]` means someone opened the source
and can quote it; `[listed]` means it came from a search result or an abstract and still
needs its full text and a proper citation before submission. Nothing here is cited in the
paper until it is `[read]`.

---

## 1 · The data

- **Delhivery logistics trip dataset**, public release. 144,867 scan-level segment rows,
  14,817 trips, reconstructed here into 26,369 origin-destination legs. Carries the
  production routing engine's estimate (`osrm_time`) beside the realised time, which is
  what makes the audit possible at all. `[read]` — used throughout; see `data/README.md`
  for provenance and `docs/W1_lahari_data_dictionary_and_eda.md` for the field-by-field
  reading.
- **NYC TLC yellow-taxi trip records**, monthly parquet, 2023-2024. 56.4M rows used for the
  scale appendix only; no analytical claim is made from them. `[read]`

**On the Delhivery dataset's own literature:** a search on 18 September 2026 found Kaggle
notebooks and GitHub repositories doing feature engineering and actual-vs-OSRM comparison,
and **no peer-reviewed paper using this dataset**. That is a statement about our search,
not about the world, and the paper must phrase it that way. Practical consequence: there is
no published baseline on this data to compare against, which is why every result is reported
beside a trivial policy instead.

## 2 · The closest published work

Full table with "how we differ" in `docs/paper_outline.md`.

- **DeepETA: How Uber Predicts Arrival Times Using Deep Learning** (Uber Engineering, 2022).
  Predicts the **residual between a routing engine's ETA and the observed outcome**;
  asymmetric Huber loss, chosen because MAE is the reported metric. The closest precedent
  for our formulation, arrived at independently — and useful evidence that residual-over-a-
  planner is a normal thing to do, not a workaround. `[read]`
- **Wen, H. et al., "A Survey on Service Route and Time Prediction in Instant Delivery:
  Taxonomy, Progress, and Prospects"**, arXiv:2309.01194 (2023). Taxonomy by task
  (route / time / joint), architecture (sequence / graph) and paradigm (supervised / DRL).
  Places us: time-only, supervised, non-deep, line-haul rather than instant delivery.
  `[read]`
- **DRL4Route: A Deep Reinforcement Learning Framework for Pick-up and Delivery Route
  Prediction**, arXiv:2307.16246 (2023). Deployed at Cainiao. Different task (route order),
  cited for deployment framing. `[listed]`
- **DeepSTA: A Spatial-Temporal Attention Network for Logistics Delivery Timely Rate
  Prediction in Anomaly Conditions**, arXiv:2505.00402. Adjacent motivation — systematic
  disruption — with a learned model where ours is statistical. `[listed]`

## 3 · Corridor-level travel time and reliability

The transport-research strand that shares our unit of analysis.

- **FHWA, Freight Performance Measurement: Travel Time in Freight-Significant Corridors.**
  Corridor-level reliability measures from GPS probe data: planning-time index, buffer
  index, percentile spreads. `[listed]`
- **Developing corridor-level truck travel time estimates and other freight performance
  measures from archived ITS data** (US DOT / ROSAP). `[listed]`
- **Travel-time reliability for freight corridors** (TREC / Portland State; Pacific
  Northwest corridors). Distribution fitting — gamma, log-logistic, log-normal, Weibull —
  with goodness-of-fit testing. `[listed]`

**Why they matter to us:** this literature measures corridors with *descriptive indices*.
Our contribution in the same unit is **significance testing with multiplicity control** —
the difference between "this corridor looks unreliable" and "this corridor is slower than
the network at FDR 5%". Before submission, at least two of these need reading in full so
the distinction is stated fairly rather than assumed.

## 4 · Statistical method

- **Welch, B. L. (1947), "The generalization of Student's problem when several different
  population variances are involved"**, *Biometrika* 34(1-2), 28-35. The unequal-variance
  t-test used corridor-by-corridor. `[listed]` — standard, but cite properly.
- **Benjamini, Y. & Hochberg, Y. (1995), "Controlling the False Discovery Rate: A Practical
  and Powerful Approach to Multiple Testing"**, *JRSS B* 57(1), 289-300. 1,130 simultaneous
  tests; FDR at 0.05. `[listed]`
- **Matthews correlation coefficient** for the threshold sweep, chosen because accuracy is
  meaningless at a 95% base rate. `[listed]`

## 5 · Tools, with versions as run

| tool | version | used for |
|---|---|---|
| Apache Spark (PySpark) | 4.0.4 | every pipeline stage, MLlib models, Structured Streaming |
| scikit-learn | 1.9.0 | the single-node reference model (diagnostic only) |
| FastAPI + SQLModel | 0.141.1 | the mock TMS the agents actually post to |
| ChromaDB | 1.5.9 | the vector index behind the analytics assistant |
| LangChain (`langchain-google-genai`) + LangGraph | see `requirements.txt` | one LLM construction site (D-007), lifecycle graph |
| Google Gemini 3.6 Flash | — | every generated sentence; free tier, 20 calls/day |
| Tesseract (pytesseract) | — | OCR for the degraded-scan split |
| Streamlit + Folium + Plotly | — | the dashboard |
| Matplotlib | 3.11.2 | the paper's figure set |

Exact pins are in `requirements.txt`; the cloud dashboard's reduced set is in
`requirements-cloud.txt`.

## 6 · Our own decisions, as citations

The paper cites its own decision log where a choice would otherwise look arbitrary. These
are the ones a reviewer is most likely to ask about:

| id | what it settles |
|---|---|
| D-003 | the 2.0× delay threshold, and the 1.25× one that was rejected |
| D-018 | the 10-leg support floor, and the instability it exposed |
| D-022 | chronological split, not random |
| D-024 | MAE as the metric |
| D-028 | builder and judge are different people |
| D-041 | verdicts computed, prose generated |
| D-048 | the median is the fair baseline |
| D-049 | the selection protocol, fixed before it ran |
| D-050 | what was adopted, and why the served model is still the old one |
| D-052 | the venue and the preprint ordering |
