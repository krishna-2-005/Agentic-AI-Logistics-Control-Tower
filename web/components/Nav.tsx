"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { cx } from "@/lib/format";

/**
 * Top navigation in four sections.
 *
 * The Streamlit sidebar listed nine page names and a build-status checklist of
 * ticks -- a panel for the team, not navigation for a visitor. Grouping the
 * routes under Network / Predict / Agents / Evidence says what the system does
 * before the visitor has clicked anything.
 */
const SECTIONS: { label: string; items: { href: string; label: string }[] }[] = [
  {
    label: "Network",
    items: [
      { href: "/network/", label: "Map" },
      { href: "/corridors/", label: "Corridors" },
      { href: "/hubs/", label: "Hubs" },
    ],
  },
  {
    label: "Predict",
    items: [
      { href: "/predict/", label: "Delay predictor" },
      { href: "/alerts/", label: "Live alerts" },
    ],
  },
  {
    label: "Agents",
    items: [
      { href: "/agents/", label: "Workforce" },
      { href: "/assistant/", label: "Assistant" },
      { href: "/prompts/", label: "Prompts" },
    ],
  },
  {
    label: "Results",
    items: [
      { href: "/evidence/", label: "The numbers" },
      { href: "/about/", label: "About" },
    ],
  },
];

function Logo() {
  return (
    <Link href="/" className="flex shrink-0 items-center gap-2.5">
      <svg width="26" height="26" viewBox="0 0 28 28" fill="none" aria-hidden>
        <circle cx="14" cy="14" r="13" stroke="var(--accent)" strokeWidth="1.5" opacity="0.35" />
        <path
          d="M4 18C9 18 9 9 14 9s5 9 10 9"
          stroke="var(--accent)"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle cx="4" cy="18" r="2.5" fill="var(--accent)" />
        <circle cx="24" cy="18" r="2.5" fill="var(--accent)" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight">
        Control Tower
      </span>
    </Link>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const saved = localStorage.getItem("ct-theme");
    const initial = saved === "light" ? "light" : "dark";
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("ct-theme", next);
    } catch {
      /* private mode: the toggle still works for this visit */
    }
  }

  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      className="rounded-lg border border-[var(--line)] p-2 text-[var(--ink-muted)] transition-colors hover:border-[var(--ink-faint)] hover:text-[var(--ink)]"
    >
      {theme === "dark" ? (
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
          <circle cx="8" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.4" />
          <path
            d="M8 1v1.6M8 13.4V15M15 8h-1.6M2.6 8H1M12.9 3.1l-1.1 1.1M4.2 11.8l-1.1 1.1M12.9 12.9l-1.1-1.1M4.2 4.2 3.1 3.1"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path
            d="M13.5 9.8A6 6 0 0 1 6.2 2.5a6 6 0 1 0 7.3 7.3Z"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}

export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const isActive = (href: string) => pathname === href;

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--line)] bg-[var(--surface)]/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-content items-center gap-6 px-4 sm:px-6">
        <Logo />

        <nav className="hidden flex-1 items-center gap-1 lg:flex">
          {SECTIONS.map((section) => (
            <div key={section.label} className="group relative">
              <button
                className={cx(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  section.items.some((i) => isActive(i.href))
                    ? "text-[var(--ink)]"
                    : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
                )}
              >
                {section.label}
              </button>
              <div className="invisible absolute left-0 top-full w-52 pt-1.5 opacity-0 transition-all group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
                <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface-raised)] p-1 shadow-xl shadow-black/30">
                  {section.items.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cx(
                        "block rounded-lg px-3 py-2 text-sm transition-colors",
                        isActive(item.href)
                          ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                          : "text-[var(--ink-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--ink)]"
                      )}
                    >
                      {item.label}
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <button
            onClick={() => setOpen((v) => !v)}
            aria-label="Menu"
            aria-expanded={open}
            className="rounded-lg border border-[var(--line)] p-2 text-[var(--ink-muted)] lg:hidden"
          >
            <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden>
              <path
                d={open ? "M3 3l10 10M13 3L3 13" : "M2 4h12M2 8h12M2 12h12"}
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>

      {open && (
        <div className="border-t border-[var(--line)] bg-[var(--surface-raised)] px-4 py-3 lg:hidden">
          {SECTIONS.map((section) => (
            <div key={section.label} className="mb-3 last:mb-0">
              <p className="mb-1 font-mono text-[11px] uppercase tracking-wider text-[var(--ink-faint)]">
                {section.label}
              </p>
              <div className="grid grid-cols-2 gap-1">
                {section.items.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cx(
                      "rounded-lg px-3 py-2 text-sm",
                      isActive(item.href)
                        ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                        : "text-[var(--ink-muted)]"
                    )}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </header>
  );
}
