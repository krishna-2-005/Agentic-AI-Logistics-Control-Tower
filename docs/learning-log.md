# Learning log — Krishna

Execution plan §5. One entry per week: which role skill the week actually practised, and
what I would say about it if asked. Kept because "what have you built with agents?" is
better answered with a specific thing that ran than with a framework name.

The plan's schedule: W1 LangGraph basics · W3 document generation/OCR · W4 prompt
iteration against evals · W5 API integration patterns · W6 multi-agent orchestration +
MCP · W7 RAG + evaluation/monitoring.

---

## Week 1 — LangGraph basics, and one construction site for the model

**Built:** a LangGraph hello-world agent that actually runs, the Streamlit skeleton with
navigation, and the versioned prompt-library structure.

**The skill underneath the tutorial.** LangGraph's own hello-world is ten lines and
teaches nothing that survives contact with a second agent. The two decisions I made
around it are the ones I would talk about:

- **D-007 — every agent gets its model from `src.agents.llm.get_llm()`, and no agent
  constructs a provider client.** Free tiers rate-limit and change. With one call site,
  swapping provider is a `.env` edit rather than five edits across five agents,
  automatic fallback keeps a Week 7 evaluation run from dying half way through, and the
  trace viewer has exactly one log shape to read.
- **D-008 — prompts are files at `prompts/<agent>/v<N>.md` and a new version is a new
  file.** The old one is never overwritten. This is the difference between claiming
  "invoice_no accuracy went 0.71 → 0.93" and being able to show it: the prompt that
  scored 0.71 still exists and can be re-run.

**What I would say in an interview:** the interesting part of agent work is not the
graph, it is that everything around the model is going to change under you — provider,
rate limit, prompt — and the design question is where you put the seams.

---

## Week 2 — reading data honestly before drawing it

**Built:** the India map and the hub-friction leaderboard, both reading only cached
CSVs; the centre-code coordinate table; the synthetic-document layout research for
Week 6.

Not an agent week on paper, and it turned out to be the most useful week so far for
work that *is* about agents — because all three lessons are about **not trusting output
that looks fine**.

- **The first map was built exactly to spec and was wrong** (P-20). Corridors as lines
  coloured by severity, on a map of India. It rendered nearly empty, because 19 of the
  34 worst corridors start and end in the same city — the network's worst corridors are
  marks of zero length. The spec was not wrong about what to show, it was wrong about
  the form, and only rendering it showed that. **Look at the artefact, not the code that
  produced it.**
- **27 of 99 corridors were silently missing** (P-21), and later **172 of 273** (P-24).
  Neither raised anything. A missing dot looks exactly like a corridor that was never
  bad. The fix that mattered was not the alias rows — it was making the page report its
  own coverage, so the next gap announces itself.
- **A generated document kept its old conclusions after its data changed** (P-22, on
  Lahari's side but the same failure mode). Numbers interpolated, characterisations
  hard-coded, so the prose confidently contradicted the table beneath it.

**Why this is agent work.** All three are the same shape as an LLM failure: fluent,
plausible, structurally fine, and wrong — and none of them throw. An agent that reads a
document and returns well-formed JSON with the wrong invoice number fails exactly like
a map that draws 101 of 273 dots. Which is the argument for Week 4's evaluation harness
being built before the prompt iteration rather than after, and for Lahari scoring the
agents I build rather than me scoring them.

**What I would say in an interview:** I would talk about the coverage report. Building
the thing is the easy half; building the thing that tells you when it has quietly
stopped working is the half that matters, and I have three separate instances of it
from one week.

---

## Week 3 — document generation, seeded errors

**Built:** the BOL + GST-invoice generator (`src/agents/doc_corpus/`), its noise
augmentation, and a 120-consignment labelled corpus — full writeup in
`docs/W3_krishna_doc_corpus.md`.

**The skill underneath the task.** "Generate synthetic documents" sounds like a
templating exercise. The part worth remembering is what W2's research already
flagged and this week made concrete: a BOL and its invoice are not two independent
documents, they are one consignment's two views of itself, and an evaluation set that
generates them independently can never test whether an auditor agent catches the two
disagreeing — because they never had the chance to. `ConsignmentRecord` backing both
renderers is the same design decision as D-007's one LLM call site: put the shared
fact in exactly one place, so the two things built on top of it cannot drift apart by
accident, and can only disagree where `seed_errors.py` makes them on purpose.

**The second lesson was about ground truth, not generation.** The extraction prompt
(D-008, `doc_extraction/v1.md`) already says "do not reconcile arithmetic ... report
all three exactly as printed" — Lahari's Week 4 evaluation harness only scores that
rule correctly if the label it compares against is the *printed* number, not the
number the consignment actually cost. Getting that backwards would have made every
seeded `total_mismatch` document score the agent as wrong for being right.

**What I would say in an interview:** building an evaluation corpus is a different
discipline from building the thing it evaluates — I would talk about the moment I
realised the label had to be "what a person reading this page would write down,"
not "what I know the true answer to be," and how that single reframing decided the
whole module's structure (labels read back out of printed fields, never kept
separately from them).

Carried open: the seeded-error taxonomy is my proposal, not yet Lahari's confirmed
sign-off (D-020) — the execution plan puts that decision jointly, and I only had my
own half of the conversation this session.
