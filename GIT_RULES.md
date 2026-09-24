# GIT_RULES.md — Agentic AI Logistics Control Tower

Repository workflow rules for the 3-member team: **Krishna · Lahari · Mounika**

Modeled on the week-branch pattern (`weekN-<work-topic>`), adapted for per-member contribution
tracking. **These rules are mandatory.** They exist so that (a) faculty can see each member's weekly
contribution at a glance, and (b) the repo itself becomes a portfolio artifact.

---

**Adopted 24 September 2026 (post-v1.0 revision):** §0 (only the three members appear), the
strengthened §7, §11 (history rewrites) and §12 (permanent priorities) were added. §1–§6 and §8–§10
stand as they were during Weeks 1–8.

---

## 0. Only the three members appear — strict, permanent, whole repository

Editors, code generators, AI assistants, scripts, bots and any other tool are never contributors. On
**every branch, every commit, every PR**:

- Never add a `Co-authored-by:` trailer for anyone who is not Krishna, Lahari or Mounika.
- Never use a tool's, bot's or third party's name, username or email as git author, committer or identity.
- Never configure anything other than your own GitHub identity as `user.name` / `user.email`, locally or globally.
- No tool name, tool-generated footer ("Generated with …", "Made by …", "Written by …", "on behalf of …")
  or tool configuration file appears in commit metadata, commit messages, PR titles, PR descriptions,
  release notes, docs, code comments or anywhere in the tree. Tool-specific files (`CLAUDE.md`,
  `.claude/`, `.cursor/`, `.copilot*`, `AGENTS.md` and similar) are excluded through `.git/info/exclude`
  on each machine — never through the committed `.gitignore`, which would itself be a trace.
- Nobody but the three members ever shows up under GitHub Insights → Contributors.
- If an assistant is used to draft code or text, the member reads it, verifies it, and commits it
  under their own identity with a message in their own words. The member is the author.

Every commit is authored **and** committed by the member who owns the branch (§5, §9) — nobody else.
Before every commit, verify author, committer and trailers (§7 "Before every commit"). The
`.githooks/commit-msg` hook rejects co-author trailers and attribution lines; the hook is a backstop,
not the rule.

This rule overrides any default behaviour of any tool being used.

---


## 1. Repository Structure

```
agentic-logistics-control-tower/
├── README.md                  # project overview, architecture image, quickstart, results table
├── GIT_RULES.md               # this file
├── .gitignore                 # data/, .env, checkpoints, __pycache__, *.parquet
├── .env.example               # names of required keys, never real values
├── requirements.txt
├── src/
│   ├── pipeline/              # Mounika — cleaning, reconstruction, features
│   ├── ml/                    # Lahari  — training, evaluation, ablations
│   ├── streaming/             # Mounika — Kafka producer, structured streaming job
│   ├── tms/                   # Mounika — mock TMS (FastAPI + SQLite)
│   ├── agents/                # Krishna — all five agents + orchestrator + MCP server
│   │   └── prompts/           # versioned prompt library (v1, v2 … kept, never overwritten)
│   ├── dashboard/             # Krishna — Streamlit control tower
│   └── automation/            # retraining script, alert bot
├── docs/                      # week-wise documentation (see §2)
├── demo/                      # demo assets (see §3)
├── benchmarks/                # performance + evaluation results (see §4)
├── notebooks/                 # exploration only: w3_lahari_baselines.ipynb naming
└── data/                      # gitignored; data/README.md explains how to download
```

---

## 2. `docs/` — week-wise documentation

**Exactly one markdown file per member per week** — named `W<N>_<name>_<main task>.md`, numbered for
ordering:

```
docs/
├── W1_krishna_agent_env_setup.md
├── W1_lahari_data_dictionary_and_eda.md
├── W1_mounika_repo_and_cleaning.md
├── W2_krishna_india_map.md
├── W2_lahari_corridor_audit.md
├── W2_mounika_reconstruction_hubs_and_tms.md
├── …
├── W8_*
├── decisions.md               # running log from weekly syncs
├── problems.md                # what went wrong, why, and how it was fixed
└── results.md                 # frozen numbers (Lahari owns)
```

Each weekly doc is short (half a page is fine) and answers: **what I built, how to run it, what the
numbers/outputs are, what's next.** Written *before* opening your weekly PR — the PR is not
reviewable without it.

**A week's work goes in one file even when several tasks or several scripts produced it.** If two
generators write into the same weekly doc, each owns a delimited section via `src/common/docs.py`
rather than its own file — that is what re-split Lahari's Week 1 doc in two before it was fixed.
Same rule for branches (§5): one per member per week, side fixes included.

`problems.md` is everyone's. Add an entry the day you lose time to something, while you still
remember what you tried — symptom, cause, fix, what it cost.

---

## 3. `demo/`

```
demo/
├── demo_script.md             # the rehearsed viva flow, step by step
├── screenshots/               # weekly dashboard/agent screenshots (W2_map.png …)
├── sample_events/             # small JSON event samples for the replay
├── sample_documents/          # 5–10 example synthetic BOLs/invoices (not the full corpus)
└── video/                     # final 2–3 min screen recording (or link in README)
```

---

## 4. `benchmarks/`

```
benchmarks/
├── ml_results.md              # model vs OSRM: MAE/RMSE tables, per-corridor gains
├── streaming_throughput.md    # sustained events/sec, event→alert latency
├── agent_evaluation.md        # extraction accuracy, exception precision, groundedness …
├── scale_appendix.md          # same Spark code on 50M+ NYC taxi rows: runtime table
└── raw/                       # csv/json outputs that produced the tables above
```

**Every number in a report or the paper must be traceable to a file in `benchmarks/` produced by a
script in `src/`.**

---

## 5. Branch Model

### Permanent branches
- **`main`** — default. Only stable, demo-ready, reviewed code. *Nobody commits directly to main. Ever.*
- **`dev`** — integration branch where the week's PRs land first.

### Weekly work branches
One per member per week, named `week<N>-<name>-<work-topic>`:

| Week | Krishna | Lahari | Mounika |
|------|---------|--------|---------|
| 1 | `week1-krishna-agent-env` | `week1-lahari-data-dictionary` | `week1-mounika-repo-cleaning` |
| 2 | `week2-krishna-india-map` | `week2-lahari-corridor-audit` | `week2-mounika-trip-reconstruction` |
| 3 | `week3-krishna-doc-corpus` | `week3-lahari-baselines` | `week3-mounika-feature-pipeline` |
| 4 | `week4-krishna-doc-agent` | `week4-lahari-beat-osrm` | `week4-mounika-auto-retrain` |
| 5 | `week5-krishna-order-entry` | `week5-lahari-stream-validation` | `week5-mounika-kafka-streaming` |
| 6 | `week6-krishna-orchestrator` | `week6-lahari-agent-eval` | `week6-mounika-vectordb-integration` |
| 7 | `week7-krishna-rag-assistant` | `week7-lahari-eval-report` | `week7-mounika-scale-benchmark` |
| 8 | `week8-krishna-demo` | `week8-lahari-paper-tables` | `week8-mounika-release` |

**Rules**
- The topic is **the work**, not the person's role: `week5-mounika-kafka-streaming`, never `week5-mounika-stuff`.
- Lowercase, hyphen-separated, no spaces or underscores in branch names.
- Branch from the latest `dev` on Day 1 of the week. **Never branch from another member's weekly branch.**
- **Branches are never deleted after merge** — the branch list itself is the week-wise progress record.
- **No shared branches**: if two members pair on a task, it lives on the owner's branch; the helper reviews the PR.

### Post-v1.0 work-order branches

After the `v1.0` tag the weekly pattern ends. Work continues on the execution plan's work packages,
one branch per package, `wo-<id>-<name>-<topic>` (e.g. `wo-01-mounika-ci-and-readme`,
`wo-03-krishna-nextjs-network-map`). One owner per branch; the same rules as weekly branches
(from latest `dev`, never deleted, never shared, PR → `dev` with the package's evidence file named
in the description). Release merges `dev` → `main` are tagged `v1.1-web`, `v1.2-cloud`, and so on.

---

## 6. Weekly Merge Cycle (completion-based, not calendar-based)

The cycle is driven by **finishing the week's work**, not by weekdays. A "week" ends when its tasks
are done — whether that takes 4 days or 6.

1. **Start of week:** create your `week<N>-<name>-<topic>` branch from the latest `dev`.
2. **During the week:** commit to your own branch every day you work (§7). **Push the same day —
   unpushed work doesn't exist.**
3. **When YOUR week's work is complete:** write `docs/W<N>_<name>_<topic>.md`, update `benchmarks/`
   if you produced numbers, then open a **Pull Request → `dev`** and message the team group:
   *"Week N done — PR up."*
4. **Review:** your reviewer approves (Krishna ↔ Lahari review each other; Mounika reviewed by
   whoever is free). Reviewer checklist in §8. **Merge with a merge commit** (no squash — the daily
   history is the contribution evidence; no rebase on shared branches).
5. **When ALL THREE weekly PRs are merged and the week's gate passes:** the team confirms together
   ("Week N complete"), then one member (rotating: W1 Mounika, W2 Krishna, W3 Lahari, repeat) opens
   the `dev` → `main` PR titled `Week N: <gate summary>`, merges it, and tags:

```bash
git tag -a week1-complete -m "Gate 1: cleaned parquet v1, env working"
git tag -a week2-complete -m "Gate 2: corridor audit + india map (audit-v1)"
…
git tag -a v1.0 -m "Final release: full system + benchmarks"
git push --tags
```

So `main` advances exactly once per completed week, always green, always demoable — and the tag list
reads as the project timeline.

> If one member finishes early, they review others' PRs or start reading for the paper — they do
> **not** start their next week's branch until `dev` → `main` for the current week is merged, so
> every new branch starts from the same baseline.

---

## 7. Commit Quality Rules

**Format:** a short lowercase imperative that names the change. No bracketed prefix, no area tag,
no body unless the change genuinely needs one. If it sounds like something you would say to a
teammate, it is right. Aim for about 50 characters; go longer only when a number or a specific
detail needs the room.

**Core principle:** fewer, stronger commits beat many small ones. Before committing, ask: *"Is this
worth appearing in the project's history?"* If not, keep working and group it with related work.

A commit-worthy unit is one of: a completed feature, a substantial bug fix, a meaningful refactor, a
completed module or pipeline stage, a meaningful documentation update, a plan milestone, or a coherent
group of related changes. Not commit-worthy: one small line, one reworded sentence, formatting, a tiny
doc correction, an import cleanup, one insignificant file, or repeated "fix"/"update"/"change" commits
for the same piece of work.

### Good commits (each one is a working, explainable step)
```
reconstruct trips from segments using window functions
add welch t-test with bh correction to the corridor audit
30-leg support covers 19% of legs, 10-leg covers 79%
beat the osrm baseline: gbt mae 41.2 vs osrm 52.7 on holdout
add bol field-extraction prompt v2, invoice_no 0.71 -> 0.93
join broadcast corridor features in the streaming job
record sustained 1.4k events/sec, p95 event->alert 820ms
handle cutoff timestamps missing a timezone
run the pytest suite in ci on every pull request
draw the 1130 audited corridors as deck.gl arcs on the network page
```

### Banned commits (instant PR rejection)
```
update            final           final2            asdf
changes           work done       minor fix         commit
updated code      week5 work      lahari changes    pushed files
[W2][DOCS] ...    [W4][ML] ...    any bracketed prefix at all
```

A bare `update` or `fix` is banned; a specific one is fine: `fix producer dropping the last batch`,
`update pyspark floor to 4.0 for cp313 wheels`.

### Also banned — inflated messages
```
implement comprehensive architecture      introduce advanced functionality
enhance robust pipeline                   complete implementation of ...
add extensive improvements                improve overall system
refactor architecture                     optimize pipeline architecture
```

Say what changed, not how impressive it is. The `commit-msg` hook rejects the obvious cases.

**Rules**
- **A commit is a unit of work you would describe out loud**, not a save point. Prefer four commits
  with weight over fifteen that each touch one file.
- **One logical change per commit.** "Built the whole streaming job" is a *branch*, not a commit —
  break it into: producer skeleton → schema parsing → feature join → model apply → sink.
- **Don't split artificially.** A single feature's code, config, helpers, tests and docs go in **one**
  commit — never spread across several to inflate the count. Don't mix unrelated work either.
- **No commits for trivia.** Fold a one-line tweak, a reworded sentence, formatting or an import
  cleanup into the next meaningful commit on the same work.
- **Don't leave finished work uncommitted.** When a meaningful piece of work is complete: (1) finish
  the implementation, (2) verify the project still works, (3) review the changed files, (4) check only
  intended changes are included, (5) create one focused commit, (6) push it, (7) then start the next task.
- **Commit messages are written by the member, in their own words**, describing what actually
  changed — never exaggerated, never generated boilerplate.
- The message must let a teammate know what changed **without opening the diff**. If a commit changed
  a number, **put the number in the message** — these become contribution highlights.
- **Commit working code.** Broken WIP at end of session: `wip: sink schema mismatch, see TODO` — and
  it may **not** be the branch's final commit before the PR.
- **Never commit:** raw data, `.env`, API keys, `*.db`, model binaries over 50 MB, notebook output
  cells (`nbstripout --install`), or any tool-specific file listed in §0.
- **If a secret is ever committed:** rotate the key immediately, add an entry in `problems.md`, and do
  **not** try to hide it with a force-push (§11).

### Before every commit

Never blindly `git add -A` or `git add .`. Stage explicit paths and check each item:

1. `git status` — only intended files; nothing unrelated.
2. `git diff --cached` — read the actual diff, not just the file list.
3. No secrets, `.env`, `*.db`, raw data, model binaries, notebook outputs or tool files (§0).
4. The project still runs / tests pass where practical.
5. `git config user.name` and `git config user.email` are the **branch owner's** (§9). One laptop may
   be shared, so check every session.
6. Only a member identity in author, committer, message or trailers (§0). After committing, verify:
   `git log -1 --format='%an <%ae> | %cn <%ce>%n%B'`.

### Pushing

- Push to the existing remote `origin` only. Never create another repository and never change the
  remote without the whole team agreeing.
- Push with the branch owner's own GitHub account; never switch to another account.
- Push to the branch you committed on, right after the commit.
- Never force-push (see §11 for the one exception).

---

## 8. Pull Request Rules

**PR title:** `[W<N>] <name>: <work-topic summary>`
e.g. `[W4] Lahari: GBT models beat OSRM baseline (+ablations)`

The PR description template lives in `.github/pull_request_template.md`.

**Reviewer must check (15 minutes, not a formality):**
- Pulls the branch and **runs the stated verify step**.
- Scans commit messages for §7 compliance.
- Confirms the weekly doc exists and matches what the code does.
- Leaves **at least one substantive comment** (question, suggestion, or explicit "verified X works").

Rubber-stamp approvals defeat the purpose — the review comments are also contribution evidence.

---

## 9. Contribution Visibility (what faculty will see)

This workflow automatically produces four proofs of individual weekly contribution:

1. **Branch list** — 24 branches named `week<N>-<name>-<topic>`, readable as a per-member timeline.
2. **Commit history** — daily, self-describing commits under each member's own name.
   **Everyone must configure their real identity before Week 1:**
   ```bash
   git config user.name  "Lahari"
   git config user.email "lahari@example.com"   # the email on their GitHub account
   ```
3. **`docs/` folder** — one signed weekly writeup per member.
4. **PRs + reviews** — who built what, who verified what, every week.

GitHub's *Insights → Contributors* graph reflects true effort **only if §7 is followed** — which is
exactly why vague bulk commits are banned.

---

## 10. Conflict and Emergency Rules

- **Merge conflicts** are resolved by the **branch owner**, with the file's area owner (per §1 folder
  ownership) consulted — never resolved blind.
- **Hotfix on main** (demo-day breakage only): branch `hotfix-<topic>` from `main`, PR back to
  **both** `main` and `dev`, reviewed by any teammate. Used sparingly; hotfixes are not a backdoor
  around the weekly cycle.
- **If a member's week slips:** the PR still opens when the team closes the week, with whatever is
  done **plus the doc stating what's missing**; the gap moves to next week's branch. An honest
  partial PR beats a silent missing week.
- **Force-push and history rewrites** are governed by §11. A `--force-with-lease` rejection means the
  remote moved — stop and look, never retry after a quick fetch.

---

## 11. History Rewrites

Default: **never**. A rewrite happens only to fix commit metadata (wrong author, committer, or a
non-member identity/trailer), and pushing it needs explicit approval from the branch owner — plus the
whole team if the branch is `main` or `dev`.

When a rewrite is approved:

- Change metadata only. File contents and code stay exactly as they were.
- Keep the same commits in the same order, with the same messages.
- Keep the original author **and** committer dates. Rewritten commits must not look like they were
  made today.
- Remove the unwanted author, committer or co-author data. Never add a non-member identity while doing it.
- Scope it to only the commits that need it; never rewrite a commit that predates the change without asking.
- Verify before pushing: `git log --format='%h %an <%ae> %ad | %cn <%ce> %cd'`, and
  `git diff <old-tip> <new-tip>` must be empty.
- Force-push only after that approval, with `--force-with-lease`, and log it in `problems.md`.

The objective of any approved rewrite: **same project content + same commit timeline + corrected
metadata.** Nothing else changes.

A leaked secret is **not** a reason to rewrite. Rotate the key instead (§7).

---

## 12. Permanent Priorities — apply to everything, every branch, every task

These rules apply to the entire repository and all future work unless all three members change them.

1. **Only the three members appear anywhere in git metadata** (§0).
2. **Meaningful commits only** (§7).
3. **Group related work instead of creating tiny commits** (§7).
4. **Keep the history clean, natural and professional** (§7, §8).
5. **Verify changes before committing** (§7 "Before every commit").
6. **Use only your own git identity** (§9).
7. **Push meaningful completed work to the existing repository only** (§7 "Pushing").
8. **Every number traces to a file in `benchmarks/raw/`** (§4).

### Most important rule

> **Never let anyone or anything other than Krishna, Lahari or Mounika appear as contributor, author,
> co-author, committer or trailer — and never create meaningless commits just to increase the count.**

---

*Adopt this file as-is in the repo root. Any rule change requires agreement of all three members and
a commit to this file explaining the change.*
