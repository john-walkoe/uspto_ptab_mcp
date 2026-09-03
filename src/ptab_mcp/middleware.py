"""HTTP-mode ASGI middleware for the MCP surface (module split, SD-1).

Stack order is composed in server_bootstrap.run_server():
Probe -> SecurityHeaders -> APIKeyAuth -> SizeLimit -> CORS -> mcp app.
"""

import os

from .shared import security_headers as shared_security_headers
from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


def _matches_any_candidate(presented, candidates) -> bool:
    """Constant-time membership test against every rotation candidate.

    INTERNAL_AUTH_SECRET may be a comma-separated list (current secret
    first, then any secret still being retired) — a rotation overlap window
    instead of a synchronized four-service restart. Every candidate is
    compared, never short-circuited on the first match, so the timing does
    not reveal how many secrets are in the rotation window or which one (if
    any) validated.
    """
    if not presented:
        return False
    import secrets as _secrets

    matched = False
    for candidate in candidates:
        if _secrets.compare_digest(presented, candidate):
            matched = True
    return matched


class APIKeyAuthMiddleware:
    """Validates X-API-KEY header on all non-health requests in HTTP mode.

    Checks against INTERNAL_AUTH_SECRET (the shared cross-MCP secret).
    Health endpoint is intentionally open for load balancer probes.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from starlette.requests import Request
        request = Request(scope, receive)
        if request.url.path == "/health":
            await self.app(scope, receive, send)
            return
        key = request.headers.get("x-api-key")
        from .shared_secure_storage import get_internal_auth_secret, split_secret_candidates
        expected_raw = (
            get_internal_auth_secret()
            or os.environ.get("INTERNAL_AUTH_SECRET")
        )
        candidates = split_secret_candidates(expected_raw)
        if not candidates:
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Server misconfigured: INTERNAL_AUTH_SECRET not set"}, status_code=500)
            await response(scope, receive, send)
            return
        if not _matches_any_candidate(key, candidates):
            # Log the event only — never the presented key or the path
            logger.warning("HTTP auth failed (x-api-key missing or mismatch)")
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


#: This surface's own CSP. script-src has no 'unsafe-inline' (L-5): nothing
#: here ships inline scripts (the OAuth pages use inline <style> only). The
#: download proxy's CSP differs because its /downloads page carries an inline
#: script, which is why only the static headers are shared (F-8).
_CSP = b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"

# Module scope, not rebuilt inside __call__ on every single HTTP request (R-4).
_SECURITY_HEADERS = [
    (name.lower().encode("ascii"), value.encode("ascii"))
    for name, value in shared_security_headers.SECURITY_HEADERS
] + [(b"content-security-policy", _CSP)]

_HSTS_HEADER = (
    shared_security_headers.HSTS_HEADER[0].lower().encode("ascii"),
    shared_security_headers.HSTS_HEADER[1].encode("ascii"),
)


def _is_tls(scope) -> bool:
    """True when the request arrived over TLS, directly or via a declared hop."""
    forwarded = ""
    for name, value in scope.get("headers", ()):
        if name == b"x-forwarded-proto":
            forwarded = value.decode("latin-1")
            break
    return shared_security_headers.is_tls(scope.get("scheme", ""), forwarded)


class SecurityHeadersMiddleware:
    """Adds browser security headers to all HTTP responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        extra = _SECURITY_HEADERS + [_HSTS_HEADER] if _is_tls(scope) else _SECURITY_HEADERS

        async def patched_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(extra)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, patched_send)


class _StreamableHTTPProbeMiddleware:
    """Return 401 for MCP probe requests that lack the required Accept header.

    claude.ai's MCP client first probes /mcp (GET and POST — Lessons 30/39)
    with an older format that omits 'text/event-stream' from Accept.
    FastMCP's StreamableHTTP handler rejects those with 406, which puts
    claude.ai into a permanent "format-incompatible" state where it never
    indexes the server's tools. Returning 401 instead causes claude.ai to
    attempt OAuth discovery (404 — expected) and then fall back to an
    anonymous connection that completes the full MCP handshake.

    Must be the outermost middleware layer.
    """
    def __init__(self, inner_app):
        self.app = inner_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope.get("method", "")
            path = scope.get("path", "")
            headers = dict(scope.get("headers", []))
            accept = headers.get(b"accept", b"").decode()
            if (
                path == "/mcp"
                and method in ("POST", "GET")
                and "text/event-stream" not in accept
            ):
                from starlette.responses import JSONResponse
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
