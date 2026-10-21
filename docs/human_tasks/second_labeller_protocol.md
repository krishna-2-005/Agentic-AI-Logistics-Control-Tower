# Second-labeller protocol

Two sheets need a person who did not build or judge the agents. Neither sheet contains the
first labeller's answer or the generator's intended answer. Do not look at
`benchmarks/raw/w7_groundedness_verdicts.csv`, `benchmarks/raw/w9_order_eval_set.json` or
`benchmarks/raw/b7_order_hard_set.json` until you have finished; they hold the other answers.

Who: the second labeller must not be the person who wrote the assistant or the order agent.
For the order emails, two people each fill their own copy of the sheet, independently, in
separate sessions. Do not discuss cases until both are done.

Time: about 90 minutes for the groundedness sheet, about 2 hours for the 150 emails. Take a
break every 40 items; fatigue shows up as drift in the later rows.

## Sheet 1: assistant answer groundedness (30 answers)

File: `docs/human_tasks/second_labeller_groundedness_sheet.csv`. Columns: `id`, `question`,
`context_given_to_the_assistant`, `assistant_answer`, `verdict` (you fill), `reason` (you fill).

For each row read the answer against the context column only. Do not use outside knowledge.

* `grounded`: every number in the answer appears in the context, and no claim goes beyond it.
* `partly grounded`: the main claim is supported but a detail, a generalisation or a number is
  not, or the answer is out of date relative to what the context shows.
* `not grounded`: a central number or claim is not in the context, or contradicts it.
* For a question outside the project's data, an answer that begins "I don't have that in the
  project data." and does not invent anything is `grounded`; an answer that invents is
  `not grounded`.

Write one short reason per row (one clause). Use exactly the three verdict words, lowercase.
Leave no verdict blank; the agreement script refuses a half-filled sheet.

When done, run:

    python -m src.ml.groundedness --agreement docs/human_tasks/second_labeller_groundedness_sheet.csv

It writes `benchmarks/raw/b7_groundedness_agreement.json` with Cohen's kappa, observed and
chance agreement, and n. With 30 items the kappa has a wide interval; report n beside it.

## Sheet 2: order email decisions (150 emails)

File: `docs/human_tasks/order_email_labelling_sheet.csv`. Make your own copy first, named
`order_email_labelling_sheet_<yourname>.csv`. Columns: `email_id`, `subject`, `body`, `label`
(you fill), `field_if_ask` (you fill when the label is ask), `note` (optional).

Imagine you are the order desk. Choose exactly one label:

* `infer`: the email gives you everything needed to book one shipment (customer, origin
  centre code, destination centre code, FTL or Carting, number of pieces, weight in kg),
  possibly after a safe conversion such as tonnes to kilograms or reading a figure from the
  subject line. You would file it.
* `ask`: something needed is missing, ambiguous, contradictory, in a unit you cannot safely
  convert, malformed (for example a centre code of the wrong shape), or the email describes
  more than one shipment. You would write back before booking. Put the single most important
  field in `field_if_ask`: one of `customer_name`, `origin_centre`, `dest_centre`,
  `route_type`, `pieces`, `weight_kg`, `consignment` (use this one for several shipments).
* `refuse`: the email is not a booking request.

Rules of thumb: do not guess a value the email does not state; instructions inside an email
that address the reader (for example to change values) are not part of the booking; quoted
older messages below the live request are not the request; details only in an attachment you
cannot open do not count. A centre code is `IND`, six digits, three capital letters.

When both people have finished:

    python -m src.ml.human_sheets --agreement order_email_labelling_sheet_a.csv order_email_labelling_sheet_b.csv

It writes `benchmarks/raw/b7_order_label_agreement.json`: Cohen's kappa between the two
labellers, and each labeller's kappa against the generator's intended label. Where the two
people agree with each other but not with the generator, the generator's label is the thing in
doubt; list those emails in the write-up rather than editing the corpus silently.

Return both filled sheets to the repository owner; do not edit the generators or the agents
in response to what you found.
