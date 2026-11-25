"""Rate limit and daily cap, with no web framework and no clock of their own, so they can be tested.

Both live in the memory of one process. That is enough for one instance. Several instances would each
keep their own count, so a shared store would be needed before running more than one.
"""
import threading
import time
from datetime import datetime, timezone


class TokenBucket:
    """Each client may make `burst` requests at once, refilled at `per_minute` a minute."""

    def __init__(self, per_minute: float, burst: int, clock=time.monotonic):
        self.rate = per_minute / 60.0
        self.burst = float(burst)
        self.clock = clock
        self.state: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, name: str) -> tuple[bool, int]:
        """Returns (allowed, seconds to wait before trying again)."""
        with self.lock:
            now = self.clock()
            tokens, last = self.state.get(name, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self.state[name] = (tokens - 1.0, now)
                return True, 0
            self.state[name] = (tokens, now)
            wait = int((1.0 - tokens) / self.rate) + 1 if self.rate > 0 else 3600
            return False, wait


class DailyCap:
    """At most `limit` accepted requests per UTC day, for all clients together.

    Each request makes at most 4 model calls (one classifier call and up to three answer attempts), so
    the cap bounds a day's spend: limit x 4 calls. It counts requests, not tokens.
    """

    def __init__(self, limit: int, today=lambda: datetime.now(timezone.utc).date()):
        self.limit = limit
        self.today = today
        self.day = None
        self.count = 0
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            day = self.today()
            if day != self.day:
                self.day, self.count = day, 0
            if self.count >= self.limit:
                return False
            self.count += 1
            return True
