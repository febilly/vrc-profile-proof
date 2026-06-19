"""Minimal VRChat HTTP client used by the verification service."""

from __future__ import annotations

import base64
import http.cookies
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import Cookie
from typing import Any

from .errors import VRChatAPIError


DEFAULT_BASE_URL = "https://api.vrchat.cloud/api/1"


class VRChatClient:
    def __init__(
        self,
        user_agent: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ):
        user_agent = user_agent.strip()
        if not user_agent:
            raise ValueError("user_agent is required")
        self.user_agent = user_agent
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.last_response_headers: dict[str, str] = {}

    def set_cookie(self, name: str, value: str) -> None:
        cookie = Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=".vrchat.cloud",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
            rfc2109=False,
        )
        self.cookie_jar.set_cookie(cookie)

    def apply_cookie_text(self, cookie_text: str) -> None:
        cookie_text = cookie_text.strip()
        if not cookie_text:
            raise VRChatAPIError(0, "auth cookie cannot be empty")
        if "=" not in cookie_text:
            self.set_cookie("auth", cookie_text)
            return

        parsed = http.cookies.SimpleCookie()
        try:
            parsed.load(cookie_text)
        except http.cookies.CookieError as exc:
            raise VRChatAPIError(0, f"invalid cookie text: {exc}") from exc

        loaded = False
        for name in ("auth", "twoFactorAuth"):
            morsel = parsed.get(name)
            if morsel is not None and morsel.value:
                self.set_cookie(name, morsel.value)
                loaded = True
        if not loaded:
            raise VRChatAPIError(0, "cookie text did not contain auth or twoFactorAuth")

    def login_with_cookie(
        self,
        auth_cookie: str,
        *,
        two_factor_cookie: str | None = None,
    ) -> dict[str, Any]:
        self.apply_cookie_text(auth_cookie)
        if two_factor_cookie:
            self.set_cookie("twoFactorAuth", two_factor_cookie)
        return self.get_current_user()

    def get_current_user(self) -> dict[str, Any]:
        response = self.request_json("GET", "/auth/user")
        if not isinstance(response, dict):
            raise VRChatAPIError(-1, "expected an object from /auth/user")
        return response

    def get_user(self, user_id: str) -> dict[str, Any]:
        response = self.request_json("GET", f"/users/{user_id}")
        if not isinstance(response, dict):
            raise VRChatAPIError(-1, "expected an object from /users/{userId}")
        return response

    def search_users(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {
                "search": query,
                "n": max(1, min(limit, 100)),
                "offset": max(0, offset),
            }
        )
        response = self.request_json("GET", f"/users?{params}")
        if not isinstance(response, list):
            raise VRChatAPIError(-1, "expected an array from user search")
        return [item for item in response if isinstance(item, dict)]

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        basic_auth: tuple[str, str] | None = None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if basic_auth is not None:
            username, password = basic_auth
            encoded = base64.b64encode(f"{username}:{password}".encode("utf-8"))
            headers["Authorization"] = f"Basic {encoded.decode('ascii')}"

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                self.last_response_headers = dict(response.headers.items())
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            self.last_response_headers = dict(exc.headers.items())
            payload = exc.read().decode("utf-8", errors="replace")
            raise VRChatAPIError(
                exc.code,
                _extract_error_message(payload),
                self.last_response_headers,
            ) from exc
        except urllib.error.URLError as exc:
            raise VRChatAPIError(0, str(exc.reason)) from exc

        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise VRChatAPIError(-1, f"invalid JSON response: {payload[:200]}") from exc


def _extract_error_message(payload: str) -> str:
    if not payload:
        return "no response body"
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return payload[:500]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("status_code") or payload).strip('"')
        return str(parsed.get("message") or payload).strip('"')
    return payload[:500]
