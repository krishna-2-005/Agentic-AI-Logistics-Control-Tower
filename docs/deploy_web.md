# Deploying the web control tower

**Owner: Mounika.** Supersedes `deploy_dashboard.md`, which described publishing the
Streamlit bundle to a Hugging Face Space (D-061).

**Live:** <https://control-tower-mu-rouge.vercel.app>

---

## 1. What is deployed, and what is not

| | where | needs a backend? |
|---|---|---|
| Overview, Network, Corridors, Hubs, Evidence, Prompts, About | Vercel, static | no |
| Predict, Live alerts, Agent traces, Assistant | Vercel, static shell → API at runtime | **yes** — not deployed yet (W-01) |

The four live pages are built and they degrade honestly: with no API configured each one
says so in plain English and shows the recorded evidence instead. That is a deliberate
state, not a placeholder — a page that shows old rows while implying they are live is the
failure mode D-054 caught us in once already.

## 2. How a change reaches the site

```
edit benchmarks/raw/…            (a stage re-runs and writes a new number)
  └─ python -m src.report.export_web      → web/public/data/*.json
       └─ git push                         → Vercel builds and deploys
```

**The site's numbers move only when a benchmark file moves.** Nothing on the site is typed
by hand; `export_web.py` is the only writer of `web/public/data/`, and
`tests/test_web_numbers.py` diffs what it wrote against `results_freeze_v3.json`.
`.github/workflows/web.yml` re-runs the export in CI and **fails the build if the committed
JSON differs**, so a stale export cannot merge.

## 3. Vercel project settings

Configured once, recorded here because a setting that lives only in a dashboard is a
setting nobody can review.

| setting | value | why |
|---|---|---|
| Repository | `krishna-2-005/Agentic-AI-Logistics-Control-Tower` | connected through Vercel's GitHub integration |
| **Root directory** | **`web`** | the Next.js app is not at the repo root. With the default `.` a git build fails immediately — this is the one setting that is easy to get wrong |
| Framework preset | Next.js | auto-detected |
| Build command | `next build` | preset default; `output: 'export'` in `next.config.ts` makes it static |
| Production branch | `main` | Vercel's default |
| Deployment protection | **off** | previews must be clickable by reviewers who have no Vercel account (plan §3.1) |
| `NEXT_PUBLIC_API_URL` | *unset* | set it when the API Space exists; the site works without it |

### Which URL updates when

| you push to | URL that changes |
|---|---|
| `main` | <https://control-tower-mu-rouge.vercel.app> (production) |
| `dev` | <https://control-tower-git-dev-kuchurusaikrishnareddy-2388s-projects.vercel.app> |
| any branch, in a PR | a fresh preview URL, commented on the PR |

**To make `dev` pushes land on the production URL** — Vercel dashboard → the project →
Settings → Git → Production Branch → `dev`. There is no API for this field; it is a
dropdown. Leave it on `main` if you would rather the public URL only move at a release,
which is what the plan's F2 gate assumes.

## 4. Deploying by hand

Normally unnecessary — git push is the deployment path. When you need it:

```bash
cd web
pnpm install
pnpm build            # writes web/out/
npx vercel --prod     # or drop --prod for a preview URL
```

## 5. Rollback

Vercel keeps every deployment. Dashboard → Deployments → the one that worked → **Promote to
Production**. One click, no rebuild. Prefer this to a revert commit when the site is broken
and the cause is not yet understood.

## 6. Cost

**$0.** Vercel Hobby: 100 GB bandwidth a month against a site whose largest page is about
1 MB, most of which gzips. Recorded in `docs/cost.md` so the Phase 3 baseline stays true.

## 7. Secrets

There are none in `web/`, by construction (D-062). The build is public the moment it
deploys, so anything committed under `web/` is published — the CI job greps the built
bundle for credential patterns and fails on a hit. When the API Space exists, its
`GEMINI_API_KEY` lives as a Space secret and the browser never holds it: the frontend asks
the API, and the API asks the model.

## 8. Still to do (W-01)

The API is designed and not built. `src/api/app.py` mounts beside the TMS routes on one
uvicorn process and wraps four functions that already exist:

| endpoint | wraps |
|---|---|
| `POST /api/predict` (+ `/status`) | `src.ml.predict.predict_delay()` — lazy SparkSession, kept warm |
| `GET /api/alerts` | `src.dashboard.alerts.load_alerts()` |
| `GET /api/traces` | `src.agents.tracing.read_traces()` |
| `POST /api/ask` | `src.agents.analytics_assistant.answer()` — `use_llm=false` by default |

`web/lib/api.ts` is already written against these shapes, so the frontend needs no change
when they land: set `NEXT_PUBLIC_API_URL` in Vercel and the four pages switch from recorded
evidence to live.
