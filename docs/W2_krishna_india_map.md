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

**19 of the 34 bottleneck corridors start and end in the same city, and 33 of 34 span
under 50 km.** The median span is **0 km**. Drawn as lines on a map of India, the worst
corridors in the network are marks of zero length — the first render showed a mostly
empty map whose only visible lines were the long *fast* corridors, which is close to the
opposite of the finding.

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
| Corridors drawn | 34 of 34 significant bottlenecks |
| Cities carrying them | 13 |
| Intra-city corridors | 19 |
| Corridors with a drawn line | 15 |
| Largest bubble | Mumbai — 10 corridors, 554 legs, 7 intra-city |
| Darkest bubble | Kolkata — worst corridor 1.92× the network's typical overrun |

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

---

## 2. Every audited corridor now lands on the map

The open item from Week 1 was a city-name normalisation table. It mattered more than it
looked: **only 72 of the 99 audited corridors could be placed**, and a corridor that
cannot be placed is silently absent — no error, just a missing dot.

Two separate failures, both now fixed:

| Failure | Example | Fix |
|---|---|---|
| One city, several spellings | `AMD`, `Amd`, `Amdavad` all mean Ahmedabad; `GGN` means Gurugram | 11 alias rows added to `india_city_coords.csv` |
| A facility naming shape the parser did not know | `Mumbai Hub (Maharashtra)` — city separated by a space, not `_` | `city_of()` now splits on either separator |

The second one is the interesting half. `city_of()` split on `_` only, which is right for
`Anand_VUNagar_DC (Gujarat)` but returns the whole string for the nine facilities that
use a space. Those are the same rows Lahari's audit reported as **19 null city fields** —
one bug, surfacing in two places. The map re-derives cities from the raw facility names
rather than reading the audit's city columns, so it does not inherit the nulls.

**Result: 99 of 99 audited corridors resolve, and all 70 significant ones are drawable.**
The page shows the coverage number and names anything unmapped, so this degrades loudly
rather than silently if new facilities appear.

---

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

## 4. What's next

- **D-018 changes this map.** If the support floor moves from 30 legs to 10, the audited
  set goes from 99 corridors to 1,130 and the worst effect size from 1.92× to 13.9×. The
  bubble sizes and the colour bins are both computed from whatever is in the CSV, so the
  page follows the decision without an edit — but the top of the ramp will need a look,
  since a 13.9× corridor and a 1.5× corridor would currently share the darkest bin.
- **Synthetic-document templates (W2 D5)** — still open, tracked in `problems.md`.
- **Week 4** fills the "Delay predictor" page; **Week 5** fills "Live alerts". Both are
  still the standing pending panel.
