"""VRChat profile-control verification using temporary bio challenges."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .client import VRChatClient
from .errors import (
    AmbiguousUserError,
    ChallengeAlreadyUsedError,
    ChallengeError,
    ChallengeExpiredError,
    ChallengeNotFoundError,
    UserResolutionError,
)
from .models import TrustRank, VerificationChallenge, VerificationResult
from .rate_limit import VerificationRateLimiter


USER_ID_PATTERN = re.compile(
    r"usr_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
DEFAULT_CONTEXT_LABEL = "Profile Verify"
LEFT_BRACKET = "【"
RIGHT_BRACKET = "】"
LABEL_TOKEN_SEPARATOR = " - "


@dataclass
class _ChallengeRecord:
    challenge: VerificationChallenge
    token: str
    expires_at_epoch: float
    used: bool = False
    verifying: bool = False


class VerificationService:
    """Creates and checks short-lived, in-memory VRChat bio challenges.

    Challenges are intentionally process-local. A random service secret is created
    by default, and all pending challenges become invalid when the process exits.
    """

    def __init__(
        self,
        client: VRChatClient,
        *,
        challenge_ttl_seconds: float = 600.0,
        secret: bytes | None = None,
        rate_limiter: VerificationRateLimiter | None = None,
        wall_clock: Callable[[], float] = time.time,
    ):
        if challenge_ttl_seconds <= 0:
            raise ValueError("challenge_ttl_seconds must be greater than zero")
        self.client = client
        self.challenge_ttl_seconds = challenge_ttl_seconds
        self._secret = secret or secrets.token_bytes(32)
        if not self._secret:
            raise ValueError("secret cannot be empty")
        self.rate_limiter = rate_limiter or VerificationRateLimiter()
        self._wall_clock = wall_clock
        self._challenges: dict[str, _ChallengeRecord] = {}
        self._lock = threading.RLock()

    def start_verification(
        self,
        user_input: str,
        *,
        context_label: str = DEFAULT_CONTEXT_LABEL,
    ) -> VerificationChallenge:
        self.rate_limiter.check_global()
        profile = resolve_user_profile(self.client, user_input)
        user_id = require_profile_user_id(profile)
        label = normalize_context_label(context_label)
        now = self._wall_clock()
        expires_at_epoch = now + self.challenge_ttl_seconds
        challenge_id = secrets.token_urlsafe(18)
        nonce = secrets.token_bytes(16)
        token = self._make_token(user_id, label, challenge_id, nonce, expires_at_epoch)
        text = format_challenge_text(label, token)
        challenge = VerificationChallenge(
            challenge_id=challenge_id,
            user_id=user_id,
            display_name=str(profile.get("displayName") or ""),
            trust_rank=extract_trust_rank(profile),
            text=text,
            context_label=label,
            expires_at=datetime.fromtimestamp(expires_at_epoch, timezone.utc),
            profile=profile,
        )
        with self._lock:
            self._prune_challenges(now)
            self._challenges[challenge_id] = _ChallengeRecord(
                challenge=challenge,
                token=token,
                expires_at_epoch=expires_at_epoch,
            )
        return challenge

    def verify(self, challenge_id: str) -> VerificationResult:
        now = self._wall_clock()
        with self._lock:
            record = self._challenges.get(challenge_id)
            if record is None:
                raise ChallengeNotFoundError("challenge was not found")
            if record.used:
                raise ChallengeAlreadyUsedError("challenge has already been used")
            if record.expires_at_epoch <= now:
                raise ChallengeExpiredError("challenge has expired")
            if record.verifying:
                raise ChallengeError("challenge verification is already in progress")
            record.verifying = True

        user_id = record.challenge.user_id
        try:
            self.rate_limiter.check_user(user_id)
            self.rate_limiter.check_global()
            profile = self.client.get_user(user_id)
            bio = str(profile.get("bio") or "")
            success = bio_contains_token(bio, record.token)
            result = VerificationResult(
                success=success,
                user_id=user_id,
                display_name=str(profile.get("displayName") or ""),
                trust_rank=extract_trust_rank(profile),
                profile=profile,
                reason="" if success else "challenge token was not found in the user's bio",
            )
            if success:
                self.rate_limiter.record_success(user_id)
                with self._lock:
                    record.used = True
            else:
                self.rate_limiter.record_failure(user_id)
            return result
        finally:
            with self._lock:
                record.verifying = False

    def discard(self, challenge_id: str) -> None:
        with self._lock:
            self._challenges.pop(challenge_id, None)

    def _make_token(
        self,
        user_id: str,
        label: str,
        challenge_id: str,
        nonce: bytes,
        expires_at_epoch: float,
    ) -> str:
        message = b"\0".join(
            (
                user_id.encode("utf-8"),
                label.encode("utf-8"),
                challenge_id.encode("ascii"),
                nonce,
                str(int(expires_at_epoch)).encode("ascii"),
            )
        )
        digest = hmac.new(self._secret, message, hashlib.sha256).digest()
        encoded = base64.b32encode(digest[:16]).decode("ascii").rstrip("=").lower()
        return f"vrcverify{encoded}"

    def _prune_challenges(self, now: float) -> None:
        retention_seconds = 3600.0
        stale_ids = [
            challenge_id
            for challenge_id, record in self._challenges.items()
            if record.used or record.expires_at_epoch + retention_seconds <= now
        ]
        for challenge_id in stale_ids:
            self._challenges.pop(challenge_id, None)


def resolve_user_profile(
    client: VRChatClient,
    user_input: str,
    *,
    search_limit: int = 10,
) -> dict[str, Any]:
    value = user_input.strip()
    if not value:
        raise UserResolutionError("user input cannot be empty")
    user_id = extract_user_id(value)
    if user_id:
        return client.get_user(user_id)

    query = normalize_name_query(value)
    candidates = client.search_users(query, limit=search_limit)
    if not candidates:
        raise UserResolutionError(f"no VRChat users matched {query!r}")
    exact = [
        candidate
        for candidate in candidates
        if str(candidate.get("displayName", "")).casefold() == query.casefold()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(candidates) == 1:
        return candidates[0]
    raise AmbiguousUserError(query, candidates)


def extract_user_id(value: str) -> str | None:
    match = USER_ID_PATTERN.search(urllib.parse.unquote(value))
    return match.group(0) if match else None


def normalize_name_query(value: str) -> str:
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme and parsed.netloc:
        tail = parsed.path.rstrip("/").split("/")[-1]
        if tail:
            return urllib.parse.unquote(tail)
    return value.strip()


def normalize_context_label(value: str) -> str:
    label = unicodedata.normalize("NFKC", value or "").strip()
    label = re.sub(r"\s+", " ", label)
    label = label.replace(LEFT_BRACKET, "").replace(RIGHT_BRACKET, "")
    return label[:40] or DEFAULT_CONTEXT_LABEL


def format_challenge_text(label: str, token: str) -> str:
    return f"{LEFT_BRACKET}{label}{LABEL_TOKEN_SEPARATOR}{token}{RIGHT_BRACKET}"


def bio_contains_token(bio: str, token: str) -> bool:
    normalized_bio = unicodedata.normalize("NFKC", bio)
    normalized_token = unicodedata.normalize("NFKC", token)
    return normalized_token in normalized_bio


def require_profile_user_id(profile: dict[str, Any]) -> str:
    user_id = profile.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise UserResolutionError("VRChat profile did not include a user ID")
    return user_id


def extract_trust_rank(profile: dict[str, Any]) -> TrustRank:
    tags = profile.get("tags")
    if not isinstance(tags, list):
        return TrustRank.UNKNOWN
    tag_set = {str(tag) for tag in tags}
    if "system_trust_troll" in tag_set:
        return TrustRank.NUISANCE
    if "system_probable_troll" in tag_set:
        return TrustRank.PROBABLE_NUISANCE
    rank_by_tag = (
        ("system_trust_legend", TrustRank.VETERAN_USER),
        ("system_trust_veteran", TrustRank.TRUSTED_USER),
        ("system_trust_trusted", TrustRank.KNOWN_USER),
        ("system_trust_known", TrustRank.USER),
        ("system_trust_basic", TrustRank.NEW_USER),
    )
    for tag, rank in rank_by_tag:
        if tag in tag_set:
            return rank
    return TrustRank.VISITOR
