# References

**Owner: Mounika**, consolidated W8 D5 from everyone's reading; rebuilt 21 October 2026 around
the shared bibliography `paper/refs.bib`. Grouped by what each entry is *for*, because a
reference list sorted alphabetically tells a reader nothing about why anything is in it.

**Verification status is marked on every entry.**

* `[read]` - someone opened the source and read its text, and can quote it.
* `[metadata checked]` - title, authors, venue/year **and** an identifier (DOI, arXiv id or
  stable URL) were confirmed on the source's own record or a registry (Crossref, the arXiv
  API, a proceedings page, a library catalogue) on **21 October 2026**, but the full text has
  not been read.
* `[listed]` - found by search or carried over from an earlier pass; not confirmed against a
  source page in this pass. These are **not** in `paper/refs.bib` and must not be cited until
  checked.

**Before submission every cited entry must be `[read]` - Lahari's pass (WP-10).** In the 21
October pass **no full text was read**; the 90 bibliography entries are `[metadata checked]`,
which is enough to cite correctly but not enough to describe a paper's findings. Do not write
what a cited paper "shows" until its row is `[read]`.

The column `key` is the cite key in `paper/refs.bib`. `core` marks the 33 entries meant for
the page-limited conference paper (`keywords = {core}` in the bib); everything else is
`journal`.

---

## 1 · The data

- **Delhivery logistics trip dataset**, public release. 144,867 scan-level segment rows,
  14,817 trips, reconstructed here into 26,369 origin-destination legs. Carries the routing
  engine's estimate (`osrm_time`) beside the realised time, which is what makes the audit
  possible at all. `[read]` - used throughout; see `data/README.md` for provenance and
  `docs/W1_lahari_data_dictionary_and_eda.md` for the field-by-field reading. Not in
  `refs.bib`: the old bib entry pointed at a Kaggle page that was not opened in the 21 October
  pass, so it is re-added only once its page is checked.
- **NYC TLC yellow-taxi trip records**, monthly parquet, 2023-2024. 56.4M rows used for the
  scale appendix only; no analytical claim is made from them. `[read]`

**On the Delhivery dataset's own literature:** a search on 18 September 2026 found Kaggle
notebooks and GitHub repositories doing feature engineering and actual-vs-OSRM comparison,
and **no peer-reviewed paper using this dataset**. That is a statement about our search,
not about the world, and the paper must phrase it that way. Practical consequence: there is
no published baseline on this data to compare against, which is why every result is reported
beside a trivial policy instead.

## 2 · The closest published work (ETA and delivery-time prediction)

Full table with "how we differ" in `docs/paper_outline.md`.

| key | citation | status | verified against |
|---|---|---|---|
| `hu2022deepreta` (core) | Hu, Binaykiya, Frank, Cirit, "DeeprETA: An ETA Post-processing System at Scale", arXiv:2206.02127 (2022). A deep residual network correcting a route planner's ETA. **Cite this, not the blog.** | `[metadata checked]` | arXiv API record |
| - | "DeepETA: How Uber Predicts Arrival Times Using Deep Learning" (Uber Engineering blog, 2022). Residual between a routing engine's ETA and the outcome; asymmetric Huber loss. The closest precedent for our formulation. | `[listed]` - an earlier pass marked it read; the page was not re-opened on 21 October and has no bib entry | - |
| `derrowpinion2021eta` (core) | Derrow-Pinion et al. (17 authors), "ETA Prediction with Graph Neural Networks in Google Maps", CIKM '21, pp. 3767-3776, doi:10.1145/3459637.3481916; arXiv:2108.11482 | `[metadata checked]` | Crossref; arXiv API ("To appear at CIKM 2021, Applied Research Track") |
| `wang2018learning` (core) | Wang, Fu, Ye, "Learning to Estimate the Travel Time", KDD '18, pp. 858-866, doi:10.1145/3219819.3219900 | `[metadata checked]` | Crossref |
| `wang2018deeptte` | Wang, Zhang, Cao, Li, Zheng, "When Will You Arrive? Estimating Travel Time Based on Deep Neural Networks", AAAI 2018, doi:10.1609/aaai.v32i1.11877 | `[metadata checked]` | Crossref |
| `fang2020constgat` | Fang et al., "ConSTGAT: Contextual Spatial-Temporal Graph Attention Network for Travel Time Estimation at Baidu Maps", KDD '20, pp. 2697-2705, doi:10.1145/3394486.3403320 | `[metadata checked]` | Crossref (record carries the short title) |
| `vlahogianni2014short`, `lana2018road` | Two traffic-forecasting surveys (Transp. Res. Part C 43, 2014; IEEE ITS Magazine 10(2), 2018) | `[metadata checked]` | Crossref |
| `wen2023survey` (core) | Wen, Lin, Wu, Mao, Cai, Hou, Guo, Liang, Jin, Zhao, Zimmermann, Ye, Wan (13 authors), "A Survey on Service Route and Time Prediction in Instant Delivery: Taxonomy, Progress, and Prospects", arXiv:2309.01194 (2023). Places us: time-only, supervised, non-deep, line-haul rather than instant delivery. **Venue: preprint only** - no journal version was found. | `[metadata checked]` (an earlier pass marked it `[read]`; not re-opened) | arXiv API; a DBLP-based search lists it as a CoRR preprint |
| `mao2023drl4route` | Mao, Wen, Zhang, Wan, Wu, Zheng, Hu, Lin, "DRL4Route: A Deep Reinforcement Learning Framework for Pick-up and Delivery Route Prediction", KDD '23, arXiv:2307.16246. Different task (route order); cited for deployment framing. | `[metadata checked]` | arXiv API ("Accepted by KDD23"); no DOI or pages found |
| `yi2023deepsta` | Yi, Yan, Wang, Yuan, Li, "DeepSTA: ...", CIKM '23, pp. 4916-4922, doi:10.1145/3583780.3614671; arXiv:2505.00402 (posted 2025, published 2023 - the earlier note dated it 2025) | `[metadata checked]` | Crossref; arXiv API |
| `khiari2020boosting` (core) | Khiari, Olaverri-Monreal, "Boosting Algorithms for Delivery Time Prediction in Transportation Logistics", ICDMW 2020, pp. 251-258, doi:10.1109/ICDMW51313.2020.00043; arXiv:2009.11598. LightGBM and CatBoost most accurate. | `[metadata checked]` | Crossref; arXiv API |

## 2b · The route engine being audited

| key | citation | status | verified against |
|---|---|---|---|
| `luxen2011real` (core) | Luxen, Vetter, "Real-time routing with OpenStreetMap data", ACM SIGSPATIAL GIS '11, pp. 513-516, doi:10.1145/2093973.2094062. The OSRM paper. | `[metadata checked]` | Crossref |
| `geisberger2008contraction`, `bast2016route` | Contraction hierarchies (WEA 2008, LNCS 5038, pp. 319-333) and the route-planning survey (LNCS 9220, pp. 19-80, 2016) | `[metadata checked]` | Crossref; author-group page for the year of the first |

## 2c · Language-model agents for operations

| key | citation | status | verified against |
|---|---|---|---|
| `yao2023react` (core) | Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models", ICLR 2023, arXiv:2210.03629 | `[metadata checked]` | arXiv API (v3 is the ICLR camera-ready) |
| `wang2024survey` (core) | Wang et al., "A survey on large language model based autonomous agents", *Frontiers of Computer Science* 18(6), 2024, doi:10.1007/s11704-024-40231-1 | `[metadata checked]` | Crossref; arXiv:2308.11432. The earlier note's article number 186345 was not shown by either record and is dropped. |
| `li2023optiguide` (core) | Li, Mellou, Zhang, Pathuri, Menache, "Large Language Models for Supply Chain Optimization", arXiv:2307.03875. Model edits an optimiser's input and explains its output; the optimiser decides. | `[metadata checked]` | arXiv API; preprint only |
| `xi2023rise` | Xi et al. (29 authors), agent survey, arXiv:2309.07864 | `[metadata checked]` | arXiv API; no journal version confirmed |
| `schick2023toolformer`, `wei2022chain` | Toolformer (NeurIPS 36, 2023); chain-of-thought prompting (NeurIPS 35, 2022) | `[metadata checked]` | proceedings pages (papers.nips.cc) |
| `lewis2020retrieval`, `zheng2023judging` | Retrieval-augmented generation (NeurIPS 2020); LLM-as-a-judge with MT-Bench (NeurIPS 2023 Datasets and Benchmarks) | `[metadata checked]` | arXiv API (venue from the authors' comment field) |
| `mcp2025specification` (core) | Model Context Protocol specification, revision 2025-06-18, `modelcontextprotocol.io/specification/2025-06-18`. Our MCP server exposes 13 tools. Cite the specification page, not news coverage. | `[metadata checked]` | the specification page itself was opened and its overview read; the page names no personal authors |

## 2d · Control towers and supply-chain visibility

| key | citation | status | verified against |
|---|---|---|---|
| `trzuskawska2017control` (core) | Trzuskawska-Grzesinska, "Control towers in supply chain management - past and future", *J. Economics and Management* 27(1), 114-133, 2017, doi:10.22367/jem.2017.27.07. Business cases; argues whole-chain visibility needs integrated control towers. | `[metadata checked]` | Crossref; DOAJ listing (found by search) |
| `chaffin2024systematic` | Chaffin, Maywald, Reiman, Glassburner, "Systematic Review of Supply Chain Control Tower Critical Success Factors and Resilience Effects", *Operations and Supply Chain Management* 17(3), 236-251, 2024, doi:10.31387/oscm0580439 | `[metadata checked]` | Crossref; AFIT repository record |
| `barratt2007antecedents`, `somapa2018characterizing`, `francis2008supply` | Supply-chain visibility: J. Operations Management 25(6), 2007; Int. J. Logistics Management 29(1), 2018; Supply Chain Management 13(3), 2008 | `[metadata checked]` | Crossref |
| - | Li, Miskon, Jamal, Yue, Zhang, "Supply Chain Control Towers: A Systematic Literature Review" (IJARBSS) | `[listed]` - sources disagree on the year (2015 in the PDF header, December 2024 in a search summary), so it is left out of the bib | search result only |

## 3 · Corridor-level travel time and reliability

The transport-research strand that shares our unit of analysis. **The earlier placeholders
("FHWA, Freight Performance Measurement ...", "Travel-time reliability for freight corridors
(TREC)") are replaced by the precisely identified reports below.**

| key | citation | status | verified against |
|---|---|---|---|
| `fhwa2005reliability` (core) | FHWA, *Travel Time Reliability: Making It There On Time, All The Time*, December 2005, produced by the Texas Transportation Institute with Cambridge Systematics. Defines the **planning time index** (95th percentile travel time / free-flow travel time) and the **buffer index** ((95th percentile - mean) / mean). No report number appears on the page. | `[metadata checked]` - the definitions were read on the page, the report PDF was not | `ops.fhwa.dot.gov/publications/tt_reliability/TTR_Report.htm` |
| `jones2005measuring` | Jones, *Measuring Travel Time in Freight-Significant Corridors*, FHWA-HOP-05-036, April 2005 (FHWA with the American Transportation Research Institute); Freight Performance Measurement initiative, truck GPS data. **This replaces the old "[to read in full]" FHWA item.** | `[metadata checked]` | `rosap.ntl.bts.gov/view/dot/41726` (title, author, number, date) |
| `margiotta2013shrp2` (core) | Margiotta, Lomax, Hallenbeck, Dowling, Skabardonis, Turner, *Analytical Procedures for Determining the Impacts of Reliability Mitigation Strategies*, SHRP 2 Report S2-L03-RR-1, TRB, 2013, doi:10.17226/22806 | `[metadata checked]` | `rosap.ntl.bts.gov/view/dot/3605`; National Academies catalogue (found by search) |
| `monsere2009truck` | Monsere, Wolfe, Alawakiel, Stephens, *Developing corridor-level truck travel time estimates and other freight performance measures from archived ITS data*, FHWA-OR-RD-10-07, August 2009 (Oregon DOT / Portland State) | `[metadata checked]` | `rosap.ntl.bts.gov/view/dot/5666` |
| `figliozzi2012reliability` | Figliozzi, *Analysis of Travel-Time Reliability for Freight Corridors Connecting the Pacific Northwest*, OTREC-RR-12-11, November 2012. Commercial-truck GPS on I-5. **Whether it fits gamma / log-logistic / log-normal / Weibull distributions was not confirmed** (the earlier note said so); the distribution-fitting study found by search was a different paper, not cited. | `[metadata checked]` | `rosap.ntl.bts.gov/view/dot/26057` |
| `unnikrishnan2022statistical` | Unnikrishnan, Figliozzi, Kochar, *Statistical Inference for Multimodal Travel Time Reliability*, NITC-RR-1403, 2022, doi:10.15760/trec.278 | `[metadata checked]` | `pdxscholar.library.pdx.edu/trec_reports/244` |
| `pu2011analytic` | Pu, "Analytic Relationships between Travel Time Reliability Measures", *Transportation Research Record* 2254, 122-130, 2011, doi:10.3141/2254-13 | `[metadata checked]` | Crossref |

**Why they matter to us:** this literature measures corridors with *descriptive indices*.
Our contribution in the same unit is **significance testing with multiplicity control** -
the difference between "this corridor looks unreliable" and "this corridor is slower than
the network at FDR 5%". Before submission, at least two of these (the FHWA 2005 reliability
report and SHRP 2 L03) need reading in full so the distinction is stated fairly rather than
assumed. Not yet done.

## 4 · Statistical method

| key | citation | status | verified against |
|---|---|---|---|
| `welch1947generalization` (core) | Welch (1947), *Biometrika* 34(1-2), 28-35. The unequal-variance t-test used corridor by corridor. | `[metadata checked]` | Crossref |
| `benjamini1995controlling` (core) | Benjamini, Hochberg (1995), *JRSS B* 57(1), 289-300. 1,130 simultaneous tests; FDR at 0.05. | `[metadata checked]` | Crossref |
| `benjamini2001control` (core) | Benjamini, Yekutieli (2001), *Ann. Statist.* 29(4), 1165-1188. FDR under dependency. | `[metadata checked]` | Crossref |
| `storey2002direct`, `storey2003positive` | Storey 2002 (JRSS B 64(3)); Storey 2003 (Ann. Statist. 31(6)) | `[metadata checked]` | Crossref |
| `efron2010large` (core), `westfall1993resampling`, `good2005permutation` | Large-scale inference; resampling-based multiple testing (Wiley 1993, ISBN 978-0-471-55761-6); permutation/bootstrap tests (Springer 2005) | `[metadata checked]` | Crossref; library catalogues for Westfall and Young |
| `cameron2015practitioner` (core), `cameron2008bootstrap` | Cluster-robust inference (J. Human Resources 50(2), 2015; Rev. Econ. Statist. 90(3), 2008) | `[metadata checked]` | Crossref |
| `phipson2010permutation` | Permutation p-values should never be zero (SAGMB 9(1), 2010) | `[metadata checked]` | Crossref |
| `matthews1975comparison`, `chicco2020advantages` (core) | **Matthews correlation coefficient** for the threshold sweep, chosen because accuracy is meaningless at a 95% base rate (the 1975 origin paper and the 2020 argument against F1 and accuracy) | `[metadata checked]` | Crossref |
| `wilson1927probable` (core), `agresti1998approximate`, `cochran1954some`, `armitage1955tests`, `cohen1960coefficient`, `landis1977measurement`, `fleiss1971measuring` | Binomial intervals, trend test, agreement statistics | `[metadata checked]` | Crossref |

## 4b · Empirical Bayes, ranking, forecast evaluation, leakage, ML

| group | keys | status | verified against |
|---|---|---|---|
| shrinkage and ranking | `robbins1956empirical`, `efron1973stein` (core), `efron1975data`, `morris1983parametric`, `laird1989empirical` (core), `gelman2007data`, `gelman2013bayesian`, `gelman2014beyond` (core), `goldstein1996league` | `[metadata checked]` | Crossref; Project Euclid listing for Robbins |
| gradient boosting | `friedman2001greedy` (core), `chen2016xgboost` (core), `ke2017lightgbm`, `prokhorenkova2018catboost`, `grinsztajn2022why`, `breiman2001random` | `[metadata checked]` | Crossref; papers.nips.cc; arXiv API |
| forecast evaluation | `diebold1995comparing` (core), `harvey1997testing`, `tashman2000out` (core), `bergmeir2012use` (core), `hyndman2006another`, `politis1994stationary`, `kunsch1989jackknife`, `efron1979bootstrap`, `wilcoxon1945individual`, `demsar2006statistical` | `[metadata checked]` | Crossref; jmlr.org for Demsar |
| leakage and reproducibility | `kaufman2012leakage` (core), `kapoor2023leakage` (core), `arp2022dos`, `pineau2021improving` | `[metadata checked]` | Crossref; USENIX and JMLR pages |

Specific caution for the paper: the proceedings title of Grinsztajn et al. says "typical
tabular data"; the arXiv v1 title says "tabular data". The bib follows the proceedings.

## 4c · Systems: stream processing and big data

| key | citation | status | verified against |
|---|---|---|---|
| `zaharia2016apache` (core) | Apache Spark, CACM 59(11), 2016 | `[metadata checked]` | Crossref |
| `armbrust2018structured` (core) | Structured Streaming, SIGMOD '18 | `[metadata checked]` | Crossref |
| `meng2016mllib` | MLlib, JMLR 17(34), 2016 | `[metadata checked]` | jmlr.org |
| `kreps2011kafka` | Kafka, NetDB '11 (no DOI) | `[metadata checked]` | search results reproducing the ACM copyright block and authors |
| `zaharia2012resilient`, `dean2008mapreduce` | RDDs (NSDI '12); MapReduce (CACM 51(1), 2008) | `[metadata checked]` | usenix.org; Crossref |
| - | Carbone et al., Apache Flink (IEEE Data Eng. Bull., 2015) | `[listed]` - authors confirmed, volume and issue not; left out of the bib | search result only |

## 5 · Tools, with versions as run

| tool | version | used for |
|---|---|---|
| Apache Spark (PySpark) | 4.0.4 | every pipeline stage, MLlib models, Structured Streaming |
| scikit-learn | 1.9.0 | the single-node reference model (diagnostic only) |
| FastAPI + SQLModel | 0.141.1 | the mock TMS the agents actually post to |
| ChromaDB | 1.5.9 | the vector index behind the analytics assistant |
| LangChain (`langchain-google-genai`) + LangGraph | see `requirements.txt` | one LLM construction site (D-007), lifecycle graph |
| Google Gemini 3.6 Flash | - | every generated sentence; free tier, 20 calls/day |
| Tesseract (pytesseract) | - | OCR for the degraded-scan split |
| Streamlit + Folium + Plotly | - | the dashboard |
| Matplotlib | 3.11.2 | the paper's figure set |

Exact pins are in `requirements.txt`; the cloud dashboard's reduced set is in
`requirements-cloud.txt`.

## 6 · Our own decisions, as citations

The paper cites its own decision log where a choice would otherwise look arbitrary. These
are the ones a reviewer is most likely to ask about:

| id | what it settles |
|---|---|
| D-003 | the 2.0x delay threshold, and the 1.25x one that was rejected |
| D-018 | the 10-leg support floor, and the instability it exposed |
| D-022 | chronological split, not random |
| D-024 | MAE as the metric |
| D-028 | builder and judge are different people |
| D-041 | verdicts computed, prose generated |
| D-048 | the median is the fair baseline |
| D-049 | the selection protocol, fixed before it ran |
| D-050 | what was adopted, and why the served model is still the old one |
| D-052 | the venue and the preprint ordering (see D-095 and D-097: the venue named there is a networking conference) |
| D-095 | the venue shortlist and recommendation |
| D-096 | the bibliography verification rule |

## 7 · How this file and the bib were checked

* Every `refs.bib` entry has a `note` with the verification date and URL or DOI;
  `tests/test_refs_bib.py` checks that, plus balanced braces, unique keys and at least 50
  entries.
* The bib compiles without BibTeX errors under `IEEEtran`, `splncs04` and `elsarticle-num`
  (test document with `\nocite{*}`, tectonic, 21 October 2026).
* DOIs recalled from memory were wrong at least five times (each pointed at an unrelated
  paper); the rule that each DOI is resolved through Crossref before use caught every one.
  See P-81.
