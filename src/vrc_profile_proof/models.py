"""Public data models for profile verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class TrustRank(StrEnum):
    UNKNOWN = "unknown"
    VISITOR = "visitor"
    NEW_USER = "new_user"
    USER = "user"
    KNOWN_USER = "known_user"
    TRUSTED_USER = "trusted_user"
    VETERAN_USER = "veteran_user"
    PROBABLE_NUISANCE = "probable_nuisance"
    NUISANCE = "nuisance"


@dataclass(frozen=True)
class VerificationChallenge:
    challenge_id: str
    user_id: str
    display_name: str
    trust_rank: TrustRank
    text: str
    context_label: str
    expires_at: datetime
    profile: dict[str, Any]


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    user_id: str
    display_name: str
    trust_rank: TrustRank
    profile: dict[str, Any]
    reason: str = ""
