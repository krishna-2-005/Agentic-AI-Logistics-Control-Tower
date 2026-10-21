"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Mounts its children only once the placeholder is near the viewport.
 *
 * The map and the charts pull in several hundred kilobytes of JavaScript. Loading
 * them up front blocked the main thread for seconds on a phone, before the visitor
 * had scrolled to them. The placeholder keeps the final height, so nothing shifts
 * when they arrive.
 */
export function Lazy({
  children,
  height,
  rootMargin = "300px",
  label,
}: {
  children: ReactNode;
  height: number | string;
  rootMargin?: string;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || shown) return;
    if (typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true);
          io.disconnect();
        }
      },
      { rootMargin }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [shown, rootMargin]);

  if (shown) return <>{children}</>;
  return (
    <div
      ref={ref}
      style={{ height, width: "100%" }}
      className="animate-pulse rounded-xl border border-[var(--line)] bg-[var(--surface-raised)]"
      role="img"
      aria-label={label ?? "Loading"}
    />
  );
}
