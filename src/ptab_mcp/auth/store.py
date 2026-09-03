"""Registered-user list + OAuth authorization-server state (SQLite).

mcp_users is the authorization source of truth for the dual-IdP login flow:
the upstream IdP (Google / Entra ID) proves WHO the caller is; an active row
here decides WHETHER they may connect and, via role, whether they get the
ptab:admin scope (the user-management tool). Rows are managed by the
admin-gated `ptab_manage_users` MCP tool or scripts/manage_mcp_users.py.

The three oauth_* tables persist the authorization-server state that must
survive restarts: dynamically registered MCP clients (RFC 7591), single-use
authorization codes, and rotating refresh tokens. Codes and refresh tokens are
stored as SHA-256 hashes only.

Backend is a single SQLite file (PTAB_AUTH_DB_PATH, default
``data/mcp_auth.db``) — zero-infrastructure for self-hosters. WAL mode +
busy_timeout are enabled so the same file can be shared by several MCP
containers on ONE host (PTAB mounts the shared paid-tier file PFW hosts); a network
filesystem is NOT safe for this. Connections are opened per operation — auth
traffic is a handful of queries per login/refresh, and per-call connections
keep multi-process sharing robust.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

UTC = timezone.utc

log = logging.getLogger(__name__)


def _retention_days(env_name: str, default: int) -> int:
    """Retention window in days; 0 disables the sweep."""
    try:
        return max(0, int(os.getenv(env_name, str(default))))
    except ValueError:
        log.warning("Invalid %s, using default %d", env_name, default)
        return default


#: admin_audit_log holds FULL unmasked identities and was append-only with no
#: retention target at all, while the masked copy in the rotating logs had one
#: (PT-10). Set PTAB_AUDIT_RETENTION_DAYS=0 to keep everything (e.g. when an
#: external archiver owns retention).
_AUDIT_RETENTION_DAYS = _retention_days("PTAB_AUDIT_RETENTION_DAYS", 365)

#: oauth_clients grows with every anonymous dynamic registration and had no
#: eviction (PT-09). Rows are only dropped when no live refresh token points at
#: them, so a connector in use is never evicted.
_CLIENT_RETENTION_DAYS = _retention_days("PTAB_CLIENT_RETENTION_DAYS", 90)

VALID_ROLES = ("user", "admin")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_users (
    email          TEXT PRIMARY KEY,
    display_name   TEXT,
    role           TEXT NOT NULL DEFAULT 'user',
    active         INTEGER NOT NULL DEFAULT 1,
    added_at       TEXT NOT NULL,
    last_login_at  TEXT,
    last_login_idp TEXT,
    notes          TEXT
);
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id  TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash  TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    client_id  TEXT NOT NULL,
    email      TEXT NOT NULL,
    scopes     TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_refresh_email ON oauth_refresh_tokens (email);
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    target    TEXT,
    role      TEXT,
    success   INTEGER NOT NULL DEFAULT 1,
    detail    TEXT
);
"""


def token_hash(token: str) -> str:
    """SHA-256 hex of a code/refresh token — the only form that hits disk."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    """Canonical stored timestamp form — lexicographically comparable."""
    return dt.astimezone(UTC).isoformat()


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


class McpUserStore:
    """Registered users + OAuth AS state in one SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    @asynccontextmanager
    async def _db(self) -> AsyncIterator[aiosqlite.Connection]:
        if not self._schema_ready:
            async with self._schema_lock:
                if not self._schema_ready:
                    self._db_path.parent.mkdir(parents=True, exist_ok=True)
                    async with aiosqlite.connect(self._db_path) as db:
                        await db.execute("PRAGMA journal_mode=WAL")
                        await db.execute("PRAGMA busy_timeout=5000")
                        await db.executescript(_SCHEMA)
                        await db.commit()
                    # Owner-only perms on the auth DB + WAL/SHM sidecars
                    # (M-1, CWE-732) — sqlite creates them world-readable.
                    from ..util.database import restrict_db_file_permissions
                    restrict_db_file_permissions(str(self._db_path))
                    self._schema_ready = True
        db = await aiosqlite.connect(self._db_path)
        try:
            # 5s (vs the link cache's 30s) is deliberate (RF-5): auth queries
            # sit on the interactive login/refresh path, where failing fast
            # beats a browser spinner — a lock held >5s on this shared-file
            # DB means something is already wrong.
            await db.execute("PRAGMA busy_timeout=5000")
            db.row_factory = aiosqlite.Row
            yield db
        finally:
            await db.close()

    # ------------------------------------------------------------------ users

    async def get_user(self, email: str) -> dict[str, Any] | None:
        async with self._db() as db:
            cur = await db.execute(
                "SELECT email, display_name, role, active, added_at, "
                "last_login_at, last_login_idp, notes "
                "FROM mcp_users WHERE email = ?",
                (email.strip().lower(),),
            )
            row = await cur.fetchone()
        return self._user_dict(row) if row else None

    async def upsert_user(
        self,
        email: str,
        *,
        role: str = "user",
        display_name: str | None = None,
        active: bool = True,
        notes: str | None = None,
    ) -> None:
        if role not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}, got {role!r}")
        async with self._db() as db:
            await db.execute(
                "INSERT INTO mcp_users (email, display_name, role, active, added_at, notes) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (email) DO UPDATE SET "
                "display_name = COALESCE(excluded.display_name, mcp_users.display_name), "
                "role = excluded.role, active = excluded.active, "
                "notes = COALESCE(excluded.notes, mcp_users.notes)",
                (
                    email.strip().lower(),
                    display_name,
                    role,
                    int(active),
                    _iso(_now()),
                    notes,
                ),
            )
            await db.commit()

    async def set_active(self, email: str, active: bool) -> bool:
        async with self._db() as db:
            cur = await db.execute(
                "UPDATE mcp_users SET active = ? WHERE email = ?",
                (int(active), email.strip().lower()),
            )
            await db.commit()
        return cur.rowcount == 1

    async def record_login(self, email: str, idp: str) -> None:
        async with self._db() as db:
            await db.execute(
                "UPDATE mcp_users SET last_login_at = ?, last_login_idp = ? "
                "WHERE email = ?",
                (_iso(_now()), idp, email.strip().lower()),
            )
            await db.commit()

    async def list_users(self) -> list[dict[str, Any]]:
        async with self._db() as db:
            cur = await db.execute(
                "SELECT email, display_name, role, active, added_at, "
                "last_login_at, last_login_idp, notes "
                "FROM mcp_users ORDER BY added_at"
            )
            rows = await cur.fetchall()
        return [self._user_dict(r) for r in rows]

    @staticmethod
    def _user_dict(row: aiosqlite.Row) -> dict[str, Any]:
        d = dict(row)
        d["active"] = bool(d["active"])
        d["added_at"] = _parse(d["added_at"])
        d["last_login_at"] = _parse(d["last_login_at"])
        return d

    # -------------------------------------------------------- admin audit log

    async def record_admin_action(
        self,
        actor: str,
        action: str,
        target: str | None = None,
        role: str | None = None,
        success: bool = True,
        detail: str | None = None,
    ) -> None:
        """Persist one privileged-tool action (M-6, CWE-778).

        Full identities live here (queryable, 0600 SQLite) rather than in the
        rotating logs, whose sanitizer masks emails by design.
        """
        async with self._db() as db:
            await db.execute(
                "INSERT INTO admin_audit_log "
                "(ts, actor, action, target, role, success, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_iso(_now()), actor, action, target, role,
                 1 if success else 0, detail),
            )
            # Opportunistic retention sweep, in the same style oauth_codes
            # already uses. This table is append-only and deliberately holds
            # FULL unmasked identities, so it was the one copy of that data
            # with no retention period at all while the rotating logs (masked)
            # had one — precisely what a GDPR retention question lands on
            # (PT-10). 0 disables the sweep for deployments that archive
            # externally.
            if _AUDIT_RETENTION_DAYS > 0:
                await db.execute(
                    "DELETE FROM admin_audit_log WHERE ts < ?",
                    (_iso(_now() - timedelta(days=_AUDIT_RETENTION_DAYS)),),
                )
            await db.commit()

    # ------------------------------------------------- registered MCP clients

    async def put_client(self, client_id: str, payload: dict[str, Any]) -> None:
        async with self._db() as db:
            await db.execute(
                "INSERT INTO oauth_clients (client_id, payload, created_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT (client_id) DO UPDATE SET payload = excluded.payload",
                (client_id, json.dumps(payload), _iso(_now())),
            )
            # Dynamic client registration must be anonymous per the MCP OAuth
            # profile, so this table grows with every registering connector and
            # had no eviction of any kind, unlike oauth_codes and
            # oauth_refresh_tokens (PT-09). Drop registrations older than the
            # retention window that hold no live refresh token — a client still
            # in use re-registers or keeps refreshing, so this cannot evict a
            # connector anyone is actually using.
            if _CLIENT_RETENTION_DAYS > 0:
                await db.execute(
                    "DELETE FROM oauth_clients WHERE created_at < ? AND client_id "
                    "NOT IN (SELECT client_id FROM oauth_refresh_tokens "
                    "        WHERE revoked = 0 AND expires_at > ?)",
                    (_iso(_now() - timedelta(days=_CLIENT_RETENTION_DAYS)),
                     _iso(_now())),
                )
            await db.commit()

    async def get_client(self, client_id: str) -> dict[str, Any] | None:
        async with self._db() as db:
            cur = await db.execute(
                "SELECT payload FROM oauth_clients WHERE client_id = ?", (client_id,)
            )
            row = await cur.fetchone()
        return json.loads(row["payload"]) if row else None

    # ----------------------------------------------------- authorization codes

    async def put_code(
        self, code: str, payload: dict[str, Any], ttl_seconds: int
    ) -> None:
        expires = _now() + timedelta(seconds=ttl_seconds)
        async with self._db() as db:
            await db.execute(
                "INSERT INTO oauth_codes (code_hash, payload, expires_at) "
                "VALUES (?, ?, ?)",
                (token_hash(code), json.dumps(payload), _iso(expires)),
            )
            await db.commit()

    async def take_code(self, code: str) -> dict[str, Any] | None:
        """Fetch AND delete in one statement — a code is single-use even if the
        subsequent PKCE check fails (burning it is the safe failure mode)."""
        now = _iso(_now())
        async with self._db() as db:
            cur = await db.execute(
                "DELETE FROM oauth_codes WHERE code_hash = ? AND expires_at > ? "
                "RETURNING payload",
                (token_hash(code), now),
            )
            row = await cur.fetchone()
            # Opportunistic cleanup of expired codes (tiny table).
            await db.execute("DELETE FROM oauth_codes WHERE expires_at <= ?", (now,))
            await db.commit()
        return json.loads(row["payload"]) if row else None

    # ------------------------------------------------------------ refresh tokens

    async def put_refresh(
        self,
        token: str,
        *,
        client_id: str,
        email: str,
        scopes: list[str],
        ttl_seconds: int,
    ) -> None:
        expires = _now() + timedelta(seconds=ttl_seconds)
        async with self._db() as db:
            await db.execute(
                "INSERT INTO oauth_refresh_tokens "
                "(token_hash, client_id, email, scopes, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    token_hash(token),
                    client_id,
                    email,
                    json.dumps(scopes),
                    _iso(expires),
                    _iso(_now()),
                ),
            )
            await db.commit()

    async def get_refresh(self, token: str) -> dict[str, Any] | None:
        async with self._db() as db:
            cur = await db.execute(
                "SELECT token_hash, client_id, email, scopes, expires_at, revoked "
                "FROM oauth_refresh_tokens "
                "WHERE token_hash = ? AND revoked = 0 AND expires_at > ?",
                (token_hash(token), _iso(_now())),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["scopes"] = json.loads(d["scopes"])
        d["expires_at"] = _parse(d["expires_at"])
        d["revoked"] = bool(d["revoked"])
        return d

    async def get_refresh_any(self, token: str) -> dict[str, Any] | None:
        """The row for this token REGARDLESS of revoked/expired state.

        get_refresh() filters `revoked = 0`, which makes a replayed token that
        was already rotated away indistinguishable from one that never existed.
        Telling them apart is the whole of reuse detection (PT-06).
        """
        async with self._db() as db:
            cur = await db.execute(
                "SELECT token_hash, client_id, email, scopes, expires_at, revoked "
                "FROM oauth_refresh_tokens WHERE token_hash = ?",
                (token_hash(token),),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["scopes"] = json.loads(d["scopes"])
        d["expires_at"] = _parse(d["expires_at"])
        d["revoked"] = bool(d["revoked"])
        return d

    async def revoke_all_refresh_for_email(self, email: str) -> int:
        """Revoke every live refresh token for one identity. Returns the count.

        Rotation is correct here (the presented token is revoked before a new
        one is issued), but without family revocation a stolen token that has
        already been used once is just noise: the thief and the legitimate user
        race, and whoever refreshes second silently loses. `oauth_refresh_tokens`
        already carries `email` and an index on it (PT-06).
        """
        async with self._db() as db:
            cur = await db.execute(
                "UPDATE oauth_refresh_tokens SET revoked = 1 "
                "WHERE email = ? AND revoked = 0",
                (email.strip().lower(),),
            )
            await db.commit()
            return cur.rowcount or 0

    async def revoke_refresh(self, token: str) -> None:
        async with self._db() as db:
            await db.execute(
                "UPDATE oauth_refresh_tokens SET revoked = 1 WHERE token_hash = ?",
                (token_hash(token),),
            )
            # Opportunistic cleanup: drop rows long past expiry.
            await db.execute(
                "DELETE FROM oauth_refresh_tokens WHERE expires_at < ?",
                (_iso(_now() - timedelta(days=7)),),
            )
            await db.commit()
