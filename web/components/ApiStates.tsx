"use client";

import { useEffect, useState } from "react";

import { Notice } from "@/components/ui";
import { WAKING_BODY, WAKING_TITLE } from "@/lib/api";

/**
 * True once `active` has stayed true for `ms`. A reply inside three seconds means the
 * host was awake and needs no message; a slower one means it is booting.
 */
export function useSlow(active: boolean, ms = 3000): boolean {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) {
      setSlow(false);
      return;
    }
    const id = setTimeout(() => setSlow(true), ms);
    return () => clearTimeout(id);
  }, [active, ms]);
  return slow;
}

/** The friendly wait state: what is happening and that nothing is broken. */
export function WakingNotice({ className }: { className?: string }) {
  return (
    <Notice tone="info" title={WAKING_TITLE} className={className}>
      <span role="status">{WAKING_BODY}</span>
    </Notice>
  );
}

export function RetryButton({
  onClick,
  children = "Try again",
}: {
  onClick: () => void;
  children?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm font-medium transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
    >
      {children}
    </button>
  );
}

/** Shown when the host did not answer within the 90 s window. */
export function ApiDownNotice({
  message,
  onRetry,
  className,
}: {
  message?: string | null;
  onRetry: () => void;
  className?: string;
}) {
  return (
    <Notice tone="replay" title="The live service did not answer" className={className}>
      <p>
        {message ??
          "It did not answer within 90 seconds."}{" "}
        The recorded results on the rest of the site need no server.
      </p>
      <div className="mt-3">
        <RetryButton onClick={onRetry} />
      </div>
    </Notice>
  );
}
