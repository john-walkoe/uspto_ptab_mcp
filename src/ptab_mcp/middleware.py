"""HTTP-mode ASGI middleware for the MCP surface (module split, SD-1).

Stack order is composed in server_bootstrap.run_server():
Probe -> SecurityHeaders -> APIKeyAuth -> SizeLimit -> CORS -> mcp app.
"""

import os

from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


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
        from .shared_secure_storage import get_internal_auth_secret
        import secrets as _secrets
        expected = (
            get_internal_auth_secret()
            or os.environ.get("INTERNAL_AUTH_SECRET")
        )
        if not expected:
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Server misconfigured: INTERNAL_AUTH_SECRET not set"}, status_code=500)
            await response(scope, receive, send)
            return
        if not key or not _secrets.compare_digest(key, expected):
            # Log the event only — never the presented key or the path
            logger.warning("HTTP auth failed (x-api-key missing or mismatch)")
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Adds browser security headers to all HTTP responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        _SECURITY_HEADERS = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
            # script-src has no 'unsafe-inline' (L-5): nothing on this surface
            # ships inline scripts (the OAuth pages use inline <style> only).
            # Referrer-Policy/Permissions-Policy match the download proxy (L-8).
            (
                b"content-security-policy",
                b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'",
            ),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
        ]

        async def patched_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
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
