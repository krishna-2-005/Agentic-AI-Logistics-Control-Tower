"""What stops one visitor using up a free container meant for everyone (WP-04, D-072).

Three controls, each answering a different way a public endpoint gets exhausted:

* `RateLimiter` -- requests per client per minute. Stops one visitor, or one script,
  from monopolising a route.
* `ConcurrencyGate` -- predictions in flight at once, across everyone. A prediction holds
  a Spark job; two in parallel is what two free vCPUs can run without every answer
  getting slower. A third is told "busy" at once rather than queued behind the others.
* `DailyQuota` -- language-model calls per day, across everyone. The free tier's daily
  cap is the binding constraint on this project (`docs/cost.md`), so the server spends
  only a stated fraction of it (D-063).

Written here rather than taken from `slowapi`: these are about forty lines, they need
the client address as the proxy reports it (not the proxy's own), and a dependency for
them would be one more thing in a container that has to start inside a free tier's
limits. All three are in-process, which is right for one container and says so.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class RateLimiter:
    """At most `limit` requests per `window_s` seconds per key, as a sliding window."""

    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float:
        """0 if the request may proceed (and counts it); otherwise seconds until it may."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, self.window_s - (now - hits[0]))
            hits.append(now)
            # Keys with no recent hits are dropped, so the table cannot grow without bound
            # under a stream of one-off addresses.
            if len(self._hits) > 10_000:
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return 0.0


class ConcurrencyGate:
    """At most `size` holders at once; a caller that cannot get in is refused, not queued."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._slots = threading.BoundedSemaphore(size)

    def try_enter(self) -> bool:
        return self._slots.acquire(blocking=False)

    def leave(self) -> None:
        self._slots.release()


class DailyQuota:
    """`limit` uses per calendar day in IST, shared by every caller."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._day = ""
        self._used = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        today = datetime.now(IST).date().isoformat()
        if today != self._day:
            self._day, self._used = today, 0

    def take(self) -> bool:
        with self._lock:
            self._roll()
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    def give_back(self) -> None:
        """Return a use that did not happen (the call failed before reaching the model)."""
        with self._lock:
            self._used = max(0, self._used - 1)

    def remaining(self) -> int:
        with self._lock:
            self._roll()
            return self.limit - self._used
