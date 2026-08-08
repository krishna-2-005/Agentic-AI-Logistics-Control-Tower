# exception_triage prompts

Empty until **Week 6** (Krishna). `v1.md` lands with the Tracking & Exception Agent:
flagged prediction -> investigate (corridor audit history + TMS lookup) -> severity ->
draft customer notification -> log exception ticket.

This is the only prompt in the project that drafts customer-facing text, so it is the
only one that runs above temperature 0.
