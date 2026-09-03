"""Registered-user management tool (ptab:admin scope in OAuth mode).

Registration-gated by PTAB_ENABLE_USER_MANAGEMENT (default off — matches the
PFW pattern / neo4j NEO4J_READ_ONLY approach)."""

import os
import re
from typing import Any, Dict

from fastmcp.apps import AppConfig

from ..app_uris import USER_MANAGEMENT_URI
from ..shared.safe_logger import get_safe_logger
from ..util.identity import get_authenticated_identity

logger = get_safe_logger(__name__)

# Registration gate for the user-management tool (neo4j NEO4J_READ_ONLY
# pattern: filtered at registration time, so it never appears in tools/list
# when off). Default OFF: stdio doesn't need it (seed admins with
# scripts/manage_mcp_users.py), and outside OAuth mode it would be protected
# only by the shared INTERNAL_AUTH_SECRET. Prod OAuth compose must set
# PTAB_ENABLE_USER_MANAGEMENT=true.
USER_MANAGEMENT_ENABLED = (
    os.getenv("PTAB_ENABLE_USER_MANAGEMENT", "false").lower() == "true"
)

# Set by register(): the OAuth provider's user store is reused when present
_auth_provider = None

# Module scope. `re` is stdlib and always importable, so the lazy path bought
# nothing and cost a `global`, mutable module state, an aliased function-local
# import and a branch in a function already over the complexity gate (R-4).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_VALID_ACTIONS = ("list", "add", "set_role", "activate", "deactivate")
_ROLES = ("user", "admin")


def _get_user_store():
    """User store for the management tool: reuse the auth provider's store in
    OAuth mode; otherwise open the configured SQLite path directly (stdio /
    plain-HTTP use, e.g. seeding before OAuth is switched on)."""
    if _auth_provider is not None:
        # `users`, not `_users`: the tool layer reading a leading-underscore
        # attribute off the auth provider breaks silently on a rename, which is
        # exactly the failure mode main.py:226-242 refuses to accept for the
        # admin scope gate.
        return _auth_provider.users
    from ..auth import AuthSettings
    from ..auth.store import McpUserStore

    return McpUserStore(AuthSettings.from_env().auth_db_path)


async def _record_admin_action(store, actor: str, action: str, target: str,
                               role: str, success: bool, detail: str = "") -> None:
    """Persist and log one admin action.

    Every state-changing admin action leaves a persistent, queryable trail
    (M-6, CWE-778): full identities in the admin_audit_log table, a sanitized
    (email-masked) line in the security log. Lifted out of the tool function
    as a module-level helper rather than a closure (F-4).
    """
    if action == "list":
        return
    audited_role = role if action in ("add", "set_role") else None
    try:
        await store.record_admin_action(
            actor=actor, action=action, target=target,
            role=audited_role, success=success, detail=detail or None,
        )
    except Exception as audit_error:
        logger.error("Admin audit write failed: %s", type(audit_error).__name__)
    logger.info(
        "Admin action: actor=%s action=%s target=%s role=%s success=%s",
        actor, action, target, audited_role or "-", success,
    )


async def _actor_scope_is_stale(store, actor: str) -> bool:
    """True when the caller's baked-in admin scope no longer matches mcp_users.

    OAuth mode only: outside it there is no per-identity actor to re-read
    (`actor` is the placeholder "local-process") and the tool is reached
    through the registration gate plus the transport secret, which
    scripts/manage_mcp_users.py also holds.
    """
    if _auth_provider is None or not get_authenticated_identity():
        return False
    return not await _actor_is_still_an_active_admin(store, actor)


async def _actor_is_still_an_active_admin(store, actor: str) -> bool:
    """Re-read the actor's row from mcp_users right now.

    Access tokens are stateless JWTs with a 3600s TTL and no revocation, so the
    `ptab:admin` scope FastMCP checks was baked in at issue time. Deactivating
    a compromised admin did not revoke it for up to an hour — and inside that
    hour the identity could use THIS tool to re-activate itself in the shared
    table, which is what makes the window matter (PT-05). One live read closes
    it for the mutating actions.
    """
    row = await store.get_user(actor)
    return bool(row and row.get("active") and row.get("role") == "admin")


async def _apply_action(store, action: str, email: str, role: str,
                        display_name: str, notes: str):
    """Perform one user-table mutation.

    Returns (message, failure): `failure` is a caller-facing reason string when
    the action could not be applied, else None. Lifted out of the tool function
    so dispatch, validation, audit and response projection are not one 121-line
    body at complexity 17 (F-4).
    """
    if action == "list":
        return "", None

    if action in ("add", "set_role") and role not in _ROLES:
        return "", f"role must be 'user' or 'admin', got {role!r}"

    if action == "add":
        await store.upsert_user(
            email, role=role,
            display_name=display_name or None,
            notes=notes or None,
        )
        return f"Added/updated {email} with role '{role}'.", None

    if action == "set_role":
        existing = await store.get_user(email)
        if existing is None:
            return "", f"no such user: {email}"
        await store.upsert_user(email, role=role, active=existing["active"])
        return f"{email} role set to '{role}'.", None

    active = action == "activate"
    if not await store.set_active(email, active):
        return "", f"no such user: {email}"
    return f"{email} is now {'active' if active else 'deactivated'}.", None


async def ptab_manage_users(
    action: str = "list",
    email: str = "",
    role: str = "user",
    display_name: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """Manage the registered-user list for OAuth sign-in (ADMIN ONLY).
    Users, accounts, admin, permissions, roles, access, allowlist, add user, deactivate, sign-in.

    Lists, adds, activates, deactivates, or changes the role of registered
    users. A user may sign in via Google / Microsoft only while their row is
    active; role 'admin' additionally grants this user-management tool.
    PTAB reads the SHARED paid-tier user database hosted by PFW — changes
    here apply to PFW, PTAB, and FPD alike. Changes take effect at the
    user's next token refresh (up to 1 hour).

    Args:
        action: One of: list, add, set_role, activate, deactivate
        email: Target user email (required for all actions except list)
        role: 'user' or 'admin' (for add / set_role)
        display_name: Optional display name (for add)
        notes: Optional notes (for add)

    Returns:
        The full user table after the action, plus a confirmation message.
    """
    if action not in _VALID_ACTIONS:
        return {"error": f"action must be one of {_VALID_ACTIONS}, got {action!r}"}

    store = _get_user_store()
    actor = get_authenticated_identity() or "local-process"
    message = ""

    async def _audit(success: bool, detail: str = "") -> None:
        await _record_admin_action(store, actor, action, email, role, success, detail)

    try:
        if action != "list":
            email = email.strip().lower()
            if not _EMAIL_RE.match(email):
                return {"error": f"invalid email address: {email!r}"}

            if await _actor_scope_is_stale(store, actor):
                logger.warning(
                    "Admin action refused: actor is no longer an active admin "
                    "in mcp_users (stale token scope)"
                )
                await _audit(False, "actor no longer an active admin")
                return {
                    "error": "Your administrator access has been revoked. "
                             "Sign in again to refresh your session."
                }

        message, failure = await _apply_action(
            store, action, email, role, display_name, notes
        )
        if failure is not None:
            await _audit(False, failure)
            return {"error": failure}

        await _audit(True)
        users = await store.list_users()
        return {
            "action": action,
            "message": message or f"{len(users)} registered user(s).",
            "users": [
                {
                    "email": u["email"],
                    "display_name": u["display_name"],
                    "role": u["role"],
                    "active": u["active"],
                    "added_at": u["added_at"].isoformat() if u["added_at"] else None,
                    "last_login_at": (
                        u["last_login_at"].isoformat() if u["last_login_at"] else None
                    ),
                    "last_login_idp": u["last_login_idp"],
                    "notes": u["notes"],
                }
                for u in users
            ],
        }
    except Exception as e:
        logger.error("User management action failed: %s", type(e).__name__)
        try:
            await _audit(False, type(e).__name__)
        except Exception as audit_error:
            # An admin action failing AND its audit failing must not produce
            # zero record of either.
            logger.error(
                "Admin audit write failed on the error path: %s",
                type(audit_error).__name__,
            )
        # The exception TYPE only: an aiosqlite error carries the absolute path
        # of the shared auth DB and a constraint violation carries column names.
        # Every other tool path routes through sanitize_error_message.
        return {"error": f"User management failed: {type(e).__name__}"}


def register(mcp, auth_provider=None) -> None:
    """Register ptab_manage_users when the gate allows it."""
    global _auth_provider
    _auth_provider = auth_provider
    if USER_MANAGEMENT_ENABLED:
        if _auth_provider is None and os.getenv("FASTMCP_TRANSPORT", "stdio") == "http":
            # Enabled on the HTTP surface without OAuth, the only protection on
            # this tool would be the shared INTERNAL_AUTH_SECRET — anyone
            # holding that ecosystem-wide secret could self-grant admin across
            # PFW/PTAB/FPD via the shared user DB. Refuse to start rather than
            # register it ungated (this used to log a warning and continue).
            # stdio stays allowed: there the OS process boundary is the gate.
            raise RuntimeError(
                "PTAB_ENABLE_USER_MANAGEMENT=true requires PTAB_AUTH_MODE=oauth in "
                "HTTP mode; the shared INTERNAL_AUTH_SECRET is not a per-identity "
                "gate. Use scripts/manage_mcp_users.py for out-of-band administration."
            )
        mcp.tool(name="ptab_manage_users", app=AppConfig(resource_uri=USER_MANAGEMENT_URI),
                 annotations={"defer_loading": True})(ptab_manage_users)
    else:
        logger.info(
            "ptab_manage_users not registered (PTAB_ENABLE_USER_MANAGEMENT is off; "
            "default). Use scripts/manage_mcp_users.py for user administration."
        )
