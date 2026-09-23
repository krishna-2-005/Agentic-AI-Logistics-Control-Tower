/**
 * The shared surface of the site.
 *
 * Every page is built from these, which is what §10's "Consistent" criterion
 * actually means in practice: one card, one badge, one table, one page skeleton.
 * A visitor who learns one page has learned them all.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { repoFileUrl } from "@/lib/repo";

// ── page skeleton ────────────────────────────────────────────────────────────

export function PageHeader({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow?: string;
  title: string;
  /** One sentence a non-engineer can repeat. Every page has one. */
  lede: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-8 animate-fade-up">
      {eyebrow && (
        <p className="mb-2 font-mono text-xs uppercase tracking-[0.18em] text-[var(--ink-faint)]">
          {eyebrow}
        </p>
      )}
      <h1 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl">
        {title}
      </h1>
      <p className="mt-3 max-w-2xl text-pretty text-base leading-relaxed text-[var(--ink-muted)]">
        {lede}
      </p>
      {children && <div className="mt-5">{children}</div>}
    </header>
  );
}

export function Section({
  title,
  description,
  children,
  className,
  actions,
}: {
  title?: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={cx("mb-12", className)}>
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            {title && (
              <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
            )}
            {description && (
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-[var(--ink-muted)]">
                {description}
              </p>
            )}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Card({
  children,
  className,
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={cx(
        "rounded-xl border border-[var(--line)] bg-[var(--surface-raised)]",
        padded && "p-5",
        className
      )}
    >
      {children}
    </div>
  );
}

// ── the evidence link, used on every number ──────────────────────────────────

/**
 * Progressive disclosure, the third design rule: the number, then a one-line
 * story, then the file it came from. Nothing on this site is asserted without
 * a link to the artefact that produced it.
 */
export function Evidence({
  file,
  label = "Evidence",
  className,
}: {
  file: string;
  label?: string;
  className?: string;
}) {
  return (
    <a
      href={repoFileUrl(file)}
      target="_blank"
      rel="noreferrer"
      title={file}
      className={cx(
        "inline-flex items-center gap-1 font-mono text-[11px] text-[var(--ink-faint)]",
        "transition-colors hover:text-[var(--accent)]",
        className
      )}
    >
      <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path
          d="M9 2h5v5M14 2 7 9M12 9.5V13a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3.5"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {label}
    </a>
  );
}

// ── KPI ──────────────────────────────────────────────────────────────────────

export function Kpi({
  value,
  label,
  sub,
  file,
  accent,
  className,
}: {
  value: ReactNode;
  label: string;
  sub?: ReactNode;
  file?: string;
  accent?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "rounded-xl border border-[var(--line)] bg-[var(--surface-raised)] p-4",
        "transition-colors hover:border-[var(--ink-faint)]",
        className
      )}
    >
      <div
        className={cx(
          "tabular text-2xl font-semibold leading-none tracking-tight sm:text-[1.75rem]",
          accent && "text-[var(--accent)]"
        )}
      >
        {value}
      </div>
      <div className="mt-2 text-sm font-medium">{label}</div>
      {sub && (
        <div className="mt-1 text-xs leading-relaxed text-[var(--ink-muted)]">
          {sub}
        </div>
      )}
      {file && <div className="mt-2">{<Evidence file={file} />}</div>}
    </div>
  );
}

export function KpiRow({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>
  );
}

// ── badges ───────────────────────────────────────────────────────────────────

/**
 * Severity always carries a word and a shape, never colour alone (W-11).
 * A colourblind reader and a projector both need the label to survive.
 */
export function SeverityBadge({
  color,
  label,
  direction,
  className,
}: {
  color: string;
  label: string;
  direction?: string;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
        "border",
        className
      )}
      style={{
        color,
        borderColor: `${color}55`,
        background: `${color}14`,
      }}
    >
      <span
        aria-hidden
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: color }}
      />
      {label}
      {direction === "better" && (
        <span className="text-[var(--ink-faint)]">· faster</span>
      )}
    </span>
  );
}

export function Pill({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "warn" | "good";
  className?: string;
}) {
  const tones = {
    neutral:
      "border-[var(--line)] bg-[var(--surface-sunken)] text-[var(--ink-muted)]",
    accent:
      "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent)]",
    warn: "border-amber-500/40 bg-amber-500/10 text-amber-400",
    good: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  } as const;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        tones[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

// ── honest empty / offline states ────────────────────────────────────────────

/**
 * Used wherever the live API is unavailable. It says which it is -- recorded
 * evidence or a sleeping container -- because a page that silently shows old
 * data while implying it is live is the kind of thing this project's decision
 * log exists to prevent.
 */
export function Notice({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "warn" | "replay";
  title: string;
  children?: ReactNode;
  className?: string;
}) {
  const tones = {
    info: "border-[var(--accent)]/30 bg-[var(--accent-soft)]",
    warn: "border-amber-500/30 bg-amber-500/[0.07]",
    replay: "border-[var(--line)] bg-[var(--surface-sunken)]",
  } as const;
  return (
    <div
      className={cx(
        "rounded-lg border px-4 py-3 text-sm",
        tones[tone],
        className
      )}
    >
      <p className="font-medium">{title}</p>
      {children && (
        <div className="mt-1 leading-relaxed text-[var(--ink-muted)]">
          {children}
        </div>
      )}
    </div>
  );
}

// ── table primitives ─────────────────────────────────────────────────────────

export function TableShell({
  children,
  className,
  maxHeight,
}: {
  children: ReactNode;
  className?: string;
  maxHeight?: string;
}) {
  return (
    <div
      className={cx(
        "overflow-auto rounded-xl border border-[var(--line)] bg-[var(--surface-raised)]",
        className
      )}
      style={maxHeight ? { maxHeight } : undefined}
    >
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({
  children,
  align = "left",
  className,
  ...rest
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
} & React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      {...rest}
      className={cx(
        "sticky top-0 z-10 whitespace-nowrap border-b border-[var(--line)]",
        "bg-[var(--surface-sunken)] px-3 py-2.5 text-xs font-semibold",
        "uppercase tracking-wider text-[var(--ink-muted)]",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  mono,
  className,
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
  mono?: boolean;
  className?: string;
}) {
  return (
    <td
      className={cx(
        "border-b border-[var(--line)]/60 px-3 py-2",
        align === "right" && "text-right",
        align === "center" && "text-center",
        mono && "tabular font-mono text-[13px]",
        className
      )}
    >
      {children}
    </td>
  );
}

// ── misc ─────────────────────────────────────────────────────────────────────

export function ArrowLink({
  href,
  children,
  external,
}: {
  href: string;
  children: ReactNode;
  external?: boolean;
}) {
  const content = (
    <>
      {children}
      <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
        →
      </span>
    </>
  );
  const cls =
    "group inline-flex items-center gap-1.5 text-sm font-medium text-[var(--accent)] hover:underline";
  return external ? (
    <a href={href} target="_blank" rel="noreferrer" className={cls}>
      {content}
    </a>
  ) : (
    <Link href={href} className={cls}>
      {content}
    </Link>
  );
}

/** A definition a visitor can hover. Every domain term gets one on first use. */
export function Term({
  children,
  definition,
}: {
  children: ReactNode;
  definition: string;
}) {
  return (
    <abbr
      title={definition}
      className="cursor-help border-b border-dotted border-[var(--ink-faint)] no-underline"
    >
      {children}
    </abbr>
  );
}
