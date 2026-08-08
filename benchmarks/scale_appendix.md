# Scale appendix — identical Spark code on 50M+ rows

**Owner: Mounika.** Populated Week 7.

The blueprint (§12) rests the big-data claim partly on this: the same corridor
aggregation code, unchanged, run on NYC TLC trip records at two orders of magnitude
more data, with a runtime table.

## Status: awaiting Week 7

| Dataset | Rows | Cores | Driver memory | Wall time | Notes |
|---|---|---|---|---|---|
| Delhivery | 144,867 | | | _pending_ | |
| NYC TLC (1 month) | ~3M | | | _pending_ | |
| NYC TLC (6 months) | ~50M | | | _pending_ | |

## Rules

- **The Spark code must be genuinely identical** — same functions, imported, not
  copy-adapted. If a parameter has to change (shuffle partitions, for instance), state
  which and why. A re-implementation proves nothing about the original.
- Report cores and memory per row of the table. A runtime without them is unreadable.
- Include the schema mapping used to present taxi trips as corridor legs.
