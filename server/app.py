# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import csv
import io
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
APP_VERSION = os.environ.get("APP_VERSION", "0.2.0").strip() or "0.2.0"
SERVER_VERSION = os.environ.get("SERVER_VERSION", "0.2.1").strip() or "0.2.1"
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
}

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

ADMIN_FRONTEND_BUILD = "admin-operations-20260807-v021"
NO_STORE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_config()
    init_db()
    yield


app = FastAPI(
    title="Video Mix Tool Membership Server",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
    lifespan=lifespan,
)

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
        return datetime.fromisoformat(value)
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
    if request.url.path.startswith("/admin") or request.url.path.startswith("/api/auth") or request.url.path == "/api/redeem":
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


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
    stamp = now_utc().strftime("%Y%m%d%H%M%S")
    backup_path = backup_dir / f"{DB_PATH.name}.{stamp}.{reason}.bak"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def schema_needs_migration_backup() -> bool:
    if not DB_PATH.exists():
        return False
    with sqlite3.connect(DB_PATH) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "schema_migrations" not in tables:
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
        (APP_VERSION, APP_VERSION, f"Video Mix Pro {APP_VERSION}", "", "", "", now),
    )

    if schema_changes and not migration_applied(conn, "001_additive_schema_backfill"):
        mark_migration(conn, "001_additive_schema_backfill")
    if not migration_applied(conn, "002_device_cooldown_and_releases"):
        mark_migration(conn, "002_device_cooldown_and_releases")
    if not migration_applied(conn, "003_operations_console"):
        mark_migration(conn, "003_operations_console")


def init_db() -> None:
    if schema_needs_migration_backup():
        backup_database("pre_migration")
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        run_migrations(conn)


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
    row = conn.execute("""
        SELECT u.*, s.device_id AS session_device_id,
               s.token AS session_token,
               s.last_seen_at AS session_last_seen_at,
               s.expires_at AS session_expires_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token IN (?, ?)
        LIMIT 1
    """, (digest, token)).fetchone()
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
        "minimum_version": APP_VERSION,
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
        payload.update(
            {
                "current_version": current_version,
                "update_available": current < version_tuple(latest),
                "required": current < version_tuple(minimum) or bool(release.get("is_mandatory")),
            }
        )
    return payload


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
        return release_payload(get_release(conn, channel))


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


class LoginReq(BaseModel):
    username: str
    password: str
    device_id: str
    device_name: str | None = None


class VerifyReq(BaseModel):
    token: str
    device_id: str


class RedeemReq(BaseModel):
    token: str
    device_id: str
    code: str


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
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        user = row_to_dict(row)
        if not user:
            raise HTTPException(401, "账号或密码错误")
        stored_password = user.get("password_hash") or user.get("password") or user.get("password_sha256")
        if not verify_password(req.password, stored_password):
            raise HTTPException(401, "账号或密码错误")
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
            current = parse_dt(user.get("member_expires_at"))
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
        audit(conn, user.get("username") or "", "redeem", code, plan, ip)
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


@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(
        render_template("site.html", {"APP_VERSION": APP_VERSION}),
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/admin", response_class=HTMLResponse)
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
async def admin_login(request: Request):
    ip = client_ip(request)
    check_rate_limit(f"admin-login:{ip}", 5, 300)
    data = await request.json()
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
    response = JSONResponse({"ok": True})
    response.delete_cookie("admin_session", path="/admin")
    return response


@app.get("/admin/api/summary")
def admin_summary(request: Request):
    require_admin(request)
    with db() as conn:
        release = release_payload(get_release(conn))
        release_history = [dict(r) for r in conn.execute(
            "SELECT * FROM app_release_history ORDER BY published_at DESC, id DESC LIMIT 20"
        ).fetchall()]
        current_time = now_iso()
        seven_days = (now_utc() + timedelta(days=7)).isoformat()
        today_prefix = now_utc().date().isoformat() + "%"
        metrics = {
            "users_total": conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"],
            "members_active": conn.execute(
                """SELECT COUNT(*) AS n FROM users
                   WHERE is_member=1 AND is_banned=0
                     AND (plan='permanent' OR member_expires_at>?)""",
                (current_time,),
            ).fetchone()["n"],
            "devices_cooling_down": conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE device_rebind_cooldown_until>?",
                (current_time,),
            ).fetchone()["n"],
            "codes_available": conn.execute(
                """SELECT COUNT(*) AS n FROM redeem_codes
                   WHERE used_by IS NULL AND is_disabled=0
                     AND (expires_at IS NULL OR expires_at='' OR expires_at>?)""",
                (current_time,),
            ).fetchone()["n"],
            "codes_disabled": conn.execute(
                "SELECT COUNT(*) AS n FROM redeem_codes WHERE used_by IS NULL AND is_disabled=1"
            ).fetchone()["n"],
            "codes_expired": conn.execute(
                "SELECT COUNT(*) AS n FROM redeem_codes WHERE used_by IS NULL AND expires_at IS NOT NULL AND expires_at!='' AND expires_at<=?",
                (current_time,),
            ).fetchone()["n"],
            "registrations_today": conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE created_at LIKE ?", (today_prefix,)
            ).fetchone()["n"],
            "redeemed_today": conn.execute(
                "SELECT COUNT(*) AS n FROM redeem_codes WHERE used_at LIKE ?", (today_prefix,)
            ).fetchone()["n"],
            "members_expiring_7d": conn.execute(
                """SELECT COUNT(*) AS n FROM users
                   WHERE is_member=1 AND is_banned=0 AND plan!='permanent'
                     AND member_expires_at>? AND member_expires_at<=?""",
                (current_time, seven_days),
            ).fetchone()["n"],
        }
        code_batches = [dict(r) for r in conn.execute(
            """SELECT batch_id,COUNT(*) AS total,
                      SUM(CASE WHEN used_by IS NULL THEN 1 ELSE 0 END) AS unused,
                      MIN(created_at) AS created_at,MAX(expires_at) AS expires_at,
                      MAX(note) AS note
               FROM redeem_codes GROUP BY batch_id ORDER BY created_at DESC LIMIT 100"""
        ).fetchall()]
    return {
        "plans": PLAN_LABELS,
        "release": release,
        "release_history": release_history,
        "metrics": metrics,
        "code_batches": code_batches,
        "device_rebind_cooldown_hours": DEVICE_REBIND_COOLDOWN_HOURS,
        "server_version": SERVER_VERSION,
    }


@app.get("/admin/api/users")
def admin_users(
    request: Request,
    q: str = "",
    status: str = "all",
    plan: str = "all",
    device: str = "all",
    page: int = 1,
    page_size: int = 50,
):
    require_admin(request)
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    where = []
    params: list[Any] = []
    current_time = now_iso()
    keyword = q.strip()
    if keyword:
        where.append("(username LIKE ? OR COALESCE(device_name,'') LIKE ? OR COALESCE(device_id,'') LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if status == "active":
        where.append("is_member=1 AND is_banned=0 AND (plan='permanent' OR member_expires_at>?)")
        params.append(current_time)
    elif status == "inactive":
        where.append("is_banned=0 AND (is_member=0 OR (plan!='permanent' AND (member_expires_at IS NULL OR member_expires_at<=?)))")
        params.append(current_time)
    elif status == "banned":
        where.append("is_banned=1")
    elif status == "expiring":
        where.append("is_member=1 AND is_banned=0 AND plan!='permanent' AND member_expires_at>? AND member_expires_at<=?")
        params.extend([current_time, (now_utc() + timedelta(days=7)).isoformat()])
    if plan != "all" and plan in PLAN_DAYS:
        where.append("plan=?")
        params.append(plan)
    if device == "bound":
        where.append("device_id IS NOT NULL AND device_id!=''")
    elif device == "unbound":
        where.append("(device_id IS NULL OR device_id='')")
    elif device == "cooldown":
        where.append("device_rebind_cooldown_until>?")
        params.append(current_time)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM users{where_sql}", params).fetchone()["n"]
        rows = [dict(r) for r in conn.execute(
            f"""SELECT id,username,is_member,plan,member_expires_at,device_id,device_name,
                       device_bound_at,device_rebind_cooldown_until,is_banned,created_at,updated_at
                FROM users{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()]
    for user in rows:
        user["device_rebind_remaining_seconds"] = seconds_until(user.get("device_rebind_cooldown_until"))
        user["active"] = is_active_member(user)
    return {"items": rows, "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}


@app.get("/admin/api/users/{user_id}")
def admin_user_detail(user_id: int, request: Request):
    require_admin(request)
    with db() as conn:
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        if not user:
            raise HTTPException(404, "用户不存在")
        redemptions = [dict(r) for r in conn.execute(
            """SELECT code,plan,custom_days,batch_id,used_at,note
               FROM redeem_codes WHERE used_by=? ORDER BY used_at DESC LIMIT 100""",
            (user_id,),
        ).fetchall()]
        timeline = [dict(r) for r in conn.execute(
            """SELECT actor,action,target,detail,ip,created_at FROM audit_logs
               WHERE target=? OR actor=? ORDER BY created_at DESC,id DESC LIMIT 100""",
            (user.get("username"), user.get("username")),
        ).fetchall()]
        sessions = conn.execute("SELECT COUNT(*) AS n FROM sessions WHERE user_id=?", (user_id,)).fetchone()["n"]
    user["device_rebind_remaining_seconds"] = seconds_until(user.get("device_rebind_cooldown_until"))
    user["active"] = is_active_member(user)
    return {"user": user, "redemptions": redemptions, "timeline": timeline, "active_sessions": sessions}


@app.get("/admin/api/codes")
def admin_codes(
    request: Request,
    q: str = "",
    status: str = "all",
    batch_id: str = "all",
    page: int = 1,
    page_size: int = 50,
):
    require_admin(request)
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    where = []
    params: list[Any] = []
    current_time = now_iso()
    if q.strip():
        like = f"%{q.strip()}%"
        where.append("(r.code LIKE ? OR COALESCE(r.used_by_username_snapshot,'') LIKE ? OR COALESCE(r.note,'') LIKE ?)")
        params.extend([like, like, like])
    if status == "available":
        where.append("r.used_by IS NULL AND r.is_disabled=0 AND (r.expires_at IS NULL OR r.expires_at='' OR r.expires_at>?)")
        params.append(current_time)
    elif status == "used":
        where.append("r.used_by IS NOT NULL")
    elif status == "disabled":
        where.append("r.used_by IS NULL AND r.is_disabled=1")
    elif status == "expired":
        where.append("r.used_by IS NULL AND r.expires_at IS NOT NULL AND r.expires_at!='' AND r.expires_at<=?")
        params.append(current_time)
    if batch_id != "all":
        where.append("r.batch_id=?")
        params.append(batch_id)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM redeem_codes r{where_sql}", params).fetchone()["n"]
        rows = [dict(r) for r in conn.execute(
            f"""SELECT r.code,r.plan,r.custom_days,r.batch_id,r.expires_at,r.is_disabled,r.disabled_at,
                       r.used_by,COALESCE(r.used_by_username_snapshot,u.username,'') AS used_by_username_snapshot,
                       r.used_at,r.created_at,r.note
                FROM redeem_codes r LEFT JOIN users u ON u.id=r.used_by
                {where_sql} ORDER BY r.created_at DESC LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()]
    return {"items": rows, "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}


@app.get("/admin/api/audit")
def admin_audit(request: Request, q: str = "", action: str = "all", page: int = 1, page_size: int = 50):
    require_admin(request)
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    where = []
    params: list[Any] = []
    if q.strip():
        like = f"%{q.strip()}%"
        where.append("(actor LIKE ? OR target LIKE ? OR detail LIKE ? OR ip LIKE ?)")
        params.extend([like, like, like, like])
    if action != "all":
        where.append("action=?")
        params.append(action)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM audit_logs{where_sql}", params).fetchone()["n"]
        rows = [dict(r) for r in conn.execute(
            f"SELECT id,actor,action,target,detail,ip,created_at FROM audit_logs{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()]
        actions = [r["action"] for r in conn.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action").fetchall()]
    return {"items": rows, "actions": actions, "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}


@app.post("/admin/api/release")
async def update_release(request: Request):
    require_admin(request, require_csrf=True)
    data = await request.json()
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

    updated_at = now_iso()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO app_releases(
                channel,latest_version,minimum_version,title,notes,download_url,sha256,is_mandatory,updated_at
            ) VALUES('stable',?,?,?,?,?,?,?,?)
            ON CONFLICT(channel) DO UPDATE SET
                latest_version=excluded.latest_version,
                minimum_version=excluded.minimum_version,
                title=excluded.title,
                notes=excluded.notes,
                download_url=excluded.download_url,
                sha256=excluded.sha256,
                is_mandatory=excluded.is_mandatory,
                updated_at=excluded.updated_at
            """,
            (latest_version, minimum_version, title, notes, download_url, sha256, is_mandatory, updated_at),
        )
        conn.execute(
            """INSERT INTO app_release_history(
                   channel,latest_version,minimum_version,title,notes,download_url,sha256,
                   is_mandatory,published_at,published_by
               ) VALUES('stable',?,?,?,?,?,?,?,?,?)""",
            (latest_version, minimum_version, title, notes, download_url, sha256, is_mandatory, updated_at, ADMIN_USER),
        )
        audit(
            conn,
            ADMIN_USER,
            "release_update",
            latest_version,
            f"minimum={minimum_version}; mandatory={is_mandatory}; url={download_url}",
            client_ip(request),
        )
        release = release_payload(get_release(conn))
    return {"ok": True, "release": release}


@app.post("/admin/api/create_codes")
async def create_codes(request: Request):
    require_admin(request, require_csrf=True)
    data = await request.json()
    plan = data.get("plan")
    try:
        count = max(1, min(int(data.get("count", 1)), 500))
    except Exception:
        raise HTTPException(400, "生成数量格式错误")
    note = str(data.get("note") or "")[:200]
    expires_at = str(data.get("expires_at") or "").strip() or None
    if expires_at:
        expires_dt = parse_dt(expires_at)
        if not expires_dt:
            raise HTTPException(400, "兑换码过期时间格式错误")
        if expires_dt <= now_utc():
            raise HTTPException(400, "兑换码过期时间必须晚于当前时间")
        expires_at = expires_dt.isoformat()
    custom_days = None
    if plan == "custom":
        custom_days = max(1, min(int(data.get("custom_days", 1)), 36500))
    if plan not in PLAN_DAYS:
        raise HTTPException(400, "会员类型错误")
    created = []
    batch_id = f"{now_utc().strftime('%Y%m%d-%H%M')}-{secrets.token_hex(3).upper()}"
    with db() as conn:
        for _ in range(count):
            for _attempt in range(5):
                code = secrets.token_urlsafe(12).replace("-", "").replace("_", "").upper()[:16]
                try:
                    conn.execute(
                        """INSERT INTO redeem_codes(
                               code,plan,custom_days,batch_id,expires_at,is_disabled,created_at,note
                           ) VALUES(?,?,?,?,?,0,?,?)""",
                        (code, plan, custom_days, batch_id, expires_at, now_iso(), note),
                    )
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise HTTPException(500, "兑换码生成冲突，请重试")
            created.append(code)
        audit(conn, ADMIN_USER, "create_codes", batch_id, f"plan={plan}; count={count}; expires_at={expires_at}; note={note}", client_ip(request))
    return {"created": created, "batch_id": batch_id, "expires_at": expires_at}


@app.post("/admin/api/code_action")
async def code_action(request: Request):
    require_admin(request, require_csrf=True)
    data = await request.json()
    action = str(data.get("action") or "")
    codes = [str(value).strip().upper() for value in (data.get("codes") or []) if str(value).strip()]
    batch_id = str(data.get("batch_id") or "").strip()
    if not codes and not batch_id:
        raise HTTPException(400, "请选择兑换码或批次")
    if len(codes) > 500:
        raise HTTPException(400, "单次最多操作 500 个兑换码")
    where = "batch_id=?" if batch_id else f"code IN ({','.join('?' for _ in codes)})"
    params: list[Any] = [batch_id] if batch_id else codes
    with db() as conn:
        matched = conn.execute(f"SELECT COUNT(*) AS n FROM redeem_codes WHERE {where}", params).fetchone()["n"]
        if action == "disable":
            affected = conn.execute(
                f"UPDATE redeem_codes SET is_disabled=1,disabled_at=? WHERE {where} AND used_by IS NULL",
                [now_iso(), *params],
            ).rowcount
        elif action == "enable":
            affected = conn.execute(
                f"UPDATE redeem_codes SET is_disabled=0,disabled_at=NULL WHERE {where} AND used_by IS NULL",
                params,
            ).rowcount
        elif action == "delete_unused":
            affected = conn.execute(
                f"DELETE FROM redeem_codes WHERE {where} AND used_by IS NULL",
                params,
            ).rowcount
        else:
            raise HTTPException(400, "未知兑换码操作")
        audit(
            conn,
            ADMIN_USER,
            f"code_{action}",
            batch_id or f"{len(codes)} codes",
            f"matched={matched}; affected={affected}",
            client_ip(request),
        )
    return {"ok": True, "matched": matched, "affected": affected}


@app.get("/admin/api/codes/export")
def export_codes(request: Request, status: str = "all", batch_id: str = "all"):
    require_admin(request)
    where = []
    params: list[Any] = []
    current_time = now_iso()
    if status == "available":
        where.append("used_by IS NULL AND is_disabled=0 AND (expires_at IS NULL OR expires_at='' OR expires_at>?)")
        params.append(current_time)
    elif status == "used":
        where.append("used_by IS NOT NULL")
    elif status == "disabled":
        where.append("used_by IS NULL AND is_disabled=1")
    elif status == "expired":
        where.append("used_by IS NULL AND expires_at IS NOT NULL AND expires_at!='' AND expires_at<=?")
        params.append(current_time)
    if batch_id != "all":
        where.append("batch_id=?")
        params.append(batch_id)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    with db() as conn:
        rows = conn.execute(
            f"""SELECT code,plan,custom_days,batch_id,expires_at,is_disabled,
                       used_by_username_snapshot,used_at,created_at,note
                FROM redeem_codes{where_sql} ORDER BY created_at DESC""",
            params,
        ).fetchall()
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["兑换码", "套餐", "自定义天数", "批次", "过期时间", "已停用", "使用账号", "使用时间", "创建时间", "备注"])
    for row in rows:
        writer.writerow(list(row))
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="video-mix-redeem-codes.csv"'},
    )


@app.post("/admin/api/cleanup_smoke")
async def cleanup_smoke(request: Request):
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


@app.post("/admin/api/user_action")
async def user_action(request: Request):
    require_admin(request, require_csrf=True)
    data = await request.json()
    user_id = int(data.get("user_id"))
    action = data.get("action")
    with db() as conn:
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        if not user:
            raise HTTPException(404, "用户不存在")

        if action == "revoke":
            conn.execute("UPDATE users SET is_member=0, plan=NULL, member_expires_at=NULL, updated_at=? WHERE id=?", (now_iso(), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        elif action == "ban":
            conn.execute("UPDATE users SET is_banned=1, updated_at=? WHERE id=?", (now_iso(), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        elif action == "unban":
            conn.execute("UPDATE users SET is_banned=0, updated_at=? WHERE id=?", (now_iso(), user_id))
        elif action == "reset_device":
            conn.execute(
                """
                UPDATE users
                SET device_id=NULL,device_name=NULL,device_bound_at=NULL,
                    device_rebind_cooldown_until=NULL,updated_at=?
                WHERE id=?
                """,
                (now_iso(), user_id),
            )
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        elif action == "reset_device_cooldown":
            conn.execute(
                "UPDATE users SET device_rebind_cooldown_until=NULL,updated_at=? WHERE id=?",
                (now_iso(), user_id),
            )
        elif action == "delete_user":
            conn.execute("UPDATE redeem_codes SET used_by_username_snapshot=COALESCE(used_by_username_snapshot, ?) WHERE used_by=?", (user.get("username") or "", user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        elif action in {"grant", "set_membership"}:
            plan = data.get("plan", "month")
            if plan not in PLAN_DAYS:
                raise HTTPException(400, "会员类型错误")
            days = PLAN_DAYS[plan]
            requested_expiry = str(data.get("expires_at") or "").strip()
            if days is None:
                expires_at = None
            elif requested_expiry:
                parsed_expiry = parse_dt(requested_expiry)
                if not parsed_expiry:
                    raise HTTPException(400, "会员到期时间格式错误")
                expires_at = parsed_expiry.isoformat()
            elif plan == "custom":
                try:
                    custom_days = max(1, min(int(data.get("custom_days", 1)), 36500))
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, "自定义会员天数格式错误") from exc
                expires_at = (now_utc() + timedelta(days=custom_days)).isoformat()
            else:
                expires_at = (now_utc() + timedelta(days=int(days))).isoformat()
            conn.execute("UPDATE users SET is_member=1, plan=?, member_expires_at=?, updated_at=? WHERE id=?", (plan, expires_at, now_iso(), user_id))
        else:
            raise HTTPException(400, "未知操作")
        audit(conn, ADMIN_USER, f"user_{action}", user.get("username") or str(user_id), str(data.get("plan") or ""), client_ip(request))
    return {"ok": True}


@app.post("/admin/api/user_batch_action")
async def user_batch_action(request: Request):
    require_admin(request, require_csrf=True)
    data = await request.json()
    try:
        user_ids = sorted({int(value) for value in (data.get("user_ids") or [])})
    except Exception as exc:
        raise HTTPException(400, "用户 ID 格式错误") from exc
    if not user_ids or len(user_ids) > 100:
        raise HTTPException(400, "请选择 1 至 100 个用户")
    action = str(data.get("action") or "")
    if action not in {"grant", "revoke", "ban", "unban", "reset_device_cooldown"}:
        raise HTTPException(400, "该操作不支持批量执行")
    plan = str(data.get("plan") or "month")
    if action == "grant" and plan not in PLAN_DAYS:
        raise HTTPException(400, "会员类型错误")
    custom_days = None
    if action == "grant" and plan == "custom":
        try:
            custom_days = max(1, min(int(data.get("custom_days", 1)), 36500))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "自定义会员天数格式错误") from exc
    placeholders = ",".join("?" for _ in user_ids)
    with db() as conn:
        existing = [dict(r) for r in conn.execute(
            f"SELECT id,username FROM users WHERE id IN ({placeholders})", user_ids
        ).fetchall()]
        affected_ids = [user["id"] for user in existing]
        if not affected_ids:
            raise HTTPException(404, "没有找到可操作的用户")
        affected_placeholders = ",".join("?" for _ in affected_ids)
        current = now_iso()
        if action == "grant":
            days = PLAN_DAYS[plan]
            if days is None:
                expires_at = None
            elif plan == "custom":
                expires_at = (now_utc() + timedelta(days=custom_days or 1)).isoformat()
            else:
                expires_at = (now_utc() + timedelta(days=int(days))).isoformat()
            conn.execute(
                f"UPDATE users SET is_member=1,plan=?,member_expires_at=?,updated_at=? WHERE id IN ({affected_placeholders})",
                [plan, expires_at, current, *affected_ids],
            )
        elif action == "revoke":
            conn.execute(
                f"UPDATE users SET is_member=0,plan=NULL,member_expires_at=NULL,updated_at=? WHERE id IN ({affected_placeholders})",
                [current, *affected_ids],
            )
            conn.execute(f"DELETE FROM sessions WHERE user_id IN ({affected_placeholders})", affected_ids)
        elif action == "ban":
            conn.execute(
                f"UPDATE users SET is_banned=1,updated_at=? WHERE id IN ({affected_placeholders})",
                [current, *affected_ids],
            )
            conn.execute(f"DELETE FROM sessions WHERE user_id IN ({affected_placeholders})", affected_ids)
        elif action == "unban":
            conn.execute(
                f"UPDATE users SET is_banned=0,updated_at=? WHERE id IN ({affected_placeholders})",
                [current, *affected_ids],
            )
        elif action == "reset_device_cooldown":
            conn.execute(
                f"UPDATE users SET device_rebind_cooldown_until=NULL,updated_at=? WHERE id IN ({affected_placeholders})",
                [current, *affected_ids],
            )
        audit(
            conn,
            ADMIN_USER,
            f"user_batch_{action}",
            f"{len(affected_ids)} users",
            f"ids={','.join(str(value) for value in affected_ids)}; plan={plan if action == 'grant' else ''}; custom_days={custom_days or ''}",
            client_ip(request),
        )
    return {"ok": True, "affected": len(affected_ids)}


BRAND_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Video Mix Pro</title><style>
body{margin:0;min-height:100vh;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#1f2937;background:#f9f8f6}
*{box-sizing:border-box}
.container{max-width:960px;margin:0 auto;padding:48px 24px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:64px}
.logo{font-size:20px;font-weight:700}
h1{font-size:42px;font-weight:700;margin:0 0 16px;line-height:1.2}
.subtitle{font-size:18px;color:#6b7280;margin:0 0 48px;line-height:1.6}
.features{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin-bottom:48px}
.feature{background:#fff;border:1px solid #e8e8e6;border-radius:12px;padding:24px}
.feature h3{font-size:16px;font-weight:600;margin:0 0 8px}
.feature p{font-size:14px;color:#6b7280;margin:0;line-height:1.6}
footer{text-align:center;color:#9ca3af;font-size:14px;padding:24px 0}
@media(max-width:768px){.features{grid-template-columns:1fr}}
</style></head><body>
<div class="container">
  <header>
    <div class="logo">Video Mix Pro</div>
  </header>
  <h1>智能批量视频混剪</h1>
  <p class="subtitle">自动化素材拼接、去重增强、GPU 编码加速，让视频批量生成更简单。</p>
  <div class="features">
    <div class="feature">
      <h3>批量生成</h3>
      <p>自定义素材组合，自动去重，支持指定数量批量输出。</p>
    </div>
    <div class="feature">
      <h3>素材结构</h3>
      <p>支持首视频、尾视频、插片、底栏叠加，灵活编排视频结构。</p>
    </div>
    <div class="feature">
      <h3>编码性能</h3>
      <p>支持 Intel QSV、NVIDIA NVENC、AMD AMF 硬件编码加速。</p>
    </div>
    <div class="feature">
      <h3>会员授权</h3>
      <p>兑换码开通会员，设备绑定，后台统一管理。</p>
    </div>
    <div class="feature">
      <h3>去重增强</h3>
      <p>重复组合自动调整速度、帧率、码率，降低重复率。</p>
    </div>
    <div class="feature">
      <h3>自动命名</h3>
      <p>自定义文件名规则，日期、字段、序号自动生成。</p>
    </div>
  </div>
  <footer>Video Mix Pro</footer>
</div>
</body></html>"""

ADMIN_LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Video Mix Pro 管理后台</title><style>
body{margin:0;min-height:100vh;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#1f2937;background:#f9f8f6;display:flex;align-items:center;justify-content:center;padding:24px}
*{box-sizing:border-box}
.card{background:#fff;border:1px solid #e8e8e6;border-radius:16px;padding:32px;width:100%;max-width:400px;box-shadow:0 4px 24px rgba(0,0,0,0.04)}
h1{margin:0 0 4px;font-size:22px;font-weight:600}p{margin:0 0 24px;color:#6b7280;font-size:14px}
label{display:block;font-size:13px;font-weight:500;color:#374151;margin-bottom:6px}
input{width:100%;height:40px;border:1px solid #e8e8e6;border-radius:8px;padding:0 12px;font-size:14px;outline:none;background:#fff;transition:border-color .15s}
input:focus{border-color:#5b6b7c}
button{width:100%;height:40px;border:0;border-radius:8px;background:#5b6b7c;color:#fff;font-weight:600;font-size:14px;cursor:pointer;margin-top:18px;transition:background .15s}
button:hover{background:#4a5866}
#msg{min-height:20px;margin-top:12px;color:#c07a7a;font-size:13px}
</style></head><body>
<div class="card"><h1>Video Mix Pro</h1><p>管理后台登录</p>
<label>账号</label><input id="u" placeholder="管理员账号" autocomplete="username">
<label>密码</label><input id="p" type="password" placeholder="管理员密码" autocomplete="current-password">
<button id="loginBtn">登录</button><div id="msg"></div></div>
<script>document.addEventListener('DOMContentLoaded',()=>{const $=id=>document.getElementById(id);async function login(){const msg=$('msg'),u=$('u'),p=$('p');msg.innerText='登录中...';try{const r=await fetch('/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({username:u.value,password:p.value})});if(r.ok){location.reload()}else{msg.innerText=await r.text()}}catch(e){msg.innerText='网络错误：'+e.message}}$('loginBtn').addEventListener('click',login);$('p').addEventListener('keydown',e=>{if(e.key==='Enter')login()})})</script>
</body></html>"""

ADMIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="__CSRF_TOKEN__"><title>Video Mix Pro 管理后台</title><style>
body{margin:0;background:#f9f8f6;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#1f2937;overflow:hidden}
*{box-sizing:border-box}
.layout{display:grid;grid-template-columns:220px 1fr;height:100vh}
.sidebar{background:#fff;border-right:1px solid #e8e8e6;padding:20px 14px}
.brand{font-size:20px;font-weight:700;margin:4px 10px 2px}
.brand-sub{color:#9ca3af;font-size:12px;margin:0 10px 20px}
.build-id{color:#c0c4cc;font-size:11px;margin:0 10px 16px;word-break:break-all}
.nav{display:grid;gap:2px}
.nav button{height:36px;text-align:left;border:0;border-radius:8px;background:transparent;color:#6b7280;font-weight:500;padding:0 12px;cursor:pointer;font-size:13px;transition:background .12s,color .12s}
.nav button:hover{background:#f5f5f3;color:#374151}
.nav button.active{background:#f3f5f7;color:#1f2937;font-weight:600}
.main{height:100vh;overflow:auto;padding:24px 28px}
.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}
.top-actions{display:flex;align-items:center;gap:8px}
.title h1{margin:0;font-size:24px;font-weight:600}.title p{margin:4px 0 0;color:#6b7280;font-size:14px}
.card{background:#fff;border:1px solid #e8e8e6;border-radius:12px;padding:20px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:16px}
.metric{background:#fff;border:1px solid #e8e8e6;border-radius:12px;padding:16px}
.metric span{color:#9ca3af;font-size:12px}.metric b{display:block;font-size:24px;margin-top:6px;font-weight:600}
h2{margin:0 0 14px;font-size:16px;font-weight:600}
button,select,input{height:34px;border-radius:6px;border:1px solid #e8e8e6;padding:0 10px;margin:2px;font-family:inherit;font-size:13px}
button{background:#5b6b7c;color:#fff;border:0;font-weight:600;cursor:pointer;transition:background .12s}
button:hover{background:#4a5866}
button.danger{background:#c07a7a}button.gray{background:#9ca3af}button.green{background:#6b9e8a}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.search{min-width:280px}
.page{display:none}.page.active{display:block}
table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;overflow:hidden;border-radius:10px;border:1px solid #e8e8e6}
td,th{border-bottom:1px solid #f0efed;padding:10px;text-align:left;font-size:13px;vertical-align:top}
th{background:#f9f8f6;color:#6b7280;font-size:12px;font-weight:600}
tr:last-child td{border-bottom:0}
code{background:#f5f5f3;padding:2px 6px;border-radius:4px;font-family:Consolas,monospace;font-size:12px}
textarea{width:100%;height:120px;border-radius:8px;border:1px solid #e8e8e6;padding:10px;font-family:Consolas,monospace;font-size:13px}
.badge{display:inline-flex;align-items:center;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:600}
.ok{background:#f0f7f4;color:#6b9e8a}.no{background:#fdf2f2;color:#c07a7a}.wait{background:#fdf6ed;color:#d4a056}
.empty{padding:24px;text-align:center;color:#9ca3af;border:1px dashed #e8e8e6;border-radius:10px;background:#fafafa}
.admin-error{display:none;margin:0 0 16px;padding:12px 14px;border:1px solid #f0c4c4;border-radius:8px;background:#fff4f4;color:#9f3a3a;font-size:13px;white-space:pre-wrap}
.toast{position:fixed;right:16px;bottom:16px;background:#1f2937;color:#fff;border-radius:8px;padding:10px 14px;font-size:13px;box-shadow:0 4px 24px rgba(0,0,0,0.08);display:none}
@media(max-width:980px){body{overflow:auto}.layout{grid-template-columns:1fr;height:auto}.sidebar{height:auto}.main{height:auto}.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<div class="layout">
  <aside class="sidebar">
    <div class="brand">Video Mix</div>
    <div class="brand-sub">会员管理后台</div>
    <div class="build-id">Admin UI build: admin-js-es5-20260627-members</div>
    <div class="nav">
      <button class="active" data-page="dashboard">数据概览</button>
      <button data-page="codesCreate">兑换码生成</button>
      <button data-page="usersPage">用户管理</button>
      <button data-page="codesPage">兑换记录</button>
    </div>
  </aside>
  <main class="main">
    <div class="topbar">
      <div class="title">
        <h1 id="pageTitle">数据概览</h1>
        <p id="pageSub">会员、兑换码、封禁状态总览</p>
      </div>
      <div class="top-actions"><button class="gray" id="refreshBtn">刷新</button><button class="danger" id="logoutBtn">退出</button></div>
    </div>
    <div id="adminError" class="admin-error"></div>
    <section id="dashboard" class="page active">
      <div class="grid">
        <div class="metric"><span>总用户</span><b id="mUsers">-</b></div>
        <div class="metric"><span>有效会员</span><b id="mMembers">-</b></div>
        <div class="metric"><span>未使用兑换码</span><b id="mCodes">-</b></div>
        <div class="metric"><span>封禁账号</span><b id="mBanned">-</b></div>
      </div>
    </section>
    <section id="codesCreate" class="page">
      <div class="card">
        <h2>生成兑换码</h2>
        <div class="toolbar">
          <select id="plan"><option value="month">月会员</option><option value="quarter">季会员</option><option value="half_year">半年会员</option><option value="year">一年会员</option><option value="permanent">永久会员</option><option value="custom">自定义天数</option></select>
          <input id="customDays" type="number" value="7" min="1" max="36500" placeholder="自定义天数" style="display:none;width:120px">
          <input id="count" type="number" value="10" min="1" max="500">
          <input id="note" placeholder="备注">
          <button id="createCodesBtn">生成</button>
          <button class="gray" id="copyCodesBtn">复制</button>
          <button class="danger" id="cleanupSmokeBtn">清理测试数据</button>
        </div>
        <textarea id="newCodes" placeholder="新生成的兑换码"></textarea>
      </div>
    </section>
    <section id="usersPage" class="page">
      <div class="card">
        <h2>用户管理</h2>
        <div class="toolbar">
          <input class="search" id="userSearch" placeholder="搜索账号 / 设备 / 会员类型">
          <button class="gray" id="refreshUsersBtn">刷新</button>
        </div>
        <div id="users"></div>
      </div>
    </section>
    <section id="codesPage" class="page">
      <div class="card">
        <h2>兑换码记录</h2>
        <div class="toolbar">
          <input class="search" id="codeSearch" placeholder="搜索兑换码 / 备注 / 类型">
        </div>
        <div id="codes"></div>
      </div>
    </section>
  </main>
</div>
<div id="toast" class="toast"></div>
<script>
window.onerror=function(message,source,line,column,error){
  var box=document.getElementById('adminError');
  var nl=String.fromCharCode(10);
  var text='Admin UI build: admin-js-es5-20260627-members'+nl+'JS error: '+message+nl+'at: '+line+':'+column;
  if(box){box.style.display='block';box.innerText=text;}
  return false;
};
</script>
<script>
document.addEventListener('DOMContentLoaded',function(){
  var BUILD='admin-js-es5-20260627-members';
  var plans={month:'月会员',quarter:'季会员',half_year:'半年会员',year:'一年会员',permanent:'永久会员'};
  var pageInfo={dashboard:['数据概览','会员、兑换码、封禁状态总览'],codesCreate:['兑换码生成','批量生成兑换码'],usersPage:['用户管理','开通、撤销、封禁、重置设备'],codesPage:['兑换记录','查看兑换码使用状态']};
  var state={users:[],codes:[]};
  var csrf=(document.querySelector('meta[name="csrf-token"]')||{}).content||'';
  function el(id){return document.getElementById(id)}
  function text(id,value){var node=el(id);if(node){node.innerText=String(value)}}
  function clear(node){while(node&&node.firstChild){node.removeChild(node.firstChild)}}
  function divStatus(id,value){var node=el(id);if(!node){return}clear(node);var d=document.createElement('div');d.className='empty';d.appendChild(document.createTextNode(value));node.appendChild(d)}
  function td(value){var node=document.createElement('td');node.appendChild(document.createTextNode(value==null?'':String(value)));return node}
  function spanBadge(textValue,cls){var node=document.createElement('span');node.className='badge '+cls;node.appendChild(document.createTextNode(textValue));return node}
  function button(label,cls,attrs){var node=document.createElement('button');if(cls){node.className=cls}node.appendChild(document.createTextNode(label));for(var key in attrs){if(attrs.hasOwnProperty(key)){node.setAttribute(key,attrs[key])}}return node}
  function toast(value){var node=el('toast');if(!node){return}node.innerText=value;node.style.display='block';window.clearTimeout(toast.timer);toast.timer=window.setTimeout(function(){node.style.display='none'},6000)}
  function showError(value){var box=el('adminError');if(box){box.style.display='block';box.innerText='Admin UI build: '+BUILD+String.fromCharCode(10)+value}toast(value)}
  function showPage(id,button){var pages=document.querySelectorAll('.page');for(var i=0;i<pages.length;i++){pages[i].classList.remove('active')}var page=el(id);if(page){page.classList.add('active')}var buttons=document.querySelectorAll('.nav button');for(var j=0;j<buttons.length;j++){buttons[j].classList.remove('active')}if(button){button.classList.add('active')}if(pageInfo[id]){text('pageTitle',pageInfo[id][0]);text('pageSub',pageInfo[id][1])}}
  function request(path,data,ok,fail){var xhr=new XMLHttpRequest();xhr.open(data?'POST':'GET',path,true);xhr.withCredentials=true;xhr.onreadystatechange=function(){if(xhr.readyState!==4){return}var body=xhr.responseText||'';var parsed=null;try{parsed=body?JSON.parse(body):{}}catch(e){parsed=body}if(xhr.status>=200&&xhr.status<300){ok(parsed)}else{var msg=typeof parsed==='string'?parsed:(parsed.detail||parsed.message||body||('HTTP '+xhr.status));fail(new Error(msg))}};xhr.onerror=function(){fail(new Error('网络错误'))};if(data){xhr.setRequestHeader('Content-Type','application/json');xhr.setRequestHeader('X-CSRF-Token',csrf);xhr.send(JSON.stringify(data))}else{xhr.send()}}
  function memberActive(user){if(!user||!user.is_member){return false}if(user.plan==='permanent'){return true}if(!user.member_expires_at){return false}return new Date(user.member_expires_at)>new Date()}
  function fmt(value){if(!value){return ''}try{return new Date(value).toLocaleString()}catch(e){return value}}
  function codeLabel(code){if(code.plan==='custom'){return '自定义 '+(code.custom_days||0)+' 天'}return plans[code.plan]||code.plan||''}
  function toggleCustomDays(){var node=el('customDays');if(node){node.style.display=el('plan').value==='custom'?'inline-block':'none'}}
  function load(){text('mUsers','loading');text('mMembers','loading');text('mCodes','loading');text('mBanned','loading');divStatus('users','加载中...');divStatus('codes','加载中...');request('/admin/api/summary',null,function(data){var box=el('adminError');if(box){box.style.display='none';box.innerText=''}state.users=data&&data.users?data.users:[];state.codes=data&&data.codes?data.codes:[];var active=0,banned=0,unused=0;for(var i=0;i<state.users.length;i++){if(memberActive(state.users[i])){active++}if(state.users[i].is_banned){banned++}}for(var j=0;j<state.codes.length;j++){if(!state.codes[j].used_by){unused++}}text('mUsers',state.users.length);text('mMembers',active);text('mCodes',unused);text('mBanned',banned);renderUsers();renderCodes();toast('后台数据已加载 '+BUILD)},function(err){text('mUsers','ERR');text('mMembers','ERR');text('mCodes','ERR');text('mBanned','ERR');divStatus('users','加载失败：'+err.message);divStatus('codes','加载失败：'+err.message);showError('加载失败：'+err.message)})}
  function makeTable(headers){var table=document.createElement('table');var tr=document.createElement('tr');for(var i=0;i<headers.length;i++){var th=document.createElement('th');th.appendChild(document.createTextNode(headers[i]));tr.appendChild(th)}table.appendChild(tr);return table}
  function renderUsers(){var box=el('users');if(!box){return}clear(box);var q=(el('userSearch').value||'').toLowerCase();var table=makeTable(['ID','账号','会员','设备','状态','操作']);var count=0;for(var i=0;i<state.users.length;i++){var user=state.users[i];if(JSON.stringify(user).toLowerCase().indexOf(q)<0){continue}count++;var tr=document.createElement('tr');tr.appendChild(td(user.id));var account=td('');var b=document.createElement('b');b.appendChild(document.createTextNode(user.username||''));account.appendChild(b);account.appendChild(document.createElement('br'));account.appendChild(document.createTextNode(fmt(user.created_at)));tr.appendChild(account);var member=td('');member.appendChild(memberActive(user)?spanBadge(plans[user.plan]||user.plan,'ok'):spanBadge('非会员','no'));member.appendChild(document.createElement('br'));member.appendChild(document.createTextNode(user.plan==='permanent'?'永久':fmt(user.member_expires_at)));tr.appendChild(member);tr.appendChild(td(user.device_name||'未绑定'));var status=td('');status.appendChild(user.is_banned?spanBadge('封禁','no'):spanBadge('正常','ok'));tr.appendChild(status);var ops=td('');var opsList=[['月','grant','month',''],['季','grant','quarter',''],['半年','grant','half_year',''],['年','grant','year',''],['永久','grant','permanent','green'],['撤销','revoke','','danger'],['重置','reset_device','','gray'],['封禁','ban','','danger'],['解封','unban','','gray'],['删除','delete_user','','danger']];for(var k=0;k<opsList.length;k++){ops.appendChild(button(opsList[k][0],opsList[k][3],{'data-action':opsList[k][1],'data-plan':opsList[k][2],'data-user-id':user.id,'data-username':user.username||''}))}tr.appendChild(ops);table.appendChild(tr)}if(count){box.appendChild(table)}else{divStatus('users','暂无用户')}}
  function renderCodes(){var box=el('codes');if(!box){return}clear(box);var q=(el('codeSearch').value||'').toLowerCase();var table=makeTable(['兑换码','套餐','状态','使用账号','使用时间','创建时间','备注']);var count=0;for(var i=0;i<state.codes.length;i++){var code=state.codes[i];if(JSON.stringify(code).toLowerCase().indexOf(q)<0){continue}count++;var tr=document.createElement('tr');tr.appendChild(td(code.code));tr.appendChild(td(codeLabel(code)));var st=td('');st.appendChild(code.used_by?spanBadge('已使用','no'):spanBadge('未使用','ok'));tr.appendChild(st);tr.appendChild(td(code.used_by_username_snapshot||code.used_by||''));tr.appendChild(td(fmt(code.used_at)));tr.appendChild(td(fmt(code.created_at)));tr.appendChild(td(code.note||''));table.appendChild(tr)}if(count){box.appendChild(table)}else{divStatus('codes','暂无兑换码')}}
  function createCodes(){var payload={plan:el('plan').value,count:el('count').value,note:el('note').value};if(payload.plan==='custom'){payload.custom_days=el('customDays').value}request('/admin/api/create_codes',payload,function(data){el('newCodes').value=(data.created||[]).join('\\n');toast('已生成');load()},function(err){showError('生成失败：'+err.message)})}
  function confirmAction(action,name){if(action==='delete_user'){return window.confirm('确定彻底删除用户 '+name+' 吗？此操作不可恢复。')}if(action==='ban'){return window.confirm('确定封禁用户 '+name+' 吗？')}if(action==='revoke'){return window.confirm('确定撤销用户 '+name+' 的会员吗？')}if(action==='reset_device'){return window.confirm('确定重置用户 '+name+' 的设备绑定吗？')}return true}
  function userAction(button){var action=button.getAttribute('data-action');var name=button.getAttribute('data-username')||'';if(!confirmAction(action,name)){return}request('/admin/api/user_action',{user_id:Number(button.getAttribute('data-user-id')),action:action,plan:button.getAttribute('data-plan')||null},function(){toast('操作成功');load()},function(err){showError('操作失败：'+err.message)})}
  function cleanupSmoke(){if(!window.confirm('确定清理 smoke_ 测试账号和未使用测试兑换码吗？')){return}request('/admin/api/cleanup_smoke',{},function(data){toast('已清理测试数据 用户 '+(data.users_deleted||0)+' 个，兑换码 '+(data.codes_deleted||0)+' 个');load()},function(err){showError('清理失败：'+err.message)})}
  function logout(){request('/admin/logout',{},function(){window.location.reload()},function(err){showError('退出失败：'+err.message)})}
  function bind(id,event,handler){var node=el(id);if(node){node.addEventListener(event,handler)}}
  var nav=document.querySelector('.nav');if(nav){nav.addEventListener('click',function(event){var target=event.target;while(target&&target!==nav&&!(target.tagName==='BUTTON'&&target.getAttribute('data-page'))){target=target.parentNode}if(target&&target.getAttribute('data-page')){showPage(target.getAttribute('data-page'),target)}})}
  var users=el('users');if(users){users.addEventListener('click',function(event){var target=event.target;while(target&&target!==users&&!(target.tagName==='BUTTON'&&target.getAttribute('data-action'))){target=target.parentNode}if(target&&target.getAttribute('data-action')){userAction(target)}})}
  bind('refreshBtn','click',load);bind('logoutBtn','click',logout);bind('refreshUsersBtn','click',load);bind('createCodesBtn','click',createCodes);bind('cleanupSmokeBtn','click',cleanupSmoke);bind('plan','change',toggleCustomDays);bind('copyCodesBtn','click',function(){var box=el('newCodes');box.focus();box.select();try{document.execCommand('copy');toast('已复制')}catch(e){toast('请手动复制')}});bind('userSearch','input',renderUsers);bind('codeSearch','input',renderCodes);
  showPage('dashboard',document.querySelector('.nav button[data-page="dashboard"]'));
  toggleCustomDays();
  divStatus('users','Admin UI build: '+BUILD+'，正在初始化...');
  divStatus('codes','Admin UI build: '+BUILD+'，正在初始化...');
  load();
});
</script></body></html>"""
