---
title: Agentic AI Logistics Control Tower
emoji: 🚚
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8501
pinned: false
short_description: Corridor audit, delay model and agent evaluation on Delhivery data
---

# Agentic AI Logistics Control Tower — dashboard

The read-only dashboard of a project that audits where a production routing engine is
systematically wrong on India's road-freight network, predicts how late each leg will run,
and evaluates a small team of deterministic-core agents.

**What works here:** the corridor audit, the India map, hub friction, the agent console's
MCP transcript, the analytics assistant's 30-question scorecard and the prompt library —
every number is read from a committed benchmark file.

**What does not run here, by design:** anything that needs Spark, a trained model, the
vector index or a language model. Those pages say what is missing instead of failing. The
full system — streaming, agents, the TMS — runs from the repository with one command; this
Space is the part that needs nothing but a browser.
