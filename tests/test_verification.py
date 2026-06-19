from __future__ import annotations

import re
import unittest

from vrc_profile_proof import (
    ChallengeAlreadyUsedError,
    ChallengeExpiredError,
    GlobalRateLimit,
    TrustRank,
    UserRateLimit,
    VerificationRateLimiter,
    VerificationService,
    bio_contains_token,
    extract_user_id,
)


USER_ID = "usr_00000000-0000-0000-0000-000000000001"


class FakeClock:
    def __init__(self) -> None:
        self.value = 1_700_000_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeClient:
    def __init__(self) -> None:
        self.profile = {
            "id": USER_ID,
            "displayName": "Example User",
            "bio": "",
            "tags": ["system_trust_veteran"],
        }
        self.get_user_calls = 0

    def get_user(self, user_id: str):
        self.get_user_calls += 1
        if user_id != USER_ID:
            raise AssertionError(f"unexpected user id: {user_id}")
        return dict(self.profile)

    def search_users(self, query: str, *, limit: int = 10):
        return [dict(self.profile)] if query == "Example User" else []


def make_service(client: FakeClient, clock: FakeClock, *, ttl: float = 600):
    limiter = VerificationRateLimiter(
        global_policy=GlobalRateLimit(max_operations=100, window_seconds=60),
        user_policy=UserRateLimit(
            min_interval_seconds=0,
            failures_before_cooldown=5,
            cooldown_seconds=300,
        ),
        clock=clock,
    )
    return VerificationService(
        client,  # type: ignore[arg-type]
        challenge_ttl_seconds=ttl,
        secret=b"test-secret" * 4,
        rate_limiter=limiter,
        wall_clock=clock,
    )


class VerificationServiceTests(unittest.TestCase):
    def test_profile_url_user_id_extraction(self) -> None:
        url = f"https://vrchat.com/home/user/{USER_ID}"
        self.assertEqual(extract_user_id(url), USER_ID)

    def test_each_challenge_is_unique(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        first = service.start_verification(USER_ID, context_label="My App")
        second = service.start_verification(USER_ID, context_label="My App")
        self.assertNotEqual(first.challenge_id, second.challenge_id)
        self.assertNotEqual(first.text, second.text)

    def test_fresh_profile_is_fetched_on_verify(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        challenge = service.start_verification(USER_ID)
        self.assertEqual(client.get_user_calls, 1)

        client.profile["bio"] = challenge.text
        result = service.verify(challenge.challenge_id)
        self.assertTrue(result.success)
        self.assertEqual(result.user_id, USER_ID)
        self.assertEqual(result.trust_rank, TrustRank.TRUSTED_USER)
        self.assertEqual(client.get_user_calls, 2)

    def test_successful_challenge_is_one_time(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        challenge = service.start_verification(USER_ID)
        client.profile["bio"] = challenge.text
        self.assertTrue(service.verify(challenge.challenge_id).success)
        with self.assertRaises(ChallengeAlreadyUsedError):
            service.verify(challenge.challenge_id)

    def test_challenge_expires(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock, ttl=10)
        challenge = service.start_verification(USER_ID)
        clock.advance(10)
        with self.assertRaises(ChallengeExpiredError):
            service.verify(challenge.challenge_id)

    def test_nfkc_matches_fullwidth_token(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        challenge = service.start_verification(USER_ID)
        token = re.search(r"vrcverify[a-z0-9]+", challenge.text)
        self.assertIsNotNone(token)
        token_text = token.group(0)  # type: ignore[union-attr]
        fullwidth = "".join(
            chr(ord(character) + 0xFEE0) if "!" <= character <= "~" else character
            for character in token_text
        )
        self.assertTrue(bio_contains_token(f"before {fullwidth} after", token_text))

    def test_five_failures_then_user_cooldown(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        challenge = service.start_verification(USER_ID)
        for _ in range(5):
            self.assertFalse(service.verify(challenge.challenge_id).success)
        from vrc_profile_proof import RateLimitExceeded

        with self.assertRaises(RateLimitExceeded) as raised:
            service.verify(challenge.challenge_id)
        self.assertEqual(raised.exception.scope, "user_cooldown")

    def test_label_dashes_are_folded_to_ascii(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        # em dash, en dash, and horizontal bar should all become ASCII hyphen
        challenge = service.start_verification(
            USER_ID, context_label="My—App–Name―"
        )
        self.assertNotIn("—", challenge.text)
        self.assertNotIn("–", challenge.text)
        self.assertNotIn("―", challenge.text)
        self.assertIn("My-App-Name", challenge.text)
        # VRChat preserves ASCII hyphen, so the round-trip should match
        client.profile["bio"] = challenge.text
        self.assertTrue(service.verify(challenge.challenge_id).success)

    def test_label_whitespace_is_collapsed(self) -> None:
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        # regular spaces, ideographic space, and tab should all collapse to one
        challenge = service.start_verification(
            USER_ID, context_label="My	 App　Name"
        )
        self.assertIn("My App Name", challenge.text)
        client.profile["bio"] = challenge.text
        self.assertTrue(service.verify(challenge.challenge_id).success)

    def test_full_challenge_text_matches_after_vrcchat_transforms(self) -> None:
        """End-to-end: user pastes full challenge text, VRChat fullwidth-converts
        ASCII brackets and letters, but the full text must still match."""
        clock = FakeClock()
        client = FakeClient()
        service = make_service(client, clock)
        challenge = service.start_verification(USER_ID, context_label="My App")
        # Simulate VRChat converting ASCII alphanumerics to fullwidth
        bio_text = challenge.text
        fullwidth_bio = "".join(
            chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in bio_text
        )
        client.profile["bio"] = fullwidth_bio
        self.assertTrue(service.verify(challenge.challenge_id).success)


if __name__ == "__main__":
    unittest.main()
