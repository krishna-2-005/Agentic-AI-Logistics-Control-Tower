---
title: Agentic Control Tower API
emoji: 🚚
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Read-only API behind the Control Tower site's live pages
---

# Agentic AI Logistics Control Tower: public API

The API behind the four live pages of
[the project site](https://control-tower-mu-rouge.vercel.app). Source and every number:
[github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower).

| Route | What it serves |
|---|---|
| `GET /health` | liveness, and whether the model is warm |
| `POST /api/predict` | how late a leg will run, from the **v2 residual GBT the results report** (30.90 min test MAE), with corridor history as of the departure. Every answer names its model. |
| `GET /api/predict/status` | `warming` for about 30 s after the container wakes, then `ready` |
| `GET /api/alerts` | alerts from a **recorded run** of the v2 stream over the 2018 data, released in event-time order. This container runs no live stream, and every response says so. |
| `GET /api/traces` | the newest agent calls (timing and outcome only, never what a visitor typed) |
| `POST /api/ask` | the analytics assistant. Extractive by default; a language-model answer is opt-in and capped at **10 a day** for everyone. |

**What is not here:** the mock TMS and anything that writes. Every TMS route is a 404.

**Limits:** 30 predictions a minute per visitor and 2 running at once, 5 questions a minute,
bounded inputs, 4 KB bodies. Over a limit is a `429` with `Retry-After`, which the site shows
as "busy".

The free container sleeps when idle; the first request after that waits for Spark to start.
