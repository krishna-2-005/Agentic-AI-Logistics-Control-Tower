import type { Metadata } from "next";

import { CopyButton } from "@/components/CopyButton";
import { ArrowLink, Card, Notice, PageHeader, Pill, Section } from "@/components/ui";
import { getFigures, getPaper } from "@/lib/data";
import { REPO_URL, repoFileUrl } from "@/lib/repo";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta(
  "Paper",
  "The abstract, figures, citation and reproduction steps for the write-up behind this site."
);

export default function PaperPage() {
  const paper = getPaper().data;
  const figures = getFigures().data.figures;

  return (
    <>
      <PageHeader
        eyebrow="Results"
        title="The paper"
        lede={<>{paper.title}</>}
      />

      <Section title="Abstract">
        <Card>
          {paper.abstract_is_placeholder && (
            <Pill tone="warn" className="mb-3">
              placeholder · the paper is not final
            </Pill>
          )}
          <p className="max-w-3xl whitespace-pre-line text-sm leading-relaxed text-[var(--ink-muted)]">
            {paper.abstract}
          </p>
          <div className="mt-4 border-t border-[var(--line)] pt-3 text-sm">
            {paper.preprint_url ? (
              <ArrowLink href={paper.preprint_url} external>
                Read the preprint
              </ArrowLink>
            ) : (
              <span className="text-[var(--ink-muted)]">
                Preprint: not posted yet. The link appears here once it is.
              </span>
            )}
          </div>
        </Card>
      </Section>

      <Section
        title="Figures"
        description="Each figure is computed from a file under benchmarks/raw by a module in the repository. The PDF is the vector version used in the paper."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {figures.map((f) => (
            <Card key={f.id} padded={false} className="overflow-hidden">
              <div className="bg-white p-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={f.file}
                  alt={`${f.title}. ${f.caption}`}
                  loading="lazy"
                  className="w-full"
                />
              </div>
              <div className="border-t border-[var(--line)] px-4 py-3">
                <p className="text-xs font-semibold">{f.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-[var(--ink-muted)]">
                  {f.caption}
                </p>
                {f.pdf && (
                  <a
                    href={f.pdf}
                    className="mt-2 inline-block text-xs font-medium text-[var(--accent)] hover:underline"
                  >
                    Vector PDF
                  </a>
                )}
              </div>
            </Card>
          ))}
        </div>
      </Section>

      <Section title="Cite this work">
        <Card>
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="text-xs text-[var(--ink-muted)]">
              Generated from CITATION.cff in the repository.
            </p>
            <CopyButton text={paper.bibtex} label="Copy BibTeX" />
          </div>
          <pre className="overflow-x-auto rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] p-3 font-mono text-xs leading-relaxed">
            <code>{paper.bibtex}</code>
          </pre>
        </Card>
      </Section>

      <Section title="How to reproduce">
        <Card>
          <p className="text-sm leading-relaxed text-[var(--ink-muted)]">
            With the raw Delhivery CSV in place, one command rebuilds the data,
            the models, every result file and the figures:
          </p>
          <pre className="mt-3 overflow-x-auto rounded-lg border border-[var(--line)] bg-[var(--surface-sunken)] p-3 font-mono text-xs">
            <code>{paper.reproduce.command}</code>
          </pre>
          <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
            <li>
              <ArrowLink href={REPO_URL} external>
                Code
              </ArrowLink>
            </li>
            {paper.reproduce.links.map((l) => (
              <li key={l.path}>
                <ArrowLink href={repoFileUrl(l.path)} external>
                  {l.label}
                </ArrowLink>
              </li>
            ))}
          </ul>
        </Card>
        <Notice tone="replay" title="The dataset is not redistributed here" className="mt-4">
          The raw records belong to Delhivery and are used under their original
          licence. The data card says where to download them.
        </Notice>
      </Section>
    </>
  );
}
