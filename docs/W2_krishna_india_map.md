# W2 · Krishna — India map and hub friction leaderboard

Week 2 deliverable: the two Streamlit pages that turn Lahari's audit and Mounika's hub
table into something a person can read, plus the city-name normalisation that had been
carried as an open item since Week 1.

```bash
streamlit run src/dashboard/app.py     # pages "India map" and "Hub friction"
```

Both pages read **only cached artefacts** (D-009) — `benchmarks/raw/w2_corridor_audit.csv`
and `w2_hub_dwell.csv`. Neither runs Spark, and each degrades to the standing
"not built yet" panel when its CSV is absent, so the dashboard still boots on a clone
with no artefacts.

---

## 1. The map form had to change after seeing the data

The plan said *"corridors coloured by delay severity"*, and I built exactly that first:
great-circle lines between the two ends of each audited corridor, on a national map of
India. It was wrong, and rendering it is what showed why.

**19 of the 34 bottleneck corridors started and ended in the same city, and 33 of 34
spanned under 50 km.** The median span was **0 km**. Drawn as lines on a map of India,
the worst corridors in the network are marks of zero length — the first render showed a
mostly empty map whose only visible lines were the long *fast* corridors, which is close
to the opposite of the finding. (At the 10-leg floor D-018 settled on, it is 70 of 273
intra-city and 186 of 273 under 50 km — less extreme, same conclusion, and the page
computes both numbers rather than quoting either.)

That is not a styling problem, so restyling would not have fixed it. Lahari's audit
already said the bottleneck table is *"short-haul and urban … metro and metro-fringe
corridors, not trunk routes"*; a corridor-as-line map is the wrong form for that claim.

**The page now maps cities, not routes.** Audited corridors roll up to the city they
leave from: bubble size is how many audited corridors leave that city, colour is the
worst effect size among them, and a line is drawn only for the minority of corridors
that actually cross a distance. The tooltip carries the corridor count, leg count, worst
and mean `excess_ratio`, and how many of the corridors are intra-city.

| Default view — bottlenecks only | Value |
|---|---|
| Corridors drawn | **273 of 273** significant bottlenecks |
| Cities carrying them | 169 |
| Intra-city corridors | 70 |
| Corridors with a drawn line | 203 |
| Corridors spanning under 50 km | 186 of 273 |
| Largest bubble | Mumbai — 28 corridors, 881 legs, 18 intra-city |
| Darkest bubble | Kanpur — worst corridor 13.88× the network's typical overrun |

*These are the figures after D-018 moved the support floor to 10 legs. At the 30-leg
floor the same table read 34 corridors in 13 cities, largest bubble Mumbai with 10 and
darkest Kolkata at 1.92×.* The page computes all of it from whatever is in the CSV, so
it followed the decision — but two things about it did **not** follow automatically, and
both are below.

A direction toggle is on the page and defaults to bottlenecks. The audit found the
planner wrong in **both** directions (34 slower, 36 faster), and a map that only ever
showed the slow half would misdescribe what was measured — so "Faster only" and "Both"
are one click away, and Bengaluru's fast cluster is visible in them.

### Colour

`excess_ratio` has a real midpoint — 1.0 is a corridor that overruns exactly as much as
the network typically does — so the ramp is **diverging**: a red arm for worse, a blue
arm for better, equal steps per arm so neither direction looks more finely resolved.
Line weight repeats the magnitude and the two directions differ by dash pattern as well
as hue, so severity survives a colourblind read. Every step was checked against the
contrast floor rather than eyeballed; the lightest red had to be darkened from `#f0a3a2`
to `#ec9694` to clear 2:1 against the map surface.

**D-018 needed a fourth step on each arm.** At the 30-leg floor the worst corridor ran
1.92×, so a top bin of "1.50×+" held a handful of near-identical corridors and that was
honest. At 10 legs the range runs to **13.88×**, and the same bin would have given a
13.9× corridor and a 1.51× corridor the identical shade — 110 of 273 bottlenecks in one
colour, at precisely the end of the scale a reader cares about. The cut points now sit
at 1.20 / 1.50 / 2.50, near the bottleneck distribution's median, p75 and p95, which
fills the four bins 50 / 113 / 86 / 24. The new darkest steps (`#5e1413`, `#06203f`)
were contrast-checked the same way: every step clears 2:1 against the map surface and
adjacent steps separate by 1.65–2.25:1.

---

## 2. Every audited corridor lands on the map — but not the way I first fixed it

The open item from Week 1 was a city-name normalisation table. It mattered more than it
looked: **only 72 of the 99 audited corridors could be placed**, and a corridor that
cannot be placed is silently absent — no error, just a missing dot.

Two failures, both fixed early in the week:

| Failure | Example | Fix |
|---|---|---|
| One city, several spellings | `AMD`, `Amd`, `Amdavad` all mean Ahmedabad; `GGN` means Gurugram | 11 alias rows added to `india_city_coords.csv` |
| A facility naming shape the parser did not know | `Mumbai Hub (Maharashtra)` — city separated by a space, not `_` | `city_of()` now splits on either separator |

The second one is the interesting half. `city_of()` split on `_` only, which is right for
`Anand_VUNagar_DC (Gujarat)` but returns the whole string for the nine facilities that
use a space. Those are the same rows Lahari's audit reported as **19 null city fields** —
one bug, surfacing in two places. That got the map to 99 of 99 (P-21).

### Then D-018 landed and the whole approach fell over

Lahari's support floor moved from 30 legs to 10, the audited set went from 99 corridors
to 1,130, and the map — running without a single error, reporting a healthy-looking
picture — was drawing **101 of the 273 bottlenecks**.

The hand-maintained table had 59 cities in it, and it had been built against a metro-heavy
audited set. The 10-leg set reaches **139 towns it had never heard of**, and there was no
top-20 of missing cities to add: the tail was almost entirely one corridor each — Nowda,
Ragunthgnj, Kaptanganj, Manjhaul. **A hand-maintained city list cannot follow the audit
wherever the audit goes.** Adding rows faster was not a fix, it was a treadmill.

### Placement moved onto the centre code

Every centre code carries a six-digit PIN — `IND282002AAD` is 282002, Agra — which is the
same fact D-011 already uses to recover a facility's state. So the map now places a
corridor from its **code** and labels the bubble from its **name**:

| Route | Centres placed |
|---|---|
| PIN inside the centre code, against GeoNames postal data | 1,605 of 1,657 — 96.9% |
| Facility-name fallback, hand table | the remaining 52 (PIN `000000`, or absent from postal data) |
| **Audited corridors placed** | **1,130 of 1,130 · 273 of 273 bottlenecks** |

`src/dashboard/reference/centre_coords.csv` is generated once by
`python -m src.dashboard.build_centre_coords` and committed; the dashboard reads the CSV
and never the generator, so D-009 holds and the page still starts on a fresh clone with
no pipeline run. GeoNames is CC BY 4.0 and is attributed in `data/README.md` and on the
page. Recorded as D-019 and P-24.

**This is D-002's argument, arriving a week late.** Corridors are keyed on centre codes
because names are null on 554 rows and spelled inconsistently. I left *placement* on
names anyway, which is why the same class of bug bit three times — P-21, P-23, and then
P-24, where it took out two thirds of the map. Names are for reading; codes are for
geometry.

The page keeps the fallback rather than retiring it, because `IND000000ACB` is a real,
working Gurgaon centre with a placeholder PIN — the code cannot be the only route. And
it reports whatever neither route places, by facility name, so the next gap is loud.

## 3. Hub friction leaderboard

Ranks the 121 hubs with ≥30 outbound legs on `dwell_share` — the fraction of a leg's wall
clock the shipment spent stationary — with raw minutes beside it.

| | |
|---|---|
| Hubs ranked | 121 (those with ≥30 outbound legs) |
| Median dwell share | 40% |
| Worst hub | Aluva (Kerala), `IND683511AAA` — **82%**, 350 median dwell minutes over 86 legs |

**The page argues D-015 by letting you break it.** A "rank by" toggle switches between
dwell share and raw minutes, and most of the leaderboard changes: the two rankings share
only **8 of their top 20** hubs (Spearman 0.48). Rather than assert that share is the
right metric, the page shows the disagreement and then gives Lahari's outside evidence —
raw minutes correlate **+0.55** with how long a hub's legs are *planned* to take, a column
neither dwell metric is built from, so a minutes leaderboard would substantially rank
hubs by the length of the legs they happen to serve.

Two things the page is careful to keep visible:

- **Dispatch is not receipt.** Outbound and inbound dwell share correlate only **0.38**
  across ranked hubs. A hub can be slow to send and quick to receive, so both are in the
  table and the ranking names which one it uses.
- **Hub friction is not corridor friction.** Neither dwell metric tracks the overrun of
  the corridors leaving the hub (−0.05 and −0.00). The map and this leaderboard are two
  separate claims and the dashboard does not imply otherwise.

---

## 4. Synthetic-document templates — the layouts to model on (W2 D5)

Week 6's Invoice Auditor and Document Intake agents read synthetic paperwork. The
research task was to find real layouts to model those templates on rather than invent
plausible-looking forms, because a template invented from scratch teaches the agent to
parse a document that does not exist.

**The first finding is that the obvious reference is the wrong country.** Most
"bill of lading template" material online is the US **VICS BOL** — a standardised form
carrying a 17-digit BOL number built from the shipper's UCC code, NMFC freight class and
subcode, PO number and carrier PRO number. The Delhivery network this project is built
on is Indian, and Indian road freight does not use it. Modelling our templates on VICS
would give the agents US freight-class fields that never appear beside an Indian
corridor.

The three documents that actually move with an Indian road consignment:

| Document | Governed by | The fields that must be on it |
|---|---|---|
| **Consignment note / Lorry Receipt (LR)** | Rule 4B, Service Tax Rules 1994 — still the working definition under GST | serial number, consignor and consignee names, **registration number of the goods carriage**, details of the goods, place of origin and destination, who pays the tax |
| **E-way bill (GST EWB-01)** | CGST Rules — Part A + Part B | *Part A:* supplier and recipient GSTIN, invoice/challan number and date, consignment value, HSN code, pick-up and delivery addresses. *Part B:* mode of transport, **vehicle registration number**, and the transport document number — which is the LR number above |
| **GST tax invoice** | Rule 46, CGST Rules 2017 — 16 mandatory particulars | supplier name/address/GSTIN, serial number (≤16 chars), date, recipient details and GSTIN, HSN/SAC, description, quantity, taxable value, CGST/SGST/IGST split, place of supply, reverse-charge flag, signature, and an IRN + QR code where Rule 48(4) e-invoicing applies |

**These three interlock, and that is the point for the agents.** The e-way bill's Part B
carries the LR number; its Part A carries the invoice number. So a consignment has a
three-document chain keyed on two identifiers, and an auditor agent's real job is
cross-document consistency — does the invoice number on the e-way bill match the invoice,
does the LR number match the consignment note — not single-document field extraction.
A template set that generates the three independently would make that job impossible to
evaluate, so they have to be generated together from one consignment record.

### What the project can already fill in

Most of a template's fields are already in the mock TMS or the audit tables, which means
the synthetic documents can be *derived* rather than fabricated:

| Document field | Where it comes from |
|---|---|
| consignor / consignee, origin & destination | `Order.origin_centre` / `dest_centre` → `Facility.name`, `city`, `state` |
| serial / document number | `Order.order_ref`, `Shipment.shipment_ref` |
| goods details | `Order.pieces`, `weight_kg` |
| mode of transport, carriage | `Order.route_type` (FTL / Carting) |
| place of origin and destination | `Shipment.corridor_id` — the centre pair (D-002) |
| planned vs actual timings | `Shipment.planned_departure` / `planned_arrival`, and the audit's `mean_osrm_time` per corridor |

**What has to be synthesised, and declared as scaffolding:** GSTIN numbers, HSN/SAC
codes, vehicle registration numbers, tax splits and consignment values. None of these
exist in the Delhivery data. They are the fields an Invoice Auditor would most want to
check, so they cannot be omitted — but the README's "honest scope" line has to cover
them explicitly, the same way it already declares the agents operate on synthetic
documents over a real network.

**The one field that makes the Invoice Auditor worth building** is billed transit time
against `mean_actual_time` for the corridor, which Lahari's `w2_corridor_audit.csv`
already carries. That is a check made against measured history rather than against a
number invented for the demo, and it is the reason to key the templates on real
corridors instead of random centre pairs.

### Open for Week 6

Layouts are chosen; the templates themselves are not written — that is Week 6 work, not
Week 2. Two decisions want raising at the sync before then: whether the synthetic GSTINs
should be structurally valid (state code + PAN + check digit) or obviously fake, and
whether the document set generates one consignment chain per shipment or deliberately
seeds mismatches for the auditor to find.

---

## 5. What's next

- **D-018 is closed, and it cost this page more than expected.** The Week 2 sync moved
  the support floor to 10 legs. The bubble sizes and colour bins do follow the CSV
  without an edit, as predicted — but the *colour ramp* needed a fourth step per arm
  (§1) and *placement* had to be rebuilt entirely (§2). The lesson is in P-24: a
  decision argued on statistics in one member's area changed the correctness of a
  lookup table in another's, and the writeup that predicted the ramp problem said
  nothing about placement because the ramp was the visible half.
- **Screenshots.** `demo/screenshots/` is still empty — GIT_RULES §3 wants a weekly
  dashboard capture, and W1 and W2 both owe one. Carried into Week 3 rather than
  quietly dropped.
- **The two alias tables should become one** (P-23). Less urgent since D-019 — the map
  no longer places by name, so the lists now only drive labels and the 52-centre
  fallback — but two files holding one truth is still two files.
- **Week 3** is the synthetic document corpus: generator, noise augmentation, and 100+
  labelled documents, built on the layouts researched in §4.
- **Week 4** fills the "Delay predictor" page; **Week 5** fills "Live alerts". Both are
  still the standing pending panel.
