"""Command-line demo for vrc-profile-proof."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path
from typing import Any

from .client import VRChatClient
from .errors import (
    AmbiguousUserError,
    ChallengeError,
    RateLimitExceeded,
    UserResolutionError,
    VRChatAPIError,
)
from .verification import DEFAULT_CONTEXT_LABEL, VerificationService


DEFAULT_CLI_USER_AGENT = "vrc-profile-proof-cli/0.1 local-use"


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def build_client() -> VRChatClient:
    user_agent = os.environ.get("VRC_USER_AGENT", DEFAULT_CLI_USER_AGENT).strip()
    if user_agent == DEFAULT_CLI_USER_AGENT:
        print(
            "提示：正式使用时请设置 VRC_USER_AGENT='application/version contact'。"
        )
    return VRChatClient(user_agent=user_agent)


def login_service_account(client: VRChatClient) -> dict[str, Any]:
    auth_cookie = os.environ.get("VRC_AUTH_COOKIE", "").strip()
    if not auth_cookie:
        print("需要服务端自己的 VRChat auth cookie；不会向最终用户索取凭据。")
        auth_cookie = getpass.getpass("Server VRChat auth cookie: ").strip()
    two_factor_cookie = os.environ.get("VRC_TWO_FACTOR_AUTH_COOKIE", "").strip() or None
    current_user = client.login_with_cookie(
        auth_cookie,
        two_factor_cookie=two_factor_cookie,
    )
    if current_user.get("requiresTwoFactorAuth"):
        raise VRChatAPIError(
            401,
            "service auth cookie still requires two-factor authentication",
        )
    return current_user


def prompt_non_empty(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value


def start_with_retry(
    service: VerificationService,
    user_input: str,
    context_label: str,
):
    while True:
        try:
            return service.start_verification(
                user_input,
                context_label=context_label,
            )
        except AmbiguousUserError as exc:
            print(f"\n{exc.query!r} 匹配到多个用户：")
            for index, candidate in enumerate(exc.candidates, start=1):
                print(
                    f"  {index}. {candidate.get('displayName') or '(unknown)'}  "
                    f"{candidate.get('id') or '(missing id)'}"
                )
            user_input = prompt_non_empty("粘贴目标 user ID / profile URL: ")


def main() -> int:
    load_dotenv()
    client = build_client()
    try:
        service_user = login_service_account(client)
    except VRChatAPIError as exc:
        print(f"服务端登录失败：{exc.message}", file=sys.stderr)
        return 1

    service = VerificationService(client)
    service_name = service_user.get("displayName") or service_user.get("username") or "unknown"
    print(f"服务端 API 登录成功：{service_name}")
    print("本次启动使用临时随机 secret；重启后未完成的 challenge 自动失效。")

    context_label = (
        input(f"\n验证用途名 / 服务名 [{DEFAULT_CONTEXT_LABEL}]: ").strip()
        or DEFAULT_CONTEXT_LABEL
    )
    user_input = prompt_non_empty("用户输入（user ID / profile URL / display name）: ")
    try:
        challenge = start_with_retry(service, user_input, context_label)
    except (VRChatAPIError, UserResolutionError, RateLimitExceeded) as exc:
        print(f"创建验证请求失败：{exc}", file=sys.stderr)
        return 1

    print("\n验证请求已创建：")
    print(f"  displayName: {challenge.display_name}")
    print(f"  userId:      {challenge.user_id}")
    print(f"  trustRank:   {challenge.trust_rank.value}")
    print(f"  expiresAt:   {challenge.expires_at.isoformat()}")
    print("\n让用户把下面这一整段复制到 VRChat bio：")
    print(challenge.text)

    if input("\n调用方是否继续验证？[Y/n]: ").strip().lower() in {"n", "no"}:
        service.discard(challenge.challenge_id)
        print("已取消验证。")
        return 0

    print("\n保存 bio 后按回车检查；输入 q 退出。")
    while True:
        if input("检查现在的 bio [Enter/q]: ").strip().lower() in {"q", "quit", "exit"}:
            return 0
        try:
            result = service.verify(challenge.challenge_id)
        except RateLimitExceeded as exc:
            print(f"请求过快，请等待 {exc.retry_after:.1f} 秒后重试。")
            continue
        except (VRChatAPIError, ChallengeError) as exc:
            print(f"检查失败：{exc}", file=sys.stderr)
            continue

        if result.success:
            print("\n验证成功：")
            print(f"userId:    {result.user_id}")
            print(f"trustRank: {result.trust_rank.value}")
            return 0
        print(f"尚未通过：{result.reason}")


if __name__ == "__main__":
    raise SystemExit(main())
