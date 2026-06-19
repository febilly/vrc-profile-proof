"""In-memory global and per-user verification rate limits."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from .errors import RateLimitExceeded


@dataclass(frozen=True)
class GlobalRateLimit:
    max_operations: int = 60
    window_seconds: float = 60.0


@dataclass(frozen=True)
class UserRateLimit:
    min_interval_seconds: float = 2.0
    failures_before_cooldown: int = 5
    failure_reset_seconds: float = 300.0
    cooldown_seconds: float = 300.0


@dataclass
class _UserState:
    consecutive_failures: int = 0
    last_attempt_at: float | None = None
    last_failure_at: float | None = None
    cooldown_until: float = 0.0


class VerificationRateLimiter:
    def __init__(
        self,
        *,
        global_policy: GlobalRateLimit | None = None,
        user_policy: UserRateLimit | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.global_policy = global_policy or GlobalRateLimit()
        self.user_policy = user_policy or UserRateLimit()
        self._clock = clock
        self._global_operations: deque[float] = deque()
        self._users: dict[str, _UserState] = {}
        self._lock = threading.RLock()

    def check_global(self) -> None:
        with self._lock:
            now = self._clock()
            window_start = now - self.global_policy.window_seconds
            while self._global_operations and self._global_operations[0] <= window_start:
                self._global_operations.popleft()
            if len(self._global_operations) >= self.global_policy.max_operations:
                retry_after = (
                    self._global_operations[0]
                    + self.global_policy.window_seconds
                    - now
                )
                raise RateLimitExceeded("global", retry_after)
            self._global_operations.append(now)

    def check_user(self, user_id: str) -> None:
        with self._lock:
            now = self._clock()
            state = self._users.setdefault(user_id, _UserState())
            if state.cooldown_until > now:
                raise RateLimitExceeded("user_cooldown", state.cooldown_until - now)
            if (
                state.last_failure_at is not None
                and now - state.last_failure_at >= self.user_policy.failure_reset_seconds
            ):
                state.consecutive_failures = 0
                state.last_failure_at = None
            if state.last_attempt_at is not None:
                elapsed = now - state.last_attempt_at
                if elapsed < self.user_policy.min_interval_seconds:
                    raise RateLimitExceeded(
                        "user_interval",
                        self.user_policy.min_interval_seconds - elapsed,
                    )
            state.last_attempt_at = now

    def record_success(self, user_id: str) -> None:
        with self._lock:
            state = self._users.setdefault(user_id, _UserState())
            state.consecutive_failures = 0
            state.last_failure_at = None
            state.cooldown_until = 0.0

    def record_failure(self, user_id: str) -> None:
        with self._lock:
            now = self._clock()
            state = self._users.setdefault(user_id, _UserState())
            state.consecutive_failures += 1
            state.last_failure_at = now
            if state.consecutive_failures >= self.user_policy.failures_before_cooldown:
                state.cooldown_until = now + self.user_policy.cooldown_seconds

    def reset_user(self, user_id: str) -> None:
        with self._lock:
            self._users.pop(user_id, None)
