# W8 · Krishna — venue, demo, public dashboard, figures, and the assistant's finished run

```bash
python scripts/deploy_hf_space.py --stage dist/hf_space   # the exact public bundle, tested clean
python -m src.report.figures                               # the nine paper figures, png + pdf
python -m src.agents.assistant_eval --retry-fallbacks      # re-ask any answer a provider error cut short
```

## 1. The venue (D-052)

ICCCI 2027, submission **20 February 2027**, double-blind, 4-10 pages — the only one of the
three candidate venues with a published 2027 deadline on 18 September. The arXiv preprint
goes up when the draft is done, not when the venue answers, and the deadline is re-checked in
January because conference sites move dates without notice.

## 2. The demo script

`docs/demo_script.md`: ten minutes, six beats — the premise, the audit and map, a live replay
into alerts, one email through the whole lifecycle, document extraction, and two questions to
the assistant — with what to say when each one fails. Checking every command against the
repository caught three things before anyone rehearsed:

- the premise number was **93.6%**, the stale 1.25× delay label, not the **98.3%** of legs
  that actually run over plan;
- the extraction demo, run as written, would have overwritten the cited 40-row evaluation
  with a 4-row one — P-51 for the second time; it now writes to `--tag _demo`;
- the assistant beat narrated **Aluva** as the hub with the longest dwell. It is Hubli (§5).

The alert-precision line now says **59%**, and tells the presenter to raise the 72% correction
before anyone else does (D-054).

## 3. The public dashboard (G-08)

`requirements-cloud.txt` is the set the dashboard actually imports; `deploy/hf_space/` wraps
it as a Docker-SDK Hugging Face Space; `scripts/deploy_hf_space.py` uploads exactly the files
the dashboard reads (184 files, 14.5 MB), never `data/`. The assistant's ask box now disables
itself when the vector index is absent instead of accepting a question it will fail.

**Verified the way that finds things.** The first check blocked the heavy packages inside
the full development environment and rendered all nine pages: zero exceptions. The second
built a brand-new virtualenv from `requirements-cloud.txt` alone and rendered the staged
bundle — and **Hub friction failed**: pandas imports scipy inside `corr(method="spearman")`,
no page names it, and it had been installed all along in development. It is in the cloud
requirements now; all nine pages render.

**Not published.** The connected Hugging Face account gives this environment read access
only, and no write token was created on the owner's behalf. Publishing is
`huggingface-cli login` and one command.

## 4. The figures

Nine figures in `docs/figures/`, each read from a `benchmarks/raw/` file, on a palette checked
for colour-vision separation rather than chosen by eye, with every bar labelled because two
colours fall under 3:1 contrast. Looking at the output found four defects the code did not:
a title colliding with subplot titles, a leader line crossing the bars it labelled, a
baseline label on top of the tallest bar, and **a figure that contradicted its own title** —
the threshold figure claimed "quality barely moves" while plotting the stream's own flag,
whose MCC climbs 0.315 → 0.477. The claim belongs to the logistic classifier; both are drawn
now. Figure 9 was redrawn as-of after D-054, with the first (leaked) values kept as hollow
markers.

The vector PDFs were not in the repository until tonight: a blanket `*.pdf` ignore rule, meant
for the document corpus, had been dropping them while every commit message said "png and
vector pdf".

## 5. The assistant's finished run

All 30 questions answered by the model. Route 93.3%, source 86.7%, and **all six
out-of-scope questions refused** — four by the distance gate, the two that got past it by the
model in its own answer. Lahari's groundedness judging: **17 of 18 model-written answers**.

Two bugs came out of it:

- **P-60.** Six answers were provider errors recorded as extractive "answers" and headed for
  grading as the model's. The runner looked for the quota error in a trace the assistant
  writes *after* catching the exception, so that branch never fired. Any fallback in model
  mode is now skipped and retried; `--retry-fallbacks` re-asks the six.
- **P-61.** "Which hub has the longest dwell time?" was routed to the friction ranking, which
  puts Aluva first by dwell *share*. The model, handed both hubs' numbers, answered **Hubli —
  373 minutes against 350**, longest across all 121 hubs — and was right. The router, its
  test, the question set's expected answer and the demo script were all wrong the same way.
  Dwell-time questions now sort by minutes.

## Owed

| item | waits on |
|---|---|
| Publishing the Space | a Hugging Face write token |
| G-07, one real alert | an SMTP app password or Telegram token in `.env` |
| Two demo rehearsals | people |
| Re-asking the six fallback questions | tomorrow's Gemini quota |

Problems logged this week: P-60, P-61.
