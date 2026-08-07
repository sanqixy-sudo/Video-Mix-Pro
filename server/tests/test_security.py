from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
import yaml


class SecurityFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ.update(
            {
                "ENVIRONMENT": "development",
                "DB_PATH": str(Path(cls.temp_dir.name) / "app.db"),
                "ADMIN_USER": "test-admin",
                "ADMIN_PASSWORD": "StrongTestPassword!",
                "ADMIN_TOKEN": "t" * 40,
                "ADMIN_COOKIE_SECURE": "false",
                "RATE_LIMIT_ENABLED": "true",
            }
        )
        cls.server = importlib.import_module("app")
        cls.client_context = TestClient(cls.server.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def setUp(self) -> None:
        with self.server.RATE_LIMIT_LOCK:
            self.server.RATE_LIMIT_BUCKETS.clear()
        with self.server.ADMIN_SESSIONS_LOCK:
            self.server.ADMIN_SESSIONS.clear()

    def unique_user(self, suffix: str) -> str:
        return f"test_{suffix}_{os.urandom(4).hex()}"

    def register_and_login(self, username: str, device_id: str = "device-a") -> dict:
        response = self.client.post("/api/auth/register", json={"username": username, "password": "UserPass123!"})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "UserPass123!", "device_id": device_id, "device_name": "test pc"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def create_code(self, code: str, plan: str = "month") -> None:
        with self.server.db() as conn:
            conn.execute(
                "INSERT INTO redeem_codes(code,plan,created_at,note) VALUES(?,?,?,?)",
                (code, plan, self.server.now_iso(), "unit test"),
            )

    def login_admin(self) -> tuple[TestClient, dict[str, str]]:
        client = TestClient(self.server.app)
        response = client.post(
            "/admin/login",
            json={"username": "test-admin", "password": "StrongTestPassword!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        page = client.get("/admin")
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
        self.assertIsNotNone(csrf)
        return client, {"X-CSRF-Token": csrf.group(1)}

    def test_session_hash_single_device_redeem_and_logout(self) -> None:
        username = self.unique_user("flow")
        first = self.register_and_login(username, "device-a")
        first_token = first["token"]

        with self.server.db() as conn:
            stored = conn.execute(
                "SELECT s.token FROM sessions s JOIN users u ON u.id=s.user_id WHERE u.username=?",
                (username,),
            ).fetchone()["token"]
        self.assertEqual(stored, hashlib.sha256(first_token.encode("utf-8")).hexdigest())
        self.assertNotEqual(stored, first_token)

        second = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "UserPass123!", "device_id": "device-b", "device_name": "second pc"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_data = second.json()

        invalidated = self.client.post("/api/auth/verify", json={"token": first_token, "device_id": "device-a"})
        self.assertEqual(invalidated.status_code, 401, invalidated.text)

        code = f"CODE-{os.urandom(5).hex().upper()}"
        self.create_code(code)
        redeemed = self.client.post(
            "/api/redeem",
            json={"token": second_data["token"], "device_id": "device-b", "code": code},
        )
        self.assertEqual(redeemed.status_code, 200, redeemed.text)
        self.assertTrue(redeemed.json()["active"])
        self.assertEqual(redeemed.json()["session_expires_at"], second_data["session_expires_at"])

        reused = self.client.post(
            "/api/redeem",
            json={"token": second_data["token"], "device_id": "device-b", "code": code},
        )
        self.assertEqual(reused.status_code, 400, reused.text)

        logged_out = self.client.post(
            "/api/auth/logout",
            json={"token": second_data["token"], "device_id": "device-b"},
        )
        self.assertEqual(logged_out.status_code, 200, logged_out.text)
        after_logout = self.client.post(
            "/api/auth/verify",
            json={"token": second_data["token"], "device_id": "device-b"},
        )
        self.assertEqual(after_logout.status_code, 401, after_logout.text)

    def test_plaintext_token_is_accepted_then_migrated(self) -> None:
        username = self.unique_user("legacy")
        login = self.register_and_login(username, "legacy-device")
        legacy_token = "legacy-plaintext-token"
        with self.server.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.execute(
                "INSERT INTO sessions(token,user_id,device_id,created_at,last_seen_at,expires_at) VALUES(?,?,?,?,?,?)",
                (
                    legacy_token,
                    user_id,
                    "legacy-device",
                    self.server.now_iso(),
                    self.server.now_iso(),
                    login["session_expires_at"],
                ),
            )

        response = self.client.post("/api/auth/verify", json={"token": legacy_token, "device_id": "legacy-device"})
        self.assertEqual(response.status_code, 403, response.text)
        with self.server.db() as conn:
            stored = conn.execute("SELECT token FROM sessions WHERE user_id=?", (user_id,)).fetchone()["token"]
        self.assertEqual(stored, hashlib.sha256(legacy_token.encode("utf-8")).hexdigest())

    def test_device_rebind_cooldown_and_admin_resets(self) -> None:
        username = self.unique_user("cooldown")
        first = self.register_and_login(username, "device-a")
        self.assertEqual(first["device_rebind_remaining_seconds"], 0)

        second = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "UserPass123!", "device_id": "device-b", "device_name": "B 电脑"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertGreater(second.json()["device_rebind_remaining_seconds"], 5 * 3600)

        blocked = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "UserPass123!", "device_id": "device-c", "device_name": "C 电脑"},
        )
        self.assertEqual(blocked.status_code, 423, blocked.text)
        self.assertEqual(blocked.json()["detail"]["code"], "DEVICE_REBIND_COOLDOWN")

        same_device = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "UserPass123!", "device_id": "device-b", "device_name": "B 电脑"},
        )
        self.assertEqual(same_device.status_code, 200, same_device.text)

        with self.server.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        admin, headers = self.login_admin()
        try:
            reset_cooldown = admin.post(
                "/admin/api/user_action",
                json={"user_id": user_id, "action": "reset_device_cooldown"},
                headers=headers,
            )
            self.assertEqual(reset_cooldown.status_code, 200, reset_cooldown.text)
            third = self.client.post(
                "/api/auth/login",
                json={"username": username, "password": "UserPass123!", "device_id": "device-c", "device_name": "C 电脑"},
            )
            self.assertEqual(third.status_code, 200, third.text)

            reset_device = admin.post(
                "/admin/api/user_action",
                json={"user_id": user_id, "action": "reset_device"},
                headers=headers,
            )
            self.assertEqual(reset_device.status_code, 200, reset_device.text)
            fresh_bind = self.client.post(
                "/api/auth/login",
                json={"username": username, "password": "UserPass123!", "device_id": "device-d", "device_name": "D 电脑"},
            )
            self.assertEqual(fresh_bind.status_code, 200, fresh_bind.text)
            self.assertEqual(fresh_bind.json()["device_rebind_remaining_seconds"], 0)
        finally:
            admin.close()

    def test_update_version_comparison_and_admin_validation(self) -> None:
        current = self.client.get("/api/update/check", params={"current_version": "0.1.0"})
        self.assertEqual(current.status_code, 200, current.text)
        self.assertTrue(current.json()["update_available"])

        invalid_version = self.client.get("/api/update/check", params={"current_version": "v1"})
        self.assertEqual(invalid_version.status_code, 400, invalid_version.text)

        admin, headers = self.login_admin()
        try:
            invalid_url = admin.post(
                "/admin/api/release",
                json={"latest_version": "0.3.0", "minimum_version": "0.2.0", "download_url": "https://example.com/app.exe"},
                headers=headers,
            )
            self.assertEqual(invalid_url.status_code, 400, invalid_url.text)

            invalid_sha = admin.post(
                "/admin/api/release",
                json={
                    "latest_version": "0.3.0",
                    "minimum_version": "0.2.0",
                    "download_url": "https://github.com/example/video-mix/releases/download/v0.3.0/app.exe",
                    "sha256": "1234",
                },
                headers=headers,
            )
            self.assertEqual(invalid_sha.status_code, 400, invalid_sha.text)

            published = admin.post(
                "/admin/api/release",
                json={
                    "latest_version": "0.3.0",
                    "minimum_version": "0.2.0",
                    "title": "Video Mix Pro 0.3.0",
                    "notes": "测试发布",
                    "download_url": "https://github.com/example/video-mix/releases/download/v0.3.0/app.exe",
                    "sha256": "A" * 64,
                },
                headers=headers,
            )
            self.assertEqual(published.status_code, 200, published.text)
            older = self.client.get("/api/update/check", params={"current_version": "0.1.9"}).json()
            supported = self.client.get("/api/update/check", params={"current_version": "0.2.5"}).json()
            latest = self.client.get("/api/update/check", params={"current_version": "0.3.0"}).json()
            self.assertTrue(older["required"])
            self.assertTrue(supported["update_available"])
            self.assertFalse(supported["required"])
            self.assertFalse(latest["update_available"])
            with self.server.db() as conn:
                history = conn.execute(
                    "SELECT latest_version,minimum_version,download_url,sha256 FROM app_release_history ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(history["latest_version"], "0.3.0")
            self.assertEqual(history["minimum_version"], "0.2.0")
            self.assertIn("/releases/download/v0.3.0/", history["download_url"])
            self.assertEqual(history["sha256"], "A" * 64)
        finally:
            admin.close()

    def test_disabled_and_expired_codes_cannot_be_redeemed(self) -> None:
        disabled_user = self.unique_user("disabled-code")
        disabled_login = self.register_and_login(disabled_user, "disabled-device")
        expired_user = self.unique_user("expired-code")
        expired_login = self.register_and_login(expired_user, "expired-code-device")
        with self.server.db() as conn:
            conn.execute(
                "INSERT INTO redeem_codes(code,plan,is_disabled,created_at,note) VALUES(?,?,1,?,?)",
                ("DISABLED-CODE-UNIT", "month", self.server.now_iso(), "unit disabled"),
            )
            conn.execute(
                "INSERT INTO redeem_codes(code,plan,expires_at,created_at,note) VALUES(?,?,?,?,?)",
                (
                    "EXPIRED-CODE-UNIT",
                    "month",
                    (self.server.now_utc() - timedelta(minutes=1)).isoformat(),
                    self.server.now_iso(),
                    "unit expired",
                ),
            )
        disabled = self.client.post(
            "/api/redeem",
            json={"token": disabled_login["token"], "device_id": "disabled-device", "code": "DISABLED-CODE-UNIT"},
        )
        expired = self.client.post(
            "/api/redeem",
            json={"token": expired_login["token"], "device_id": "expired-code-device", "code": "EXPIRED-CODE-UNIT"},
        )
        self.assertEqual(disabled.status_code, 400, disabled.text)
        self.assertIn("停用", disabled.text)
        self.assertEqual(expired.status_code, 400, expired.text)
        self.assertIn("过期", expired.text)

    def test_operations_console_code_filters_actions_and_export(self) -> None:
        username = self.unique_user("code-ops")
        login = self.register_and_login(username, "code-ops-device")
        admin, headers = self.login_admin()
        try:
            created = admin.post(
                "/admin/api/create_codes",
                json={"plan": "custom", "custom_days": 9, "count": 2, "note": "ops export"},
                headers=headers,
            )
            self.assertEqual(created.status_code, 200, created.text)
            payload = created.json()
            first, second = payload["created"]
            redeemed = self.client.post(
                "/api/redeem",
                json={"token": login["token"], "device_id": "code-ops-device", "code": first},
            )
            self.assertEqual(redeemed.status_code, 200, redeemed.text)

            disabled = admin.post(
                "/admin/api/code_action",
                json={"action": "disable", "batch_id": payload["batch_id"]},
                headers=headers,
            )
            self.assertEqual(disabled.status_code, 200, disabled.text)
            self.assertEqual(disabled.json()["matched"], 2)
            self.assertEqual(disabled.json()["affected"], 1)

            listed = admin.get("/admin/api/codes", params={"status": "disabled", "batch_id": payload["batch_id"]})
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(listed.json()["total"], 1)
            self.assertEqual(listed.json()["items"][0]["code"], second)
            exported = admin.get("/admin/api/codes/export", params={"batch_id": payload["batch_id"]})
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertIn(first, exported.text)
            self.assertIn(second, exported.text)

            deleted = admin.post(
                "/admin/api/code_action",
                json={"action": "delete_unused", "batch_id": payload["batch_id"]},
                headers=headers,
            )
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertEqual(deleted.json()["affected"], 1)
            with self.server.db() as conn:
                used = conn.execute("SELECT used_by FROM redeem_codes WHERE code=?", (first,)).fetchone()
                unused = conn.execute("SELECT used_by FROM redeem_codes WHERE code=?", (second,)).fetchone()
            self.assertIsNotNone(used)
            self.assertIsNone(unused)
        finally:
            admin.close()

    def test_operations_console_user_pagination_detail_and_batch_custom_grant(self) -> None:
        usernames = [self.unique_user(f"user-ops-{index}") for index in range(2)]
        user_ids = []
        for index, username in enumerate(usernames):
            self.register_and_login(username, f"user-ops-device-{index}")
            with self.server.db() as conn:
                user_ids.append(conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"])
        admin, headers = self.login_admin()
        try:
            listed = admin.get("/admin/api/users", params={"q": usernames[0], "page": 1, "page_size": 10})
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(listed.json()["total"], 1)
            detail = admin.get(f"/admin/api/users/{user_ids[0]}")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()["user"]["username"], usernames[0])
            self.assertGreaterEqual(detail.json()["active_sessions"], 1)

            granted = admin.post(
                "/admin/api/user_batch_action",
                json={"action": "grant", "user_ids": user_ids, "plan": "custom", "custom_days": 12},
                headers=headers,
            )
            self.assertEqual(granted.status_code, 200, granted.text)
            self.assertEqual(granted.json()["affected"], 2)
            with self.server.db() as conn:
                rows = conn.execute(
                    f"SELECT plan,member_expires_at FROM users WHERE id IN ({','.join('?' for _ in user_ids)})",
                    user_ids,
                ).fetchall()
            self.assertTrue(all(row["plan"] == "custom" for row in rows))
            self.assertTrue(all(self.server.parse_dt(row["member_expires_at"]) > self.server.now_utc() + timedelta(days=11) for row in rows))

            audit = admin.get("/admin/api/audit", params={"action": "user_batch_grant"})
            self.assertEqual(audit.status_code, 200, audit.text)
            self.assertGreaterEqual(audit.json()["total"], 1)
        finally:
            admin.close()

    def test_additive_migration_preserves_legacy_user(self) -> None:
        old_path = self.server.DB_PATH
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            legacy_path = Path(folder) / "legacy.db"
            with sqlite3.connect(legacy_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE users(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO users(username,password_hash,created_at,updated_at) VALUES(?,?,?,?)",
                    ("legacy-user", "legacy-hash", "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
                )
            self.server.DB_PATH = legacy_path
            try:
                self.server.init_db()
                with self.server.db() as conn:
                    user = conn.execute("SELECT username,password_hash FROM users WHERE username='legacy-user'").fetchone()
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
                    release = conn.execute("SELECT latest_version FROM app_releases WHERE channel='stable'").fetchone()
                self.assertEqual(user["password_hash"], "legacy-hash")
                self.assertIn("device_rebind_cooldown_until", columns)
                self.assertEqual(release["latest_version"], self.server.APP_VERSION)
                self.assertTrue(any((legacy_path.parent / "backups").glob("*.pre_migration.bak")))
            finally:
                self.server.DB_PATH = old_path

    def test_expired_session_is_deleted(self) -> None:
        username = self.unique_user("expired")
        login = self.register_and_login(username, "expired-device")
        digest = hashlib.sha256(login["token"].encode("utf-8")).hexdigest()
        with self.server.db() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at=? WHERE token=?",
                ((self.server.now_utc() - timedelta(minutes=1)).isoformat(), digest),
            )

        response = self.client.post(
            "/api/auth/verify",
            json={"token": login["token"], "device_id": "expired-device"},
        )
        self.assertEqual(response.status_code, 401, response.text)
        with self.server.db() as conn:
            count = conn.execute("SELECT COUNT(*) AS total FROM sessions WHERE token=?", (digest,)).fetchone()["total"]
        self.assertEqual(count, 0)

    def test_admin_csrf_and_logout(self) -> None:
        client = TestClient(self.server.app)
        login = client.post(
            "/admin/login",
            json={"username": "test-admin", "password": "StrongTestPassword!"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        page = client.get("/admin")
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
        self.assertIsNotNone(csrf)

        denied = client.post("/admin/api/create_codes", json={"plan": "month", "count": 1, "note": "csrf"})
        self.assertEqual(denied.status_code, 403, denied.text)

        headers = {"X-CSRF-Token": csrf.group(1)}
        created = client.post(
            "/admin/api/create_codes",
            json={"plan": "month", "count": 1, "note": "csrf"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 200, created.text)

        logged_out = client.post("/admin/logout", json={}, headers=headers)
        self.assertEqual(logged_out.status_code, 200, logged_out.text)
        self.assertEqual(logged_out.json()["redirect_url"], "/")
        self.assertNotIn('name="csrf-token"', client.get("/admin").text)
        client.close()

    def test_admin_password_pricing_release_history_and_private_entry(self) -> None:
        username = self.unique_user("admin-tools")
        login = self.register_and_login(username, "admin-tools-device")
        with self.server.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]

        admin, headers = self.login_admin()
        try:
            changed = admin.post(
                "/admin/api/user_action",
                json={"user_id": user_id, "action": "change_password", "new_password": "ChangedPass456!"},
                headers=headers,
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            old_session = self.client.post(
                "/api/auth/verify", json={"token": login["token"], "device_id": "admin-tools-device"}
            )
            self.assertEqual(old_session.status_code, 401, old_session.text)
            old_password = self.client.post(
                "/api/auth/login",
                json={"username": username, "password": "UserPass123!", "device_id": "admin-tools-device"},
            )
            self.assertEqual(old_password.status_code, 401, old_password.text)
            new_password = self.client.post(
                "/api/auth/login",
                json={"username": username, "password": "ChangedPass456!", "device_id": "admin-tools-device"},
            )
            self.assertEqual(new_password.status_code, 200, new_password.text)

            prices = {"month": "¥29", "quarter": "¥79", "year": "¥199", "permanent": "¥399"}
            pricing = admin.post("/admin/api/pricing", json={"prices": prices}, headers=headers)
            self.assertEqual(pricing.status_code, 200, pricing.text)
            public_pricing = self.client.get("/api/site/pricing")
            self.assertEqual(public_pricing.status_code, 200, public_pricing.text)
            self.assertEqual(
                {item["plan"]: item["price_display"] for item in public_pricing.json()["items"]}, prices
            )

            published = admin.post(
                "/admin/api/release",
                json={
                    "latest_version": "0.4.0",
                    "minimum_version": "0.2.0",
                    "title": "Video Mix Pro 0.4.0",
                    "download_url": "https://github.com/example/video-mix/releases/download/v0.4.0/app.exe",
                },
                headers=headers,
            )
            self.assertEqual(published.status_code, 200, published.text)
            summary = admin.get("/admin/api/summary").json()
            history = next(item for item in summary["release_history"] if item["latest_version"] == "0.4.0")
            edited = admin.put(
                f"/admin/api/release_history/{history['id']}",
                json={
                    "latest_version": "0.4.0",
                    "minimum_version": "0.2.0",
                    "title": "已修正的历史标题",
                    "notes": "修正历史说明",
                    "download_url": "https://github.com/example/video-mix/releases/download/v0.4.0/app.exe",
                },
                headers=headers,
            )
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(self.client.get("/api/update/latest").json()["title"], "Video Mix Pro 0.4.0")
            deleted = admin.delete(f"/admin/api/release_history/{history['id']}", headers=headers)
            self.assertEqual(deleted.status_code, 200, deleted.text)
            with self.server.db() as conn:
                self.assertIsNone(conn.execute("SELECT id FROM app_release_history WHERE id=?", (history["id"],)).fetchone())

            site = self.client.get("/")
            self.assertEqual(site.status_code, 200, site.text)
            self.assertNotIn('href="/admin"', site.text)
            self.assertIn("v0.4.0", site.text)
        finally:
            admin.close()

    def test_rate_limit_and_production_health_redaction(self) -> None:
        self.server.check_rate_limit("unit-rate", 2, 60)
        self.server.check_rate_limit("unit-rate", 2, 60)
        with self.assertRaises(HTTPException) as raised:
            self.server.check_rate_limit("unit-rate", 2, 60)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn("Retry-After", raised.exception.headers)

        previous = self.server.IS_PRODUCTION
        self.server.IS_PRODUCTION = True
        try:
            response = self.server.health()
            payload = json.loads(response.body)
        finally:
            self.server.IS_PRODUCTION = previous
        self.assertNotIn("database", payload)
        self.assertNotIn("environment", payload)

    def test_container_hardening_configuration(self) -> None:
        server_dir = Path(__file__).resolve().parents[1]
        compose = yaml.safe_load((server_dir / "docker-compose.yml").read_text(encoding="utf-8"))
        service = compose["services"]["video-mix-member"]
        self.assertTrue(service["init"])
        self.assertTrue(service["read_only"])
        self.assertIn("ALL", service["cap_drop"])
        self.assertIn("no-new-privileges:true", service["security_opt"])
        self.assertIn("/tmp:size=64m,mode=1777", service["tmpfs"])
        self.assertIn("${BIND_ADDRESS:-0.0.0.0}:57231:8000", service["ports"])

        dockerfile = (server_dir / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER appuser", dockerfile)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", dockerfile)
        self.assertIn("COPY templates /app/templates", dockerfile)
        self.assertIn("COPY static /app/static", dockerfile)


if __name__ == "__main__":
    unittest.main()
