/**
 * Every technical term the site uses, defined once.
 *
 * Plain data with no imports so a Node test can check that the terms the pages
 * rely on are all here (`tests/web_format.test.mjs`).
 */

export interface GlossaryTerm {
  term: string;
  definition: string;
}

export const GLOSSARY: GlossaryTerm[] = [
  {
    term: "Leg",
    definition:
      "One origin-to-destination journey. The raw data is scan-level segments; a leg is all the segments of one journey collapsed into a single row.",
  },
  {
    term: "Corridor",
    definition:
      "A named pair of facilities: everything that travels from A to B. Keyed by centre code rather than city name, because a code is never null and never spelled two ways.",
  },
  {
    term: "OSRM",
    definition:
      "Open Source Routing Machine, an open-source road-routing library. The dataset records an OSRM travel-time estimate for every segment. We use that column as the estimate to audit; we cannot know how Delhivery itself used it.",
  },
  {
    term: "Overrun",
    definition:
      "How much longer a corridor's legs take than their OSRM estimate, relative to what the whole network does. 1.0x is exactly typical; above is worse, below is better.",
  },
  {
    term: "Excess ratio",
    definition:
      "The corridor's overrun divided by the network's overrun. Another name for the overrun column on the corridors page.",
  },
  {
    term: "Typically late",
    definition:
      "The median number of minutes a corridor's legs took beyond their OSRM estimate.",
  },
  {
    term: "Dwell",
    definition:
      "Time a shipment spends parked at a facility rather than moving. Measured as the scan-to-scan interval minus the realised moving time.",
  },
  {
    term: "Support",
    definition:
      "How many legs a corridor's statistic rests on. A 13.9x overrun on 13 legs and a 1.5x on 100 are not equally trustworthy, so every ranked row prints it.",
  },
  {
    term: "Support floor",
    definition:
      "The minimum number of legs a corridor needs to be tested at all. Raising it from 10 to 30 legs changes the top-20 list completely, which is why the corridors page lets you switch.",
  },
  {
    term: "Welch's t-test",
    definition:
      "A comparison of two averages that does not assume equal spread. Here it compares one corridor's log time ratios against the rest of the network.",
  },
  {
    term: "FDR (false discovery rate)",
    definition:
      "Test 1,130 corridors at a 5% significance level and about 56 will look significant by luck alone. Benjamini-Hochberg control instead caps the share of false findings among those reported at 5%.",
  },
  {
    term: "q-value",
    definition:
      "A p-value adjusted for testing many corridors at once (Benjamini-Hochberg). A corridor with q below 0.05 is significant at a 5% false discovery rate. Values under one in a million print as < 1e-6.",
  },
  {
    term: "Wilson interval",
    definition:
      "A 95% confidence range for a proportion that stays sensible at small samples and near 0% or 100%. Every agent score on the site carries one.",
  },
  {
    term: "Trivial policy",
    definition:
      "The cheapest rule that needs no intelligence, such as approving every invoice or notifying on every alert. A score only means something beside it.",
  },
  {
    term: "Empirical Bayes",
    definition:
      "A way of ranking many noisy estimates by pulling the ones with little data toward the overall average, so a lucky small sample stops topping the list.",
  },
  {
    term: "Back-off",
    definition:
      "A baseline that uses a corridor's own history when it has enough and falls back to a coarser group (for example its origin) when it does not, instead of falling back to the OSRM estimate.",
  },
  {
    term: "Residual",
    definition:
      "What is left after subtracting a baseline. This model predicts the residual over each corridor's own median, so learning nothing reproduces the strongest baseline rather than a weaker one.",
  },
  {
    term: "MAE",
    definition:
      "Mean absolute error: the average size of a mistake in minutes. It is minimised by the median, which is why the median is the bar a model here has to beat.",
  },
  {
    term: "As-of",
    definition:
      "A feature computed only from journeys that had already finished when the leg being predicted was created. The alternative leaks the future into the past.",
  },
  {
    term: "Cold start",
    definition:
      "A corridor with no earlier journeys in the training data. Most of the model's margin over the median comes from these.",
  },
  {
    term: "Replay",
    definition:
      "Feeding recorded events back through the system in their original order. The alert page is a replay of a recorded run, not a feed of today's shipments.",
  },
  {
    term: "Gradient-boosted trees (GBT)",
    definition:
      "A model made of many small decision trees, each correcting the mistakes of the ones before it. The reported model is a GBT trained on the residual over the corridor median.",
  },
  {
    term: "Spark",
    definition:
      "Apache Spark, the engine that cleans the 144,867 scan records, rebuilds journeys and aggregates corridors across many cores.",
  },
  {
    term: "MLlib",
    definition:
      "Spark's machine-learning library. The delay model is trained and served with it.",
  },
  {
    term: "Kafka",
    definition:
      "A message broker. Events are published to a Kafka topic and a Spark Structured Streaming job reads them, scores each leg and raises alerts.",
  },
  {
    term: "Parquet",
    definition:
      "A compact columnar file format. The cleaned data is cached as Parquet so later stages read it quickly.",
  },
  {
    term: "TMS",
    definition:
      "Transport management system: the booking system orders are filed into. Here it is a mock service, though its facility codes are the real ones.",
  },
  {
    term: "Vector index",
    definition:
      "A search index over the project's own documents, built from text embeddings. The analytics assistant retrieves from it and refuses when nothing relevant is found.",
  },
  {
    term: "MCP (Model Context Protocol)",
    definition:
      "An open protocol for giving an AI agent tools. The agents reach corridor statistics, predictions, the TMS and vector search through an MCP server.",
  },
  {
    term: "LangGraph",
    definition:
      "A library for building agents as a graph of steps. The orchestrator is a LangGraph graph that routes an email through intake, booking, monitoring and triage.",
  },
  {
    term: "Orchestrator",
    definition:
      "The graph that connects the five agents into one lifecycle: an order email in, a booked order and, if it runs late, a ticket out.",
  },
  {
    term: "Groundedness",
    definition:
      "Whether every number in an answer appears in the context the assistant was given. Judged by hand on saved answers.",
  },
  {
    term: "Stratified set",
    definition:
      "An evaluation set built with a fixed number of cases per kind, so hard cases are a named share. Its overall rate describes the design, not real traffic.",
  },
  {
    term: "Held-out",
    definition:
      "Scored on cases the system was not tuned on. A score on a set that motivated a fix is not held out.",
  },
];

/** Terms the pages use and rely on the glossary to explain. */
export const REQUIRED_TERMS = [
  "MCP",
  "LangGraph",
  "Kafka",
  "Spark",
  "MLlib",
  "TMS",
  "Parquet",
  "Vector index",
  "As-of",
  "FDR",
  "q-value",
  "MAE",
  "Residual",
  "Support floor",
  "OSRM",
  "Dwell",
  "Corridor",
  "Leg",
  "Back-off",
  "Empirical Bayes",
];
