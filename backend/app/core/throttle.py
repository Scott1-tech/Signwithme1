"""Login throttling.

An in-process fixed-window counter. That is enough for a single-instance
deployment, which is what this app is sized for; it is deliberately not a
distributed limiter, and the docstring says so rather than implying protection
it cannot give across replicas.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.config import settings


@dataclass
class _Window:
    count: int
    expires_at: float


class LoginThrottle:
    def __init__(self):
        self._lock = threading.Lock()
        self._windows: dict[str, _Window] = {}

    def _prune(self, now: float) -> None:
        expired = [key for key, window in self._windows.items() if window.expires_at <= now]
        for key in expired:
            del self._windows[key]

    def is_locked(self, key: str) -> int:
        """Return the seconds remaining on a lockout, or 0 when not locked."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            window = self._windows.get(key)
            if window and window.count >= settings.login_max_attempts:
                return max(int(window.expires_at - now), 1)
        return 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            window = self._windows.get(key)
            if window is None:
                self._windows[key] = _Window(count=1, expires_at=now + settings.login_lockout_seconds)
            else:
                window.count += 1

    def reset(self, key: str) -> None:
        with self._lock:
            self._windows.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()


login_throttle = LoginThrottle()
