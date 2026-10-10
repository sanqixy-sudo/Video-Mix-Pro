# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from admin_schema import EXTRA_COLUMNS, migrate as migrate_admin

APP_PORT = 57231
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DB_PATH", "/app/data/app.db"))
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT in {"prod", "production"}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    return max(minimum, min(value, maximum))


def read_secret(name: str, default: str = "") -> str:
    file_path = os.environ.get(f"{name}_FILE", "").strip()
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except Exception as exc:
            raise RuntimeError(f"cannot read {name}_FILE: {exc}") from exc
    return os.environ.get(name, default)


ADMIN_USER = read_secret("ADMIN_USER", "admin")
ADMIN_PASSWORD = read_secret("ADMIN_PASSWORD", "local-dev-admin-password")
ADMIN_TOKEN_ENV = read_secret("ADMIN_TOKEN")
ADMIN_TOKEN = ADMIN_TOKEN_ENV or secrets.token_urlsafe(32)
SESSION_TTL_DAYS = env_int("SESSION_TTL_DAYS", 30, 1, 365)
SESSION_IDLE_HOURS = env_int("SESSION_IDLE_HOURS", 168, 1, 8760)
ADMIN_SESSION_HOURS = env_int("ADMIN_SESSION_HOURS", 8, 1, 72)
DEVICE_REBIND_COOLDOWN_HOURS = env_int("DEVICE_REBIND_COOLDOWN_HOURS", 6, 1, 168)
ADMIN_COOKIE_SECURE = env_bool("ADMIN_COOKIE_SECURE", IS_PRODUCTION)
TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", False)
RATE_LIMIT_ENABLED = env_bool("RATE_LIMIT_ENABLED", True)
APP_VERSION = os.environ.get("APP_VERSION", "0.2.1").strip() or "0.2.1"
SERVER_VERSION = os.environ.get("SERVER_VERSION", "0.3.0").strip() or "0.3.0"
LEGACY_CLIENT_VERSION = os.environ.get("LEGACY_CLIENT_VERSION", "0.2.0").strip() or "0.2.0"
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOW_ORIGINS",
        "http://tauri.localhost,https://tauri.localhost,tauri://localhost" if IS_PRODUCTION else "*",
    ).split(",")
    if origin.strip()
]
UNSAFE_ADMIN_TOKENS = {"", "change-this", "change-this-admin-token-15e77b3a974e3b97"}
EXPECTED_SCHEMA_COLUMNS = {
    "users": {
        "username": "TEXT",
        "password_hash": "TEXT",
        "is_member": "INTEGER NOT NULL DEFAULT 0",
        "plan": "TEXT",
        "member_expires_at": "TEXT",
        "device_id": "TEXT",
        "device_name": "TEXT",
        "device_bound_at": "TEXT",
        "device_rebind_cooldown_until": "TEXT",
        "is_banned": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    },
    "sessions": {
        "token": "TEXT",
        "user_id": "INTEGER",
        "device_id": "TEXT",
        "created_at": "TEXT",
        "last_seen_at": "TEXT",
        "expires_at": "TEXT",
    },
    "redeem_codes": {
        "code": "TEXT",
        "plan": "TEXT",
        "custom_days": "INTEGER",
        "batch_id": "TEXT",
        "expires_at": "TEXT",
        "is_disabled": "INTEGER NOT NULL DEFAULT 0",
        "disabled_at": "TEXT",
        "used_by": "INTEGER",
        "used_by_username_snapshot": "TEXT",
        "used_at": "TEXT",
        "created_at": "TEXT",
        "note": "TEXT",
    },
    "audit_logs": {
        "actor": "TEXT",
        "action": "TEXT",
        "target": "TEXT",
        "detail": "TEXT",
        "ip": "TEXT",
        "created_at": "TEXT",
    },
    "app_releases": {
        "channel": "TEXT",
        "latest_version": "TEXT",
        "minimum_version": "TEXT",
        "title": "TEXT",
        "notes": "TEXT",
        "download_url": "TEXT",
        "sha256": "TEXT",
        "is_mandatory": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT",
    },
    "app_release_history": {
        "id": "INTEGER",
        "channel": "TEXT",
        "latest_version": "TEXT",
        "minimum_version": "TEXT",
        "title": "TEXT",
        "notes": "TEXT",
        "download_url": "TEXT",
        "sha256": "TEXT",
        "is_mandatory": "INTEGER NOT NULL DEFAULT 0",
        "published_at": "TEXT",
        "published_by": "TEXT",
    },
    "site_pricing": {
        "plan": "TEXT",
        "price_display": "TEXT",
        "updated_at": "TEXT",
    },
}

for _table, _columns in EXTRA_COLUMNS.items():
    EXPECTED_SCHEMA_COLUMNS[_table].update(_columns)

PLAN_DAYS = {
    "month": 31,
    "quarter": 93,
    "half_year": 186,
    "year": 366,
    "permanent": None,
    "custom": "custom",
}

PLAN_LABELS = {
    "month": "月会员",
    "quarter": "季会员",
    "half_year": "半年会员",
    "year": "一年会员",
    "permanent": "永久会员",
    "custom": "自定义天数",
}

PRICING_PLANS = {
    "month": {"label": "月度", "period": "/ 月", "description": "适合短期项目与轻量使用"},
    "quarter": {"label": "季度", "period": "/ 季", "description": "适合持续运营与稳定产出"},
    "year": {"label": "年度", "period": "/ 年", "description": "适合长期、高频的视频工作流"},
    "permanent": {"label": "永久", "period": "一次付费", "description": "长期使用，无需周期续费"},
}

ADMIN_FRONTEND_BUILD = "admin-web-20261010-v030"
NO_STORE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_config()
    init_db()
    # Keep one idle connection for the process lifetime. This prevents SQLite
    # tearing down/recovering WAL files between otherwise short-lived requests.
    keeper = db()
    try:
        yield
    finally:
        keeper.close()


app = FastAPI(
    title="Video Mix Tool Membership Server",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@dataclass
class AdminSession:
    csrf_token: str
    expires_at: datetime


ADMIN_SESSIONS: dict[str, AdminSession] = {}
ADMIN_SESSIONS_LOCK = threading.Lock()
RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
RATE_LIMIT_LOCK = threading.Lock()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except Exception:
        return None


def seconds_until(value: str | None) -> int:
    deadline = parse_dt(value)
    if not deadline:
        return 0
    return max(0, int((deadline - now_utc()).total_seconds() + 0.999))


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", value.strip())
    if not match:
        raise ValueError("版本号必须使用 x.y.z 格式")
    return tuple(int(part) for part in match.groups())


def render_template(name: str, replacements: dict[str, str] | None = None) -> str:
    template_path = BASE_DIR / "templates" / name
    html = template_path.read_text(encoding="utf-8")
    for key, value in (replacements or {}).items():
        html = html.replace(f"__{key}__", value)
    return html


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/admin/assets/") and response.status_code in (200, 304):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif request.url.path.startswith("/admin") or request.url.path.startswith("/api/auth") or request.url.path == "/api/redeem":
        response.headers.setdefault("Cache-Control", "no-store")
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
    return response


def client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    if not RATE_LIMIT_ENABLED:
        return
    now = time.monotonic()
    with RATE_LIMIT_LOCK:
        bucket = RATE_LIMIT_BUCKETS[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
            raise HTTPException(429, f"请求过于频繁，请 {retry_after} 秒后重试", headers={"Retry-After": str(retry_after)})
        bucket.append(now)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_deadline() -> datetime:
    return now_utc() + timedelta(days=SESSION_TTL_DAYS)


def session_is_expired(user: dict[str, Any]) -> bool:
    expires_at = parse_dt(user.get("session_expires_at"))
    last_seen = parse_dt(user.get("session_last_seen_at"))
    if expires_at and expires_at <= now_utc():
        return True
    if last_seen and last_seen + timedelta(hours=SESSION_IDLE_HOURS) <= now_utc():
        return True
    return False


class DatabaseConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, factory=DatabaseConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def validate_config() -> None:
    if not IS_PRODUCTION:
        return
    errors = []
    if not ADMIN_USER:
        errors.append("ADMIN_USER must be set in production")
    if not ADMIN_PASSWORD:
        errors.append("ADMIN_PASSWORD must be set in production")
    elif len(ADMIN_PASSWORD) < 12:
        errors.append("ADMIN_PASSWORD must contain at least 12 characters in production")
    if not ADMIN_TOKEN_ENV or ADMIN_TOKEN_ENV in UNSAFE_ADMIN_TOKENS or len(ADMIN_TOKEN_ENV) < 32:
        errors.append("ADMIN_TOKEN must be set to a fixed strong random value in production")
    if not CORS_ALLOW_ORIGINS or "*" in CORS_ALLOW_ORIGINS:
        errors.append("CORS_ALLOW_ORIGINS must be an explicit origin list in production")
    if errors:
        raise RuntimeError("; ".join(errors))


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migration_applied(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM schema_migrations WHERE name=?", (name,)).fetchone()
    return row is not None


def mark_migration(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES(?, ?)",
        (name, now_iso()),
    )


def backup_database(reason: str) -> Path | None:
    if not DB_PATH.exists():
        return None
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y%m%d%H%M%S%f")
    backup_path = backup_dir / f"{DB_PATH.name}.{stamp}.{reason}.bak"
    # SQLite's online backup includes committed WAL pages and a consistent snapshot.
    with closing(sqlite3.connect(DB_PATH)) as source, closing(sqlite3.connect(backup_path)) as target:
        source.backup(target, pages=256)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
    return backup_path


def schema_needs_migration_backup() -> bool:
    if not DB_PATH.exists():
        return False
    with closing(sqlite3.connect(DB_PATH)) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if not {"schema_migrations", "admin_operations", "code_batches", "site_settings"}.issubset(tables):
            return True
        for table, columns in EXPECTED_SCHEMA_COLUMNS.items():
            if table not in tables:
                return True
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if any(column not in existing for column in columns):
                return True
    return False


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    if column in table_columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def create_base_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_member INTEGER NOT NULL DEFAULT 0,
            plan TEXT,
            member_expires_at TEXT,
            device_id TEXT,
            device_name TEXT,
            device_bound_at TEXT,
            device_rebind_cooldown_until TEXT,
            is_banned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            expires_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            plan TEXT NOT NULL,
            custom_days INTEGER,
            batch_id TEXT,
            expires_at TEXT,
            is_disabled INTEGER NOT NULL DEFAULT 0,
            disabled_at TEXT,
            used_by INTEGER,
            used_by_username_snapshot TEXT,
            used_at TEXT,
            created_at TEXT NOT NULL,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            detail TEXT,
            ip TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_releases (
            channel TEXT PRIMARY KEY,
            latest_version TEXT NOT NULL,
            minimum_version TEXT,
            title TEXT,
            notes TEXT,
            download_url TEXT,
            sha256 TEXT,
            is_mandatory INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_release_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            latest_version TEXT NOT NULL,
            minimum_version TEXT,
            title TEXT,
            notes TEXT,
            download_url TEXT,
            sha256 TEXT,
            is_mandatory INTEGER NOT NULL DEFAULT 0,
            published_at TEXT NOT NULL,
            published_by TEXT
        );

        CREATE TABLE IF NOT EXISTS site_pricing (
            plan TEXT PRIMARY KEY,
            price_display TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        """)


def run_migrations(conn: sqlite3.Connection) -> None:
    create_base_schema(conn)
    schema_changes = False

    mark_migration(conn, "000_ensure_schema_migrations")

    for table, columns in EXPECTED_SCHEMA_COLUMNS.items():
        for column, definition in columns.items():
            schema_changes = ensure_column(conn, table, column, definition) or schema_changes

    # 旧数据库可能缺少索引依赖的字段，必须先完成增量补列再创建索引。
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
        CREATE INDEX IF NOT EXISTS idx_users_device_id ON users(device_id);
        CREATE INDEX IF NOT EXISTS idx_redeem_codes_used_by ON redeem_codes(used_by);
        CREATE INDEX IF NOT EXISTS idx_redeem_codes_created_at ON redeem_codes(created_at);
        CREATE INDEX IF NOT EXISTS idx_redeem_codes_batch_id ON redeem_codes(batch_id);
        CREATE INDEX IF NOT EXISTS idx_redeem_codes_expires_at ON redeem_codes(expires_at);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_release_history_published_at ON app_release_history(published_at);
    """)

    now = now_iso()
    conn.execute("UPDATE users SET created_at=? WHERE created_at IS NULL OR created_at=''", (now,))
    conn.execute("UPDATE users SET updated_at=? WHERE updated_at IS NULL OR updated_at=''", (now,))
    conn.execute("UPDATE users SET is_member=0 WHERE is_member IS NULL")
    conn.execute("UPDATE users SET is_banned=0 WHERE is_banned IS NULL")
    conn.execute("UPDATE users SET device_bound_at=updated_at WHERE device_id IS NOT NULL AND (device_bound_at IS NULL OR device_bound_at='')")
    conn.execute("UPDATE sessions SET created_at=? WHERE created_at IS NULL OR created_at=''", (now,))
    conn.execute("UPDATE sessions SET last_seen_at=? WHERE last_seen_at IS NULL OR last_seen_at=''", (now,))
    conn.execute(
        "UPDATE sessions SET expires_at=? WHERE expires_at IS NULL OR expires_at=''",
        ((now_utc() + timedelta(days=SESSION_TTL_DAYS)).isoformat(),),
    )
    conn.execute("UPDATE redeem_codes SET created_at=? WHERE created_at IS NULL OR created_at=''", (now,))
    conn.execute("UPDATE redeem_codes SET batch_id='legacy' WHERE batch_id IS NULL OR batch_id=''")
    conn.execute("UPDATE redeem_codes SET is_disabled=0 WHERE is_disabled IS NULL")
    conn.execute(
        """
        INSERT OR IGNORE INTO app_releases(
            channel,latest_version,minimum_version,title,notes,download_url,sha256,is_mandatory,updated_at
        ) VALUES('stable',?,?,?,?,?,?,0,?)
        """,
        (APP_VERSION, LEGACY_CLIENT_VERSION, f"Video Mix Pro {APP_VERSION}", "", "", "", now),
    )
    for pricing_plan in PRICING_PLANS:
        conn.execute(
            "INSERT OR IGNORE INTO site_pricing(plan,price_display,updated_at) VALUES(?,?,?)",
            (pricing_plan, "", now),
        )

    if schema_changes and not migration_applied(conn, "001_additive_schema_backfill"):
        mark_migration(conn, "001_additive_schema_backfill")
    if not migration_applied(conn, "002_device_cooldown_and_releases"):
        mark_migration(conn, "002_device_cooldown_and_releases")
    if not migration_applied(conn, "003_operations_console"):
        mark_migration(conn, "003_operations_console")
    if not migration_applied(conn, "004_pricing_and_release_management"):
        mark_migration(conn, "004_pricing_and_release_management")


def init_db() -> None:
    if schema_needs_migration_backup():
        backup_database("pre_migration")
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        run_migrations(conn)
        migrate_admin(conn, now_iso())


def audit(conn: sqlite3.Connection, actor: str, action: str, target: str = "", detail: str = "", ip: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_logs(actor,action,target,detail,ip,created_at) VALUES(?,?,?,?,?,?)",
        (actor, action, target, detail[:1000], ip, now_iso()),
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        method, salt, digest = stored.split("$", 2)
        if method != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000).hex()
        return hmac.compare_digest(check, digest)
    except Exception:
        pass
    if len(stored) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored):
        check = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(check.lower(), stored.lower())
    return False


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def get_user_by_token(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    digest = token_digest(token)
    # Do not accept a stored digest through the plaintext compatibility branch.
    # Digest-shaped legacy bearer tokens must re-authenticate after this upgrade.
    legacy = token if not re.fullmatch(r"[0-9a-fA-F]{64}", token) else ""
    row = conn.execute("""
        SELECT u.*, s.device_id AS session_device_id,
               s.token AS session_token,
               s.last_seen_at AS session_last_seen_at,
               s.expires_at AS session_expires_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token IN (?, ?)
        LIMIT 1
    """, (digest, legacy)).fetchone()
    user = row_to_dict(row)
    if user:
        user["session_token_migrated"] = False
    if user and user.get("session_token") == token and token != digest:
        try:
            conn.execute("UPDATE sessions SET token=? WHERE token=?", (digest, token))
            user["session_token"] = digest
            user["session_token_migrated"] = True
        except sqlite3.IntegrityError:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    return user


def is_active_member(user: dict[str, Any]) -> bool:
    if not user or user.get("is_banned"):
        return False
    if not user.get("is_member"):
        return False
    if user.get("plan") == "permanent":
        return True
    expires = parse_dt(user.get("member_expires_at"))
    if not expires:
        return False
    return expires > now_utc()


def membership_payload(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "active": is_active_member(user),
        "username": user.get("username"),
        "plan": user.get("plan"),
        "plan_label": PLAN_LABELS.get(user.get("plan") or "", user.get("plan")),
        "expires_at": user.get("member_expires_at"),
        "device_id": user.get("device_id"),
        "device_name": user.get("device_name"),
        "device_bound_at": user.get("device_bound_at"),
        "device_rebind_cooldown_until": user.get("device_rebind_cooldown_until"),
        "device_rebind_remaining_seconds": seconds_until(user.get("device_rebind_cooldown_until")),
        "session_expires_at": user.get("session_expires_at"),
    }


def get_release(conn: sqlite3.Connection, channel: str = "stable") -> dict[str, Any]:
    row = conn.execute("SELECT * FROM app_releases WHERE channel=?", (channel,)).fetchone()
    release = row_to_dict(row)
    if release:
        return release
    return {
        "channel": channel,
        "latest_version": APP_VERSION,
        "minimum_version": LEGACY_CLIENT_VERSION,
        "title": f"Video Mix Pro {APP_VERSION}",
        "notes": "",
        "download_url": "",
        "sha256": "",
        "is_mandatory": 0,
        "updated_at": now_iso(),
    }


def release_payload(release: dict[str, Any], current_version: str | None = None) -> dict[str, Any]:
    latest = str(release.get("latest_version") or APP_VERSION)
    minimum = str(release.get("minimum_version") or latest)
    payload: dict[str, Any] = {
        "channel": release.get("channel") or "stable",
        "latest_version": latest,
        "minimum_version": minimum,
        "title": release.get("title") or f"Video Mix Pro {latest}",
        "notes": release.get("notes") or "",
        "download_url": release.get("download_url") or "",
        "sha256": release.get("sha256") or "",
        "is_mandatory": bool(release.get("is_mandatory")),
        "updated_at": release.get("updated_at") or "",
    }
    if current_version is not None:
        current = version_tuple(current_version)
        update_available = current < version_tuple(latest)
        payload.update(
            {
                "current_version": current_version,
                "update_available": update_available,
                "required": current < version_tuple(minimum) or (update_available and bool(release.get("is_mandatory"))),
            }
        )
    return payload


def enforce_supported_client(conn: sqlite3.Connection, app_version: str | None) -> None:
    current_version = str(app_version or LEGACY_CLIENT_VERSION).strip()
    if len(current_version) > 32:
        raise HTTPException(400, "客户端版本号长度超出限制")
    try:
        current = version_tuple(current_version)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    release = get_release(conn)
    minimum_version = str(release.get("minimum_version") or LEGACY_CLIENT_VERSION)
    if current >= version_tuple(minimum_version):
        return
    raise HTTPException(
        426,
        detail={
            "code": "CLIENT_UPDATE_REQUIRED",
            "message": f"当前版本 v{current_version} 已停止支持，请更新至 v{release.get('latest_version') or APP_VERSION}",
            "current_version": current_version,
            "minimum_version": minimum_version,
            "latest_version": str(release.get("latest_version") or APP_VERSION),
            "title": str(release.get("title") or ""),
            "download_url": str(release.get("download_url") or ""),
        },
    )


def pricing_payload(conn: sqlite3.Connection) -> list[dict[str, str]]:
    rows = {
        row["plan"]: str(row["price_display"] or "")
        for row in conn.execute("SELECT plan,price_display FROM site_pricing").fetchall()
    }
    return [
        {
            "plan": plan,
            "label": definition["label"],
            "period": definition["period"],
            "description": definition["description"],
            "price_display": rows.get(plan, ""),
        }
        for plan, definition in PRICING_PLANS.items()
    ]


def redeem_plan_days(redeem_code: dict[str, Any]) -> int | None:
    plan = redeem_code.get("plan")
    if plan == "custom":
        try:
            days = int(redeem_code.get("custom_days") or 0)
        except Exception:
            days = 0
        if days <= 0:
            raise HTTPException(400, "自定义天数兑换码无效")
        return days
    return PLAN_DAYS.get(plan)


def plan_label(plan: str | None, custom_days: int | None = None) -> str:
    if plan == "custom":
        return f"自定义 {custom_days or 0} 天"
    return PLAN_LABELS.get(plan or "", plan or "")


@app.get("/api/health")
def health():
    db_ok = False
    error = None
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception as exc:
        error = str(exc)
    status = "ok" if db_ok else "degraded"
    payload: dict[str, Any] = {
        "ok": db_ok,
        "status": status,
        "time": now_iso(),
        "app_version": APP_VERSION,
        "server_version": SERVER_VERSION,
    }
    if not IS_PRODUCTION:
        payload["database"] = {"ok": db_ok, "path": str(DB_PATH)}
        payload["environment"] = ENVIRONMENT
        if error:
            payload["database"]["error"] = error
    return JSONResponse(payload, status_code=200 if db_ok else 503)


@app.get("/api/update/latest")
def latest_update(channel: str = "stable"):
    if channel != "stable":
        raise HTTPException(404, "更新通道不存在")
    with db() as conn:
        payload = release_payload(get_release(conn, channel))
    return JSONResponse(payload, headers=NO_STORE_HEADERS)


@app.get("/api/site/pricing")
def site_pricing():
    with db() as conn:
        payload = {"items": pricing_payload(conn)}
    return JSONResponse(payload, headers=NO_STORE_HEADERS)


@app.get("/api/update/check")
def check_update(request: Request, current_version: str, channel: str = "stable", platform: str = "windows", arch: str = "x64"):
    check_rate_limit(f"update:{client_ip(request)}", 120, 60)
    if channel != "stable":
        raise HTTPException(404, "更新通道不存在")
    if platform.lower() != "windows" or arch.lower() not in {"x64", "x86_64"}:
        raise HTTPException(400, "当前仅提供 Windows x64 更新")
    try:
        version_tuple(current_version)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with db() as conn:
        return release_payload(get_release(conn, channel), current_version)


class RegisterReq(BaseModel):
    username: str
    password: str
    app_version: str | None = None


class LoginReq(BaseModel):
    username: str
    password: str
    device_id: str
    device_name: str | None = None
    app_version: str | None = None


class VerifyReq(BaseModel):
    token: str
    device_id: str
    app_version: str | None = None


class RedeemReq(BaseModel):
    token: str
    device_id: str
    code: str
    app_version: str | None = None


class LogoutReq(BaseModel):
    token: str
    device_id: str


@app.post("/api/auth/register")
def register(req: RegisterReq, request: Request):
    check_rate_limit(f"register:{client_ip(request)}", 10, 3600)
    username = req.username.strip()
    password = req.password.strip()
    if len(username) < 3:
        raise HTTPException(400, "账号至少 3 个字符")
    if len(password) < 6:
        raise HTTPException(400, "密码至少 6 个字符")
    if len(username) > 64 or len(password) > 256:
        raise HTTPException(400, "账号或密码长度超出限制")

    try:
        with db() as conn:
            enforce_supported_client(conn, req.app_version)
            conn.execute(
                "INSERT INTO users(username,password_hash,created_at,updated_at) VALUES(?,?,?,?)",
                (username, hash_password(password), now_iso(), now_iso()),
            )
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "账号已存在")


@app.post("/api/auth/login")
def login(req: LoginReq, request: Request):
    username = req.username.strip()
    ip = client_ip(request)
    check_rate_limit(f"login-ip:{ip}", 30, 300)
    check_rate_limit(f"login-user:{username.lower()}", 10, 300)
    if len(username) > 64 or len(req.password) > 256 or len(req.device_id) > 128 or len(req.device_name or "") > 128:
        raise HTTPException(400, "登录参数长度超出限制")
    with db() as conn:
        enforce_supported_client(conn, req.app_version)
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        user = row_to_dict(row)
        if not user:
            raise HTTPException(401, "账号或密码错误")
        stored_password = user.get("password_hash") or user.get("password") or user.get("password_sha256")
        if not verify_password(req.password, stored_password):
            raise HTTPException(401, "账号或密码错误")
        # Password hashing happens before the write lock; binding decisions happen
        # only after serializing and re-reading the latest account state.
        conn.execute("BEGIN IMMEDIATE")
        fresh = row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        if not fresh or fresh.get("password_hash") != user.get("password_hash"):
            raise HTTPException(409, "账号已变更，请重新登录")
        user = fresh
        if user.get("is_banned"):
            raise HTTPException(403, "账号已被封禁")

        if not str(stored_password).startswith("pbkdf2_sha256$"):
            conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (hash_password(req.password), now_iso(), user["id"]))

        now_dt = now_utc()
        now_value = now_dt.isoformat()
        previous_device = str(user.get("device_id") or "")
        requested_device = req.device_id.strip()
        if not requested_device:
            raise HTTPException(400, "设备标识不能为空")

        if previous_device and previous_device != requested_device:
            remaining = seconds_until(user.get("device_rebind_cooldown_until"))
            if remaining > 0:
                raise HTTPException(
                    423,
                    detail={
                        "code": "DEVICE_REBIND_COOLDOWN",
                        "message": "设备换绑冷却中，请稍后再试",
                        "remaining_seconds": remaining,
                        "cooldown_until": user.get("device_rebind_cooldown_until"),
                    },
                )
            cooldown_until = (now_dt + timedelta(hours=DEVICE_REBIND_COOLDOWN_HOURS)).isoformat()
            conn.execute(
                """
                UPDATE users
                SET device_id=?,device_name=?,device_bound_at=?,device_rebind_cooldown_until=?,updated_at=?
                WHERE id=?
                """,
                (requested_device, req.device_name or "", now_value, cooldown_until, now_value, user["id"]),
            )
            audit(
                conn,
                username,
                "device_rebind",
                username,
                f"from={previous_device}; to={requested_device}; cooldown_until={cooldown_until}",
                ip,
            )
        elif not previous_device:
            conn.execute(
                """
                UPDATE users
                SET device_id=?,device_name=?,device_bound_at=?,device_rebind_cooldown_until=NULL,updated_at=?
                WHERE id=?
                """,
                (requested_device, req.device_name or "", now_value, now_value, user["id"]),
            )
            audit(conn, username, "device_bind", username, requested_device, ip)
        else:
            conn.execute(
                "UPDATE users SET device_name=?,updated_at=? WHERE id=?",
                (req.device_name or "", now_value, user["id"]),
            )

        token = secrets.token_urlsafe(32)
        token_hash = token_digest(token)
        expires_at = session_deadline().isoformat()
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        conn.execute(
            "INSERT INTO sessions(token,user_id,device_id,created_at,last_seen_at,expires_at) VALUES(?,?,?,?,?,?)",
            (token_hash, user["id"], requested_device, now_value, now_value, expires_at),
        )
        audit(conn, username, "user_login", username, req.device_name or "", ip)
        row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        user = row_to_dict(row)
        user["session_expires_at"] = expires_at

    data = membership_payload(user)
    data["token"] = token
    return data


@app.post("/api/auth/verify")
def verify(req: VerifyReq, request: Request):
    check_rate_limit(f"verify:{client_ip(request)}", 120, 60)
    with db() as conn:
        enforce_supported_client(conn, req.app_version)
        user = get_user_by_token(conn, req.token)
        if not user:
            raise HTTPException(401, "登录已失效")
        if user.get("session_token_migrated"):
            conn.commit()
        if session_is_expired(user):
            conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (token_digest(req.token), req.token))
            conn.commit()
            raise HTTPException(401, "登录已过期，请重新登录")
        if user.get("is_banned"):
            raise HTTPException(403, "账号已被封禁")
        if user.get("device_id") != req.device_id:
            raise HTTPException(403, "账号已在其他设备登录，请重新登录刷新设备")
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE token IN (?, ?)", (now_iso(), token_digest(req.token), req.token))
        data = membership_payload(user)
        if not data["active"]:
            raise HTTPException(403, "会员已过期或未开通")
        return data


@app.post("/api/redeem")
def redeem(req: RedeemReq, request: Request):
    ip = client_ip(request)
    check_rate_limit(f"redeem:{ip}", 20, 60)
    code = req.code.strip().upper()
    if not code or len(code) > 64:
        raise HTTPException(400, "兑换码格式错误")
    with db() as conn:
        enforce_supported_client(conn, req.app_version)
        conn.execute("BEGIN IMMEDIATE")
        user = get_user_by_token(conn, req.token)
        if not user:
            raise HTTPException(401, "请先登录")
        if session_is_expired(user):
            conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (token_digest(req.token), req.token))
            conn.commit()
            raise HTTPException(401, "登录已过期，请重新登录")
        if user.get("is_banned"):
            raise HTTPException(403, "账号已被封禁")
        if user.get("device_id") != req.device_id:
            raise HTTPException(403, "账号已在其他设备登录，请重新登录刷新设备")

        code_row = conn.execute("SELECT * FROM redeem_codes WHERE code=?", (code,)).fetchone()
        rc = row_to_dict(code_row)
        if not rc:
            raise HTTPException(404, "兑换码不存在")
        if rc.get("used_by"):
            raise HTTPException(400, "兑换码已被使用")
        if rc.get("is_disabled"):
            raise HTTPException(400, "兑换码已被停用")
        code_expires = parse_dt(rc.get("expires_at"))
        if code_expires and code_expires <= now_utc():
            raise HTTPException(400, "兑换码已过期")

        plan = rc["plan"]
        days = redeem_plan_days(rc)
        if user.get("plan") == "permanent" and plan != "permanent" and is_active_member(user):
            data = membership_payload(user)
            data["message"] = "已是永久会员，无需兑换非永久会员码"
            data["code_consumed"] = False
            return data

        expires_at = None
        if days is None:
            expires_at = None
        else:
            current = parse_dt(user.get("member_expires_at")) if user.get("is_member") else None
            base = current if current and current > now_utc() else now_utc()
            expires_at = (base + timedelta(days=days)).isoformat()

        conn.execute(
            "UPDATE users SET is_member=1, plan=?, member_expires_at=?, updated_at=? WHERE id=?",
            (plan, expires_at, now_iso(), user["id"]),
        )
        consumed = conn.execute(
            "UPDATE redeem_codes SET used_by=?, used_at=?, used_by_username_snapshot=? WHERE code=? AND used_by IS NULL",
            (user["id"], now_iso(), user.get("username") or "", code),
        )
        if consumed.rowcount != 1:
            raise HTTPException(400, "兑换码已被使用")
        audit(conn, user.get("username") or "", "redeem", code,
              json.dumps({"before": {key: user.get(key) for key in ("is_member", "plan", "member_expires_at")},
                          "after": {"is_member": 1, "plan": plan, "member_expires_at": expires_at}}, ensure_ascii=False), ip)
        session_expires_at = user.get("session_expires_at")
        row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        user = row_to_dict(row)
        user["session_expires_at"] = session_expires_at

    data = membership_payload(user)
    data["message"] = "兑换成功"
    data["code_consumed"] = True
    return data


@app.post("/api/auth/logout")
def logout(req: LogoutReq, request: Request):
    check_rate_limit(f"logout:{client_ip(request)}", 30, 60)
    with db() as conn:
        user = get_user_by_token(conn, req.token)
        if user and user.get("device_id") == req.device_id:
            conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (token_digest(req.token), req.token))
            audit(conn, user.get("username") or "", "user_logout", user.get("username") or "", "", client_ip(request))
    return {"ok": True}


def admin_session_from_request(request: Request) -> tuple[str, AdminSession] | None:
    token = request.cookies.get("admin_session", "")
    if not token:
        return None
    with ADMIN_SESSIONS_LOCK:
        now = now_utc()
        expired = [key for key, value in ADMIN_SESSIONS.items() if value.expires_at <= now]
        for key in expired:
            ADMIN_SESSIONS.pop(key, None)
        session = ADMIN_SESSIONS.get(token)
    return (token, session) if session else None


def require_admin(request: Request, require_csrf: bool = False) -> AdminSession:
    current = admin_session_from_request(request)
    if not current:
        raise HTTPException(401, "admin required")
    _, session = current
    if require_csrf:
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
            raise HTTPException(403, "CSRF validation failed")
    return session


def admin_page(request: Request):
    current = admin_session_from_request(request)
    if not current:
        return HTMLResponse(
            render_template("admin-login.html", {"BUILD_ID": ADMIN_FRONTEND_BUILD}),
            headers=NO_STORE_HEADERS,
        )
    _, session = current
    return HTMLResponse(
        render_template(
            "admin.html",
            {"CSRF_TOKEN": session.csrf_token, "BUILD_ID": ADMIN_FRONTEND_BUILD},
        ),
        headers=NO_STORE_HEADERS,
    )


@app.post("/admin/login")
def admin_login(request: Request, data: dict):
    ip = client_ip(request)
    check_rate_limit(f"admin-login:{ip}", 5, 300)
    username_ok = hmac.compare_digest(str(data.get("username") or ""), ADMIN_USER)
    password_ok = hmac.compare_digest(str(data.get("password") or ""), ADMIN_PASSWORD)
    if username_ok and password_ok:
        session_token = secrets.token_urlsafe(32)
        session = AdminSession(
            csrf_token=secrets.token_urlsafe(24),
            expires_at=now_utc() + timedelta(hours=ADMIN_SESSION_HOURS),
        )
        with ADMIN_SESSIONS_LOCK:
            ADMIN_SESSIONS[session_token] = session
        with db() as conn:
            audit(conn, ADMIN_USER, "admin_login", ADMIN_USER, "", ip)
        response = JSONResponse({"ok": True, "expires_at": session.expires_at.isoformat()})
        response.set_cookie(
            "admin_session",
            session_token,
            httponly=True,
            secure=ADMIN_COOKIE_SECURE,
            samesite="strict",
            max_age=ADMIN_SESSION_HOURS * 3600,
            path="/admin",
        )
        return response
    raise HTTPException(401, "管理员账号或密码错误")


@app.post("/admin/logout")
def admin_logout(request: Request):
    require_admin(request, require_csrf=True)
    token = request.cookies.get("admin_session", "")
    with ADMIN_SESSIONS_LOCK:
        ADMIN_SESSIONS.pop(token, None)
    response = JSONResponse({"ok": True, "redirect_url": "/"})
    response.delete_cookie("admin_session", path="/admin")
    return response


def normalize_release_data(data: dict[str, Any]) -> dict[str, Any]:
    latest_version = str(data.get("latest_version") or "").strip()
    minimum_version = str(data.get("minimum_version") or latest_version).strip()
    title = str(data.get("title") or f"Video Mix Pro {latest_version}").strip()[:120]
    notes = str(data.get("notes") or "").strip()[:8000]
    download_url = str(data.get("download_url") or "").strip()
    sha256 = str(data.get("sha256") or "").strip().upper()
    is_mandatory = 1 if data.get("is_mandatory") else 0

    try:
        latest_tuple = version_tuple(latest_version)
        minimum_tuple = version_tuple(minimum_version)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if minimum_tuple > latest_tuple:
        raise HTTPException(400, "最低支持版本不能高于最新版")
    if download_url:
        parsed = urlparse(download_url)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            raise HTTPException(400, "下载链接必须是 HTTPS GitHub 直链")
        if "/releases/download/" not in parsed.path:
            raise HTTPException(400, "请填写 GitHub Releases 的直接下载链接")
    if sha256 and not re.fullmatch(r"[0-9A-F]{64}", sha256):
        raise HTTPException(400, "SHA-256 必须是 64 位十六进制字符串")
    return {
        "latest_version": latest_version,
        "minimum_version": minimum_version,
        "title": title,
        "notes": notes,
        "download_url": download_url,
        "sha256": sha256,
        "is_mandatory": is_mandatory,
    }


@app.put("/admin/api/release_history/{history_id}")
def update_release_history(history_id: int, request: Request, data: dict):
    require_admin(request, require_csrf=True)
    release_data = normalize_release_data(data)
    portable = normalize_release_data({**data, "download_url": data.get("portable_url", ""), "sha256": data.get("portable_sha256", "")})
    with db() as conn:
        existing = conn.execute("SELECT id,portable_url,portable_sha256 FROM app_release_history WHERE id=?", (history_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "历史版本不存在")
        if 'portable_url' not in data:
            portable['download_url'] = existing['portable_url']
        if 'portable_sha256' not in data:
            portable['sha256'] = existing['portable_sha256']
        conn.execute(
            """UPDATE app_release_history
               SET latest_version=?,minimum_version=?,title=?,notes=?,download_url=?,sha256=?,is_mandatory=?
               WHERE id=?""",
            (
                release_data["latest_version"], release_data["minimum_version"], release_data["title"],
                release_data["notes"], release_data["download_url"], release_data["sha256"],
                release_data["is_mandatory"], history_id,
            ),
        )
        conn.execute("UPDATE app_release_history SET portable_url=?,portable_sha256=? WHERE id=?",
                     (portable["download_url"], portable["sha256"], history_id))
        audit(conn, ADMIN_USER, "release_history_update", str(history_id), release_data["latest_version"], client_ip(request))
    return {"ok": True}


@app.delete("/admin/api/release_history/{history_id}")
def delete_release_history(history_id: int, request: Request):
    require_admin(request, require_csrf=True)
    with db() as conn:
        existing = conn.execute(
            "SELECT latest_version FROM app_release_history WHERE id=?", (history_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "历史版本不存在")
        conn.execute("DELETE FROM app_release_history WHERE id=?", (history_id,))
        audit(conn, ADMIN_USER, "release_history_delete", str(history_id), existing["latest_version"], client_ip(request))
    return {"ok": True}


@app.post("/admin/api/pricing")
def update_pricing(request: Request, data: dict):
    require_admin(request, require_csrf=True)
    prices = data.get("prices") or {}
    if not isinstance(prices, dict):
        raise HTTPException(400, "价格配置格式错误")
    normalized: dict[str, str] = {}
    for plan in PRICING_PLANS:
        value = str(prices.get(plan) or "").strip()
        if len(value) > 40:
            raise HTTPException(400, f"{PRICING_PLANS[plan]['label']}价格展示不能超过 40 个字符")
        normalized[plan] = value
    updated_at = now_iso()
    with db() as conn:
        for plan, value in normalized.items():
            conn.execute(
                """INSERT INTO site_pricing(plan,price_display,updated_at) VALUES(?,?,?)
                   ON CONFLICT(plan) DO UPDATE SET price_display=excluded.price_display,updated_at=excluded.updated_at""",
                (plan, value, updated_at),
            )
        audit(conn, ADMIN_USER, "pricing_update", "website", "; ".join(f"{key}={value}" for key, value in normalized.items()), client_ip(request))
        pricing = pricing_payload(conn)
    return {"ok": True, "pricing": pricing}


@app.post("/admin/api/cleanup_smoke")
def cleanup_smoke(request: Request, data: dict):
    require_admin(request, require_csrf=True)
    with db() as conn:
        smoke_users = [r["id"] for r in conn.execute("SELECT id FROM users WHERE username LIKE 'smoke_%'").fetchall()]
        if smoke_users:
            placeholders = ",".join("?" for _ in smoke_users)
            conn.execute(f"DELETE FROM sessions WHERE user_id IN ({placeholders})", smoke_users)
            conn.execute(f"DELETE FROM users WHERE id IN ({placeholders})", smoke_users)
        codes_deleted = conn.execute("DELETE FROM redeem_codes WHERE used_by IS NULL AND (note LIKE '%smoke%' OR note LIKE '%测试%')").rowcount
        audit(conn, ADMIN_USER, "cleanup_smoke", "smoke", f"users={len(smoke_users)}; codes={codes_deleted}", client_ip(request))
    return {"ok": True, "users_deleted": len(smoke_users), "codes_deleted": codes_deleted}


def user_action(request: Request, data: dict):
    """Compatibility adapter for password reset/deletion; membership is shared."""
    require_admin(request, require_csrf=True)
    try:
        user_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "用户 ID 格式错误")
    action = data.get("action")
    if action not in {"change_password", "delete_user"}:
        raise HTTPException(400, "未知账号操作")
    password_hash = None
    if action == "change_password":
        password = str(data.get("new_password") or "")
        if not 6 <= len(password) <= 256:
            raise HTTPException(400, "新密码长度需在 6 至 256 个字符之间")
        password_hash = hash_password(password)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        if action == "change_password":
            conn.execute("UPDATE users SET password_hash=?,updated_at=? WHERE id=?", (password_hash, now_iso(), user_id))
            detail = "password reset; sessions revoked"
        else:
            conn.execute("UPDATE redeem_codes SET used_by_username_snapshot=COALESCE(used_by_username_snapshot,?) WHERE used_by=?", (user["username"], user_id))
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            detail = json.dumps({"before": {"account": user["username"]}, "after": {"account": None}})
        audit(conn, ADMIN_USER, "user_" + action, user["username"], detail, client_ip(request))
    return {"ok": True}


from admin_routes import install as install_admin
install_admin(app, sys.modules[__name__])
