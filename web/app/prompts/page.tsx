import type { Metadata } from "next";

import { PromptLibrary } from "@/components/PromptLibrary";
import { Notice, PageHeader, Section } from "@/components/ui";
import { getPrompts } from "@/lib/data";

export const metadata: Metadata = {
  title: "Prompt library",
  description:
    "Every prompt version, never overwritten — so a claimed improvement can be re-run.",
};

export default function PromptsPage() {
  const prompts = getPrompts();

  return (
    <>
      <PageHeader
        eyebrow="Agents"
        title="Every prompt, every version"
        lede={
          <>
            A new prompt version is a new file; the old one is never
            overwritten. That is the difference between claiming an accuracy
            went from 0.853 to 0.929 and being able to show it — the prompt that
            scored 0.853 still exists and still runs.
          </>
        }
      />

      <Section>
        <Notice tone="info" title="Why this page exists at all">
          Prompts are the part of an agent most likely to be changed casually
          and least likely to be versioned. Putting them under the same
          discipline as the code is what makes every agent score on this site a
          measurement rather than an anecdote.
        </Notice>
      </Section>

      <PromptLibrary agents={prompts.data} />
    </>
  );
}
