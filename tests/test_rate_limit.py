from __future__ import annotations

import unittest

from vrc_profile_proof import (
    GlobalRateLimit,
    RateLimitExceeded,
    UserRateLimit,
    VerificationRateLimiter,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class VerificationRateLimiterTests(unittest.TestCase):
    def test_global_sliding_window(self) -> None:
        clock = FakeClock()
        limiter = VerificationRateLimiter(
            global_policy=GlobalRateLimit(max_operations=2, window_seconds=10),
            clock=clock,
        )
        limiter.check_global()
        limiter.check_global()
        with self.assertRaises(RateLimitExceeded) as raised:
            limiter.check_global()
        self.assertEqual(raised.exception.scope, "global")
        self.assertEqual(raised.exception.retry_after, 10)

        clock.advance(10)
        limiter.check_global()

    def test_user_interval(self) -> None:
        clock = FakeClock()
        limiter = VerificationRateLimiter(
            user_policy=UserRateLimit(min_interval_seconds=2),
            clock=clock,
        )
        limiter.check_user("usr_test")
        with self.assertRaises(RateLimitExceeded) as raised:
            limiter.check_user("usr_test")
        self.assertEqual(raised.exception.scope, "user_interval")

        clock.advance(2)
        limiter.check_user("usr_test")

    def test_consecutive_failures_trigger_cooldown(self) -> None:
        clock = FakeClock()
        limiter = VerificationRateLimiter(
            user_policy=UserRateLimit(
                min_interval_seconds=0,
                failures_before_cooldown=3,
                failure_reset_seconds=60,
                cooldown_seconds=30,
            ),
            clock=clock,
        )
        for _ in range(3):
            limiter.check_user("usr_test")
            limiter.record_failure("usr_test")

        with self.assertRaises(RateLimitExceeded) as raised:
            limiter.check_user("usr_test")
        self.assertEqual(raised.exception.scope, "user_cooldown")
        self.assertEqual(raised.exception.retry_after, 30)

        clock.advance(30)
        limiter.check_user("usr_test")

    def test_success_resets_failure_streak(self) -> None:
        clock = FakeClock()
        limiter = VerificationRateLimiter(
            user_policy=UserRateLimit(
                min_interval_seconds=0,
                failures_before_cooldown=2,
                cooldown_seconds=30,
            ),
            clock=clock,
        )
        limiter.check_user("usr_test")
        limiter.record_failure("usr_test")
        limiter.record_success("usr_test")
        limiter.check_user("usr_test")
        limiter.record_failure("usr_test")
        limiter.check_user("usr_test")


if __name__ == "__main__":
    unittest.main()
