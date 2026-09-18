# analytics_assistant prompts

Phrases an answer the retrieval layer has already grounded (`src/agents/analytics_assistant.py`,
W7 D3-D4). The model never chooses what to answer from: it is handed either a ranked table
or the retrieved passages, and its job is the sentence.

| version | landed | what it asks for | measured |
|---|---|---|---|
| `v1` | W7 D3 | answer only from the context; cite the source; refuse in one fixed sentence when the context does not cover the question | model-phrased run of the fixed 30 questions |

**The refusal sentence is load-bearing.** It is the second of two refusal layers: the
first is a distance gate that refuses before any model call, and it has 100% precision but
only 50% recall, because questions close to the project's topic retrieve documents as near
as real ones do (P-56). Everything the gate lets through, this prompt has to refuse on its
own when the context does not answer it.

The prompt's sentence is `I don't have that in the project data.` followed by what would
be needed; the code's own refusal is that sentence alone. Judging counts an answer as a
correct refusal when it begins with it.
