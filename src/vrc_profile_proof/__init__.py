"""Temporary proof of control for VRChat profiles."""

from .client import VRChatClient
from .errors import (
    AmbiguousUserError,
    ChallengeAlreadyUsedError,
    ChallengeError,
    ChallengeExpiredError,
    ChallengeNotFoundError,
    RateLimitExceeded,
    UserResolutionError,
    VRCProfileProofError,
    VRChatAPIError,
)
from .models import TrustRank, VerificationChallenge, VerificationResult
from .rate_limit import GlobalRateLimit, UserRateLimit, VerificationRateLimiter
from .verification import (
    DEFAULT_CONTEXT_LABEL,
    VerificationService,
    bio_contains_token,
    extract_trust_rank,
    extract_user_id,
    resolve_user_profile,
)

__all__ = [
    "AmbiguousUserError",
    "ChallengeAlreadyUsedError",
    "ChallengeError",
    "ChallengeExpiredError",
    "ChallengeNotFoundError",
    "DEFAULT_CONTEXT_LABEL",
    "GlobalRateLimit",
    "RateLimitExceeded",
    "TrustRank",
    "UserRateLimit",
    "UserResolutionError",
    "VRCProfileProofError",
    "VRChatAPIError",
    "VRChatClient",
    "VerificationChallenge",
    "VerificationRateLimiter",
    "VerificationResult",
    "VerificationService",
    "bio_contains_token",
    "extract_trust_rank",
    "extract_user_id",
    "resolve_user_profile",
]
