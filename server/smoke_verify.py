#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


class HttpClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf_token = ""

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> tuple[int, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
            if path.startswith("/admin/") and self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.status, self._decode(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, self._decode(exc.read())

    def _decode(self, raw: bytes) -> Any:
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def print_step(name: str, status: int, payload: Any) -> None:
    summary = payload
    if isinstance(payload, dict):
        summary = {key: payload.get(key) for key in sorted(payload) if key not in {"token"}}
    print(f"[{status}] {name}: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the Video Mix membership server APIs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:57231", help="Server base URL")
    parser.add_argument("--admin-user", required=True, help="Admin username")
    parser.add_argument("--admin-password", required=True, help="Admin password")
    parser.add_argument("--username", help="Test username; defaults to a random smoke_* user")
    parser.add_argument("--password", default="SmokePass12345", help="Test user password")
    parser.add_argument("--device-id", default="smoke-device", help="Test device id")
    parser.add_argument("--device-name", default="smoke verify", help="Test device name")
    parser.add_argument("--redeem-code", help="Existing redeem code to use; otherwise the admin API creates one")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    client = HttpClient(args.base_url, args.timeout)
    username = args.username or f"smoke_{secrets.token_hex(5)}"

    status, payload = client.request("GET", "/api/health")
    print_step("health", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("ok") is True, "health check failed")

    status, payload = client.request("POST", "/admin/login", {"username": args.admin_user, "password": args.admin_password})
    print_step("admin login", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("ok") is True, "admin login failed")

    status, payload = client.request("GET", "/admin")
    print_step("admin session", status, "html loaded" if isinstance(payload, str) else payload)
    require(status == 200 and isinstance(payload, str), "admin page failed")
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', payload)
    require(match is not None, "admin CSRF token missing")
    client.csrf_token = match.group(1)

    status, payload = client.request("POST", "/api/auth/register", {"username": username, "password": args.password})
    print_step("register", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("ok") is True, "register failed")

    status, payload = client.request(
        "POST",
        "/api/auth/login",
        {"username": username, "password": args.password, "device_id": args.device_id, "device_name": args.device_name},
    )
    print_step("login", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("token"), "login failed")
    token = payload["token"]

    redeem_code = args.redeem_code
    if not redeem_code:
        status, payload = client.request("POST", "/admin/api/create_codes", {"plan": "month", "count": 1, "note": "smoke verify"})
        print_step("admin create code", status, payload)
        require(status == 200 and isinstance(payload, dict) and payload.get("created"), "create code failed")
        redeem_code = payload["created"][0]

    status, payload = client.request("POST", "/api/redeem", {"token": token, "device_id": args.device_id, "code": redeem_code})
    print_step("redeem", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("active") is True, "redeem failed")

    status, payload = client.request("POST", "/api/auth/verify", {"token": token, "device_id": args.device_id})
    print_step("verify", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("active") is True, "verify failed")

    status, payload = client.request("POST", "/api/auth/logout", {"token": token, "device_id": args.device_id})
    print_step("logout", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("ok") is True, "logout failed")

    status, payload = client.request("POST", "/api/auth/verify", {"token": token, "device_id": args.device_id})
    print_step("verify logged-out token", status, payload)
    require(status == 401, "logged-out token remained valid")

    status, payload = client.request("POST", "/admin/logout", {})
    print_step("admin logout", status, payload)
    require(status == 200 and isinstance(payload, dict) and payload.get("ok") is True, "admin logout failed")

    print(f"Smoke verify passed for {args.base_url} using user {username}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Smoke verify failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
