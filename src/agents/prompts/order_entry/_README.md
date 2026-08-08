# order_entry prompts

Empty until **Week 5** (Krishna). `v1.md` lands with the Order Entry Agent:
order email / PDF -> structured order -> validation -> `POST /orders` on the mock TMS.

The hard part this prompt has to get right is the **clarification path** — an
ambiguous order must produce a question, not a confident guess. That behaviour is
scored separately by Lahari on a 50-case set (execution plan, W5 D5).
