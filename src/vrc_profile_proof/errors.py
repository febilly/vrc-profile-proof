"""Exceptions raised by vrc-profile-proof."""

from __future__ import annotations


class VRCProfileProofError(Exception):
    """Base exception for the package."""


class VRChatAPIError(VRCProfileProofError):
    def __init__(
        self,
        status: int,
        message: str,
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self.message = message
        self.headers = headers or {}
        super().__init__(f"VRChat API error {status}: {message}")


class UserResolutionError(VRCProfileProofError):
    """Raised when user input cannot be resolved to one VRChat profile."""


class AmbiguousUserError(UserResolutionError):
    def __init__(self, query: str, candidates: list[dict[str, object]]):
        self.query = query
        self.candidates = candidates
        super().__init__(f"Multiple VRChat users matched {query!r}.")


class ChallengeError(VRCProfileProofError):
    """Base exception for challenge lifecycle failures."""


class ChallengeNotFoundError(ChallengeError):
    pass


class ChallengeExpiredError(ChallengeError):
    pass


class ChallengeAlreadyUsedError(ChallengeError):
    pass


class RateLimitExceeded(VRCProfileProofError):
    def __init__(self, scope: str, retry_after: float):
        self.scope = scope
        self.retry_after = max(0.0, retry_after)
        super().__init__(
            f"{scope} rate limit exceeded; retry after {self.retry_after:.1f} seconds"
        )
