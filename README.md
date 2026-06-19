[中文版本 Chinese Version](README.zh.md)

# vrc-profile-proof

`vrc-profile-proof` is an unofficial Python library for proving that a person can control a VRChat profile. It creates a short-lived challenge, asks the user to place it in their public bio, then fetches the profile again and verifies the token.

## Properties

- No VRChat credentials or session cookies are requested from end users.
- Every challenge has an independent random nonce.
- Challenges expire after 10 minutes by default and can succeed only once.
- The service secret is random and process-local by default, so restarts invalidate pending challenges.
- Every verification attempt fetches a fresh profile. There is no profile cache.
- Unicode NFKC normalization tolerates common half-width/full-width changes.
- The returned challenge includes the complete VRChat profile and normalized trust rank.
- Global and per-user in-memory rate limits are configurable.

## Installation

```powershell
python -m pip install -e .
```

The package has no runtime dependencies and requires Python 3.11 or newer.

## Library usage

```python
from vrc_profile_proof import VRChatClient, VerificationService

client = VRChatClient(
    user_agent="my-app/1.0 operator@example.com",
)
client.login_with_cookie("authcookie_xxxxx")

service = VerificationService(client)

challenge = service.start_verification(
    "usr_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    context_label="My App Profile Verify",
)

print(challenge.text)
print(challenge.user_id)
print(challenge.trust_rank.value)

# After the user saves challenge.text in their VRChat bio:
result = service.verify(challenge.challenge_id)
if result.success:
    print(result.user_id)
```

`start_verification()` accepts a user ID, a VRChat profile URL containing a user ID, or a display name. Display-name searches can be ambiguous; callers should catch `AmbiguousUserError` and ask the user to select a returned candidate.

## Challenge format

A challenge looks like this:

`【My App Profile Verify - vrcverifyxxxxxxxxxxxxxxxxxxxxxxxxxx】`

The purpose label is included in the HMAC input. The core token uses letters and digits, and verification searches for that token after Unicode NFKC normalization, so punctuation or spacing changes made by VRChat do not normally break verification.

## Rate limiting

The default policies are intentionally tolerant of user mistakes:

- Global: 60 start/check operations per 60 seconds.
- Per user: at most one check every 2 seconds.
- Per user: 5 consecutive failed checks are allowed.
- After the fifth consecutive failure: 5-minute cooldown.
- A successful check resets the user's failure streak.
- A failure streak also resets after 5 minutes without another failure.

Customize them when creating the limiter:

```python
from vrc_profile_proof import (
    GlobalRateLimit,
    UserRateLimit,
    VerificationRateLimiter,
    VerificationService,
)

limiter = VerificationRateLimiter(
    global_policy=GlobalRateLimit(max_operations=120, window_seconds=60),
    user_policy=UserRateLimit(
        min_interval_seconds=2,
        failures_before_cooldown=5,
        failure_reset_seconds=300,
        cooldown_seconds=600,
    ),
)
service = VerificationService(client, rate_limiter=limiter)
```

`RateLimitExceeded` includes `scope` and `retry_after`, making it straightforward for an HTTP service to return a useful `429` response.

## CLI demo

Copy `.env.example` to `.env`, fill in the service operator's cookie and User-Agent, then run:

```powershell
vrc-profile-proof
```

The cookie belongs to the service operator. Do not request an end user's VRChat password, auth cookie, token, or session data.

## Security notes

- A successful result proves control of a public VRChat profile at verification time. It is not proof of legal identity.
- Keep pending challenges in the same process as `VerificationService`; they intentionally do not survive restarts.
- Treat trust rank as an anti-abuse signal, not a guarantee that an account is legitimate.
- Use a descriptive User-Agent and follow VRChat API usage rules, including backing off on `429` responses.
- Display your own service name in the challenge. Do not imply that the flow is an official VRChat login.

## Development

```powershell
python -m unittest discover -s tests -v
```

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by VRChat Inc. It is profile-control verification, not official "Login with VRChat" or OAuth.