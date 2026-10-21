"use client";

import { useState } from "react";

/** Copies a block of text and says so, for the BibTeX entry. */
export function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    } catch {
      /* clipboard blocked: the text is on screen to select by hand */
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-xs font-medium transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
    >
      <span role="status">{done ? "Copied" : label}</span>
    </button>
  );
}
