# CONTRIBUTING.md — working rules for this repository

Read this **and** [`GIT_RULES.md`](GIT_RULES.md) fully before touching anything.

**Precedence.** `GIT_RULES.md` governs branching, PRs, docs, and gates. *This* file
governs commit discipline, authorship, pushing, and pacing. Where the two describe the
same thing differently, this file wins for commit messages; `GIT_RULES.md` wins for
branch and PR mechanics.

---

## 1. Project in one line

An 8-week, 3-member build: a PySpark + Kafka big-data pipeline that audits and beats a
production routing engine on real Delhivery data, with five LangGraph agents acting on
its predictions. Members: **Krishna** (agents, dashboard) · **Lahari** (ML, all
evaluation) · **Mounika** (data, TMS, streaming, MLOps).

## 2. When to commit

Every meaningful change gets its own commit, pushed immediately. Meaningful means: a
feature, a file created or deleted, a refactor, a bug fix, a structure change, docs, a
config change, a UI improvement, a pipeline change, or a completed milestone.

After each meaningful change, in this order:

1. **Verify the project still runs.** Not "it looks right" — run it.
2. **Read the diff** of what you're about to commit.
3. **One small, focused commit** covering only the related change.
4. **Push before starting the next task.** Unpushed work does not exist.

## 3. Commit messages

Short, lowercase, imperative, one change, ~50 characters. Write like a developer:

```
add project structure          create dataset loader
fix preprocessing bug          update training config
connect dashboard backend      add evaluation script
clean up imports               update requirements
```

**If a commit produces a number, put the number in it:**

```
gbt beats osrm: mae 41.2 vs 52.7
invoice_no accuracy 0.71 -> 0.93
sustained 1.4k events/sec, p95 820ms
```

**Banned.** `update` · `changes` · `final` · `work done` · `minor fix` · `commit` ·
`asdf` · `week5 work` — and marketing phrasing: *"Implement comprehensive…"*,
*"Refactor architecture…"*, *"Enhance robust…"*, *"Add extensive…"*,
*"Optimize pipeline…"*.

The `commit-msg` hook enforces all of this. It is not advisory.

## 4. Authorship — three real accounts

Every commit is authored by the task's **actual owner** per the plan's task table, and
**every branch is pushed with that owner's credentials.** Never commit or push
everything from one account — the contributor graph is a graded deliverable
(GIT_RULES §9).

**One commit, one owner.** Co-author trailers are rejected by the hook. Work done in a
pair is either two commits or one commit on whoever's branch it is; authorship belongs
in the author field, never in the message body.

Identities and per-member PATs live in `.env.git` (gitignored; template at
`.env.git.example`). Use the wrapper:

```bash
scripts/gitas.sh lahari commit -m "add corridor audit t-test"
scripts/gitas.sh lahari push -u origin week2-lahari-corridor-audit
scripts/gitas.sh mounika whoami          # check identity resolves
```

Each member generates their **own** fine-grained PAT (Contents: read and write, scoped
to this repo only). Tokens are never shared, never pasted into chat, never committed.
Krishna owns the repo, so Lahari and Mounika must be added as collaborators first —
and the collaborator list is exactly those three accounts, nothing else.

## 5. Timestamps — real only

**Never set `GIT_AUTHOR_DATE` or `GIT_COMMITTER_DATE`** on new work. Commits are dated
when they are actually made. (Preserving the original date while rebasing or
cherry-picking an existing commit is fine — that is keeping a real date, not inventing
one.)

If the history should read day-by-day, then the work is *done* day-by-day. Do not
finish a week and replay it as a fake daily trail.

## 6. Pacing

**Do not complete and push an entire week's work in one sitting.**

Work the plan task-by-task in its planned order, and stop at each day's task boundary
(D1–D5 in the execution plan). A member who genuinely finishes early reviews a
teammate's PR, writes their weekly doc, or reads for their survey thread — they do
**not** start next week's branch until `dev → main` is merged for the current week.

## 7. Branches, PRs, gates

Exactly GIT_RULES §5–§8: `week<N>-<name>-<topic>` branched from the latest `dev`;
branches never deleted; no shared branches; the weekly doc written *before* the PR
opens; **no self-merge**; merge commits only (never squash, never rebase a shared
branch); `dev → main` once per completed week, tagged.

**One branch per member per week — no more.** Everything you do in a week lands on
that single branch, including side fixes and tooling. A second branch splits your
week's contribution across two places and makes the graph harder to read, not easier.

**One document per member per week — no more.** Everything you did that week goes in
`docs/W<N>_<name>_<main task>.md`, whatever number of tasks it covers. Two files for
one member-week is the same mistake as two branches.

## 8. Hooks

```bash
git config core.hooksPath .githooks      # once per clone, per member
```

- `commit-msg` — blocks co-author and attribution trailers, banned vague messages,
  marketing wording, capitalised or over-long subjects.
- `pre-commit` — blocks secrets (`.env`, `.env.git`, key-shaped strings), anything
  under `data/` except its README, files over 50 MB, and notebooks with output cells.

If a hook fires, fix the cause. `--no-verify` needs a reason you can defend out loud.

**Known gap — read this once.** `core.hooksPath` points at a path *inside the working
tree*, so the hooks only exist on branches that contain `.githooks/`. Check out a
branch created before this landed and **you are committing unprotected**. Two
consequences:

- Merge this to `dev` early, so every branch cut from `dev` inherits the hooks.
- The hooks are a safety net, not the fence. `.env` and `.env.git` are also listed in
  `.git/info/exclude`, which is local and branch-independent, so they stay ignored even
  on a branch whose `.gitignore` predates them. Run this once per clone:

  ```bash
  printf '.env\n.env.git\n' >> .git/info/exclude
  ```

Verified working: staging `.env.git`, a key-shaped string, or anything under `data/`
is rejected.

## 9. Environment

```bash
python -m src.common.check_env           # Gate check — run before claiming anything works
```

- Python 3.13 · **PySpark 4.0** (3.5.x has no cp313 wheels and will hang building)
- JDK 17 required for Spark; portable Temurin zip avoids the UAC prompt
- Windows Parquet writes need `winutils.exe` + `hadoop.dll` with `HADOOP_HOME` set
- Virtualenv lives **outside** the OneDrive folder — a multi-GB `.venv` inside a synced
  directory will thrash sync and quota

## 10. Verification standard

Claims in docs, commits, and PRs must come from **running the code**, not from reading
it. Week 1 produced two bugs that were invisible to inspection and would have silently
corrupted results — mixed-precision timestamps and a name-backfill built on a false
premise. Both were caught by executing. Week 2 produced a third: a hub-dwell metric
that looked correct and measured nothing.

Where a number appears in a report or the paper, it must trace to a file in
`benchmarks/` produced by a script in `src/`. Problems worth the next person's time go
in [`docs/problems.md`](docs/problems.md) as they happen.

## 11. The point of all this

The strongest defence at the viva is not a tidy commit graph — it is each member being
able to open any file in their folders and explain it line by line: why that function
exists, what breaks without it, and which number in `benchmarks/` it produced.

So own your folders. If you cannot explain a file you committed, you have not finished
the task — go back through it, change what you would have written differently, and
re-commit it as your own.
