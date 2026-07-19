"""Caller identity + per-registrant viewer key (C-1 / M-4 / M-6 support)."""

from typing import Optional


def get_authenticated_identity() -> Optional[str]:
    """Email/client_id of the authenticated caller, or None outside OAuth."""
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
        if token is not None:
            claims = getattr(token, "claims", None) or {}
            return claims.get("email") or getattr(token, "client_id", None)
    except Exception:
        pass
    return None


_PROCESS_VIEWER_KEY: Optional[str] = None


def get_viewer_key() -> str:
    """Per-registrant key scoping the recent-downloads registry (C-1).

    Under OAuth, derived per authenticated identity so tenants sharing one
    HTTP process each see only their own downloads on /downloads and
    /api/recent-downloads. Under stdio/plain HTTP (single-operator), one
    random per-process key. Only its hash is stored by the proxy.
    """
    global _PROCESS_VIEWER_KEY
    if _PROCESS_VIEWER_KEY is None:
        import secrets
        _PROCESS_VIEWER_KEY = secrets.token_urlsafe(16)
    identity = get_authenticated_identity()
    if identity:
        import hashlib
        return hashlib.sha256(
            f"{_PROCESS_VIEWER_KEY}:{identity}".encode("utf-8")
        ).hexdigest()[:32]
    return _PROCESS_VIEWER_KEY
