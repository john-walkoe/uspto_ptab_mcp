"""
FastAPI HTTP server for secure PTAB document downloads.

Provides browser-accessible download URLs while keeping USPTO API keys secure.
Supports three identifier types: trial, appeal, interference.
Port configuration via PTAB_PROXY_PORT environment variable (default: 8083).
"""

import contextlib
import ipaddress
import base64
import hashlib
import re
import os
import secrets as _secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
import httpx


#: This repository's own .env. Resolved explicitly rather than by
#: python-dotenv's default upward walk.
_REPO_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def load_env_file() -> None:
    """Load THIS REPO'S .env into the process environment. Entry points only.

    This used to be a bare `load_dotenv()` at module scope. Two problems:

    1. python-dotenv walks UPWARD from the working directory, so it read a
       .env from OUTSIDE the repository. In a checkout under
       `~/mcp-servers/uspto_ptab_mcp` it reached `~/mcp-servers/.env` and
       injected a live USPTO_API_KEY and MISTRAL_API_KEY into the process.
    2. It ran on IMPORT, and `tools/documents.py` imports this module, so
       importing a tool module was enough to trigger it — including under
       pytest, where it silently replaced conftest's placeholder key with a
       production one, with no log line.

    Loading a .env is a deliberate act at an entry point, and the path is
    pinned so the search cannot escape the repository.
    """
    from dotenv import load_dotenv

    if _REPO_ENV_FILE.is_file():
        load_dotenv(_REPO_ENV_FILE)


from ..api.ptab_client import PTABClient  # noqa: E402 — after the module preamble
from .rate_limiter import rate_limiter  # noqa: E402
from ..shared.error_utils import generate_request_id  # noqa: E402
from ..shared import security_headers as shared_security_headers  # noqa: E402
from ..shared.safe_logger import get_safe_logger  # noqa: E402
from ..shared.uspto_shared_rate_limiter import get_shared_limiter  # noqa: E402
from ..shared.uspto_hosts import USPTO_KEY_EVENT_HOOKS  # noqa: E402

logger = get_safe_logger(__name__)

# Request size limit configuration
MAX_REQUEST_SIZE = 1024 * 1024  # 1MB limit

DEFAULT_PROXY_PORT = 8083


def get_proxy_port() -> int:
    """Safely parse the proxy port from PTAB_PROXY_PORT / PROXY_PORT (dedup 1.1).

    Single implementation behind main.get_local_proxy_port and the proxy's
    own callers. Handles the 'none' sentinel BEFORE int conversion.
    """
    port_str = os.getenv('PTAB_PROXY_PORT') or os.getenv('PROXY_PORT') or str(DEFAULT_PROXY_PORT)
    if port_str.lower() == 'none':
        return DEFAULT_PROXY_PORT
    try:
        return int(port_str)
    except ValueError:
        logger.warning(f"Invalid port '{port_str}', using default {DEFAULT_PROXY_PORT}")
        return DEFAULT_PROXY_PORT

def _download_timeout() -> float:
    """USPTO_DOWNLOAD_TIMEOUT, bounds-checked the same way PTABClient does."""
    from ..validation.validators import validate_timeout
    try:
        return validate_timeout(float(os.getenv("USPTO_DOWNLOAD_TIMEOUT", "60.0")), 10.0, 300.0)
    except (ValueError, TypeError):
        logger.warning("Invalid USPTO_DOWNLOAD_TIMEOUT, using 60.0")
        return 60.0


def _rate_limited_response(client_ip: str) -> JSONResponse:
    """The 429 both download routes return.

    Built twice with drift: one copy omitted "remaining_requests", so two
    clients hitting the same limiter got two different 429 bodies (D-6).
    """
    remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))
    return JSONResponse(
        status_code=429,
        content={
            "error": True,
            "message": "Rate limit exceeded. USPTO allows 5 downloads per 10 seconds.",
            "retry_after": remaining_time,
            "remaining_requests": 0,
        },
        headers={"Retry-After": str(remaining_time)},
    )


# Global client instance
api_client = None

# =============================================================================
# PROXY TOKEN AUTH (server-to-server endpoints only)
# =============================================================================
# The token protects machine-facing endpoints (/download/{type}/... and
# /api/register-download). Browser-facing endpoints (persistent links, the
# downloads page) must NOT require it — browsers cannot send custom headers
# on navigation (Lessons 41/43). Callers in the same process import
# _get_proxy_token(); cross-process callers set PROXY_TOKEN on both sides
# (Lesson 40: never regenerate the token in a caller).

_PROXY_TOKEN: Optional[str] = None


#: Minimum length for a bearer credential supplied by an operator. The JWT
#: secret already gets this check at auth/provider.py; PROXY_TOKEN and the
#: internal bearers were accepted at any length (PT-34).
MIN_SECRET_LENGTH = 32


def _get_proxy_token() -> str:
    """Return the proxy auth token (PROXY_TOKEN env or generated once)."""
    global _PROXY_TOKEN
    if _PROXY_TOKEN is None:
        supplied = os.getenv("PROXY_TOKEN") or ""
        if not supplied:
            # Fails closed (a random value can never match a peer's), but the
            # cross-process registration path then breaks silently, so say so.
            logger.warning(
                "PROXY_TOKEN is not set; using a per-process random value. "
                "Cross-process callers will fail to authenticate."
            )
        elif len(supplied) < MIN_SECRET_LENGTH:
            logger.warning(
                "PROXY_TOKEN is shorter than %d characters; it is a permanent "
                "bearer credential and should be at least that long.",
                MIN_SECRET_LENGTH,
            )
        _PROXY_TOKEN = supplied or _secrets.token_urlsafe(32)
    return _PROXY_TOKEN


class ProxyTokenDependency:
    """FastAPI dependency validating the X-Proxy-Token header."""

    async def __call__(self, request: Request) -> None:
        supplied = request.headers.get("X-Proxy-Token", "")
        if not _secrets.compare_digest(supplied, _get_proxy_token()):
            # Log the event only — never the presented token or the path
            logger.warning("Proxy token auth failed (X-Proxy-Token missing or mismatch)")
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid X-Proxy-Token header"
            )


_check_proxy_token = ProxyTokenDependency()

# =============================================================================
# RECENT DOWNLOADS REGISTRY (in-memory, for the downloads panel/page)
# =============================================================================

_MAX_RECENT_DOWNLOADS = 50
_recent_downloads: List[Dict[str, Any]] = []
_recent_downloads_lock = threading.Lock()

# Registry entries are scoped to the registrant's viewer key so one tenant
# cannot enumerate another tenant's live persistent-download links (each
# download_url is itself a bearer credential). Only the SHA-256 of the key is
# stored; the raw key travels in the tool's own /downloads?s=... URL.
_VIEWER_KEY_FIELD = "viewer_key"
_VIEWER_HASH_FIELD = "_viewer_key_hash"


def _hash_viewer_key(viewer_key: str) -> str:
    import hashlib
    return hashlib.sha256(viewer_key.encode("utf-8")).hexdigest()


def register_recent_download(entry: Dict[str, Any]) -> str:
    """Add a download to the in-memory registry; returns its download_id."""
    download_id = entry.get("download_id") or uuid.uuid4().hex
    entry = {**entry, "download_id": download_id,
             "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    viewer_key = entry.pop(_VIEWER_KEY_FIELD, None)
    if viewer_key:
        entry[_VIEWER_HASH_FIELD] = _hash_viewer_key(str(viewer_key))
    with _recent_downloads_lock:
        _recent_downloads.insert(0, entry)
        del _recent_downloads[_MAX_RECENT_DOWNLOADS:]
    return download_id


def get_recent_downloads(viewer_key: Optional[str] = None,
                         include_all: bool = False) -> List[Dict[str, Any]]:
    """Return a snapshot of the registry scoped to one viewer key.

    include_all=True (proxy-token-authenticated callers only) returns every
    entry. Otherwise only entries registered under `viewer_key` are returned;
    no key means no entries. Internal hash fields are stripped either way.
    """
    if not include_all and not viewer_key:
        return []
    wanted = _hash_viewer_key(viewer_key) if viewer_key else None
    with _recent_downloads_lock:
        snapshot = list(_recent_downloads)
    results = []
    for entry in snapshot:
        if not include_all and entry.get(_VIEWER_HASH_FIELD) != wanted:
            continue
        results.append({k: v for k, v in entry.items() if k != _VIEWER_HASH_FIELD})
    return results


# Browser-facing downloads page (served at GET /downloads, no token).
# Same-origin fetch to /api/recent-downloads
# is fine here: this is a real browser tab, not an MCP App iframe (Lesson 23
# only restricts iframes).
_DOWNLOADS_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PTAB Downloads</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 14px; background: #f8f9fa; color: #1a1a2e; }
.header { background: #3d2a6b; color: #fff; padding: 14px 20px; display: flex; align-items: center; gap: 12px; }
.header h1 { font-size: 17px; font-weight: 600; }
.header .count { background: #7a5fd0; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.tip { background: #fff9e6; border-bottom: 1px solid #ffe08a; padding: 7px 20px; font-size: 12px; color: #6b5000; }
.container { max-width: 860px; margin: 0 auto; padding: 16px 20px; }
.empty { text-align: center; padding: 50px 20px; color: #888; }
.card { background: #fff; border: 1px solid #e0dcec; border-radius: 8px; margin-bottom: 10px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; transition: background 0.3s; }
.card.highlight { background: #efe9fe; border-color: #7a5fd0; box-shadow: 0 0 0 2px rgba(122,95,208,0.35); }
.icon { width: 36px; height: 36px; border-radius: 6px; background: #efe9fe; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.info { flex: 1; min-width: 0; }
.title { font-weight: 600; font-size: 13px; margin-bottom: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { font-size: 12px; color: #888; display: flex; gap: 10px; flex-wrap: wrap; }
.badge { background: #efe9fe; color: #3d2a6b; border-radius: 3px; padding: 1px 6px; font-size: 11px; font-weight: 700; }
a.btn { background: #3d2a6b; color: #fff; border-radius: 5px; padding: 7px 14px; font-size: 13px; text-decoration: none; white-space: nowrap; }
a.btn:hover { background: #7a5fd0; }
.ts { font-size: 11px; color: #bbb; white-space: nowrap; }
#status { text-align: center; font-size: 12px; color: #999; padding: 8px; }
</style>
</head>
<body>
<div class="header"><h1>PTAB Recent Downloads</h1><span class="count" id="count">0</span></div>
<div class="tip">Click <strong>Download PDF</strong> to save a document. Links stay valid for 7 days. This page refreshes automatically.</div>
<div class="container">
  <div class="empty" id="empty" style="display:none">No downloads yet — use <code>PTAB_get_document_download</code> in Claude to generate links.</div>
  <div id="cards"></div>
  <div id="status"></div>
</div>
<script>
const ICONS = { trial: '⚖️', appeal: '📜', interference: '🔀', default: '📄' };
const params = new URLSearchParams(location.search);
const highlightId = params.get('highlight');
const viewerKey = params.get('s') || '';
let firstLoad = true;

// PT-02: registry values are USPTO-authored free text rendered with
// innerHTML below; escape every interpolation.
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtTime(iso) {
  try {
    const d = new Date(iso); const mins = Math.floor((Date.now() - d) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    if (mins < 1440) return Math.floor(mins / 60) + 'h ago';
    return d.toLocaleDateString();
  } catch { return ''; }
}

async function load() {
  try {
    const resp = await fetch('/api/recent-downloads?s=' + encodeURIComponent(viewerKey));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const docs = (await resp.json()).downloads || [];
    document.getElementById('count').textContent = docs.length;
    document.getElementById('empty').style.display = docs.length ? 'none' : 'block';
    const cards = document.getElementById('cards');
    cards.innerHTML = '';
    docs.forEach(d => {
      const div = document.createElement('div');
      div.className = 'card' + (highlightId && d.download_id === highlightId ? ' highlight' : '');
      const type = d.identifier_type || 'default';
      div.innerHTML = `
        <div class="icon">${ICONS[type] || ICONS.default}</div>
        <div class="info">
          <div class="title">${esc(d.enhanced_filename || d.document_description || 'Document')}</div>
          <div class="meta"><span class="badge">${esc(type)}</span><span>${esc(d.identifier || '')}</span><span>Doc ${esc(d.document_id || '')}</span></div>
        </div>
        <span class="ts">${esc(fmtTime(d.registered_at))}</span>
        <a class="btn" href="${esc(d.download_url)}">Download PDF</a>
      `;
      cards.appendChild(div);
    });
    if (firstLoad && highlightId) {
      document.querySelector('.card.highlight')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      firstLoad = false;
    }
    document.getElementById('status').textContent = '';
  } catch (e) {
    document.getElementById('status').textContent = 'Could not load downloads: ' + e.message;
  }
}

load();
setInterval(load, 5000);
</script>
</body>
</html>"""


# Moved to util/document_naming.py (Q-6): a pure string function does not
# belong in an ASGI server module that the tool layer has to import.
# Re-exported here for existing importers.
from ..util.document_naming import (  # noqa: E402,F401
    derive_document_description,
    generate_enhanced_filename,
    sanitize_description,
)

def _inline_script_csp_hashes(html: str) -> str:
    """CSP `'sha256-...'` source values for every inline <script> in `html`.

    The downloads page carries an inline script and an inline <style>, and the
    blanket `default-src 'self'` header below silently blocked both, so the
    page rendered an empty shell. Hashes are the right fix for static markup:
    they keep the policy closed to injected script while letting this one
    known script run. Recomputed at import, so editing the page cannot leave a
    stale hash behind.
    """
    digests = []
    for body in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        digest = hashlib.sha256(body.encode("utf-8")).digest()
        digests.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return " ".join(digests)


_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' " + _inline_script_csp_hashes(_DOWNLOADS_PAGE_HTML) + "; "
    # The page's <style> block and its style="..." attributes are static
    # markup in this file; no untrusted value reaches either.
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Static headers from the one shared source (F-8); the CSP stays local
        # because this surface's /downloads page carries an inline script.
        for name, value in shared_security_headers.SECURITY_HEADERS:
            response.headers[name] = value
        # HSTS only over TLS: this listener is plain-HTTP loopback by default,
        # where the header is inert in browsers but misleading in an audit and
        # a hazard if the hostname later resolves publicly.
        if shared_security_headers.is_tls(
            request.url.scheme, request.headers.get("x-forwarded-proto", "")
        ):
            name, value = shared_security_headers.HSTS_HEADER
            response.headers[name] = value
        response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY

        return response


class _BodyTooLarge(Exception):
    """Raised by the counting receive wrapper when a body exceeds the cap."""

    def __init__(self, received: int):
        self.received = received


class RequestSizeLimitMiddleware:
    """
    ASGI middleware to limit request body size for security.

    Prevents DoS attacks via large request bodies. Checks Content-Length when
    present AND keeps a running byte count while the body streams in, so
    Transfer-Encoding: chunked requests (no Content-Length) cannot bypass the
    cap (audit M-3, CWE-400). Pure ASGI so it also wraps the MCP HTTP stack
    in main.py without BaseHTTPMiddleware's streaming caveats.
    """

    def __init__(self, app, max_request_size: int = MAX_REQUEST_SIZE):
        self.app = app
        self.max_request_size = max_request_size

    async def _send_413(self, send, request_id: str) -> None:
        import json as _json
        body = _json.dumps({
            "error": True,
            "message": f"Request body too large. Maximum size: {self.max_request_size} bytes",
            "max_allowed": self.max_request_size,
            "request_id": request_id,
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        content_length = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    content_length = int(value)
                except ValueError:
                    pass
                break

        if content_length is not None and content_length > self.max_request_size:
            request_id = generate_request_id()
            logger.warning(
                f"[{request_id}] Request body too large: Content-Length "
                f"{content_length} bytes from {client_ip}"
            )
            await self._send_413(send, request_id)
            return

        received = 0
        response_started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_size:
                    raise _BodyTooLarge(received)
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge as exc:
            request_id = generate_request_id()
            logger.warning(
                f"[{request_id}] Request body too large: streamed "
                f"{exc.received}+ bytes from {client_ip}"
            )
            if not response_started:
                await self._send_413(send, request_id)
            # If the response already started there is nothing safe to send;
            # the connection is torn down by the server.


_DOCUMENT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _validate_download_params(identifier_type: str, identifier: str,
                              document_id: str) -> tuple:
    """Apply the MCP tool layer's validators to proxy path params (M-2)."""
    from ..validation.validators import (
        validate_appeal_number,
        validate_interference_number,
        validate_trial_number,
    )
    try:
        if identifier_type == "trial":
            identifier = validate_trial_number(identifier)
        elif identifier_type == "appeal":
            identifier = validate_appeal_number(identifier)
        elif identifier_type == "interference":
            identifier = validate_interference_number(identifier)
        else:
            # Log the ROUTE and the reason class only, never the value: the
            # rejection is the signal, and document-id / trial-number probing
            # against /download/{type}/{id}/{doc} used to leave no record at
            # all (PT-38). Content minimization still applies.
            logger.warning(
                "Download rejected at validation: unknown identifier_type"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Invalid identifier_type: {identifier_type}"
            )
    except ValueError as e:
        logger.warning("Download rejected at validation: malformed identifier")
        raise HTTPException(status_code=400, detail=f"Invalid identifier: {e}")
    if not _DOCUMENT_ID_RE.fullmatch(document_id or ""):
        logger.warning("Download rejected at validation: malformed document_id")
        raise HTTPException(status_code=400, detail="Invalid document_id")
    return identifier_type, identifier, document_id


async def _limiter_acquire(limiter) -> None:
    """No-op when the shared rate limiter is disabled. Extracted so callers
    with an already-complex control flow (e.g. _open_upstream_pdf_stream)
    don't pick up an extra branch toward their own cyclomatic complexity."""
    if limiter is not None:
        await limiter.__aenter__()


async def _limiter_release(limiter) -> None:
    """No-op when the shared rate limiter is disabled. See _limiter_acquire."""
    if limiter is not None:
        await limiter.__aexit__(None, None, None)


async def _open_upstream_pdf_stream(download_url: str, api_key: str):
    """Open a USPTO PDF stream with the body verified as a PDF (L-9).

    Prefetches the first chunk and checks the %PDF- magic bytes BEFORE any
    response headers go to the client, so a mislabeled upstream body (error
    page, HTML) becomes a clean 502 instead of being served as
    application/pdf. Returns an async generator that owns the connection.
    Raises httpx.HTTPStatusError on non-2xx, HTTPException(502) on non-PDF.

    Shared cross-process rate limiter (token + concurrency slot) — off unless
    USPTO_SHARED_RATE_LIMIT_DIR is set. A streamed PDF download legitimately
    occupies one of the shared slots for its FULL duration (USPTO's burst=1
    guidance), not just connection setup, so the limiter can't be a single
    `async with` here — it's acquired manually below and released either on
    the early-exit path or in stream_body()'s `finally`, since the generator
    this function returns outlives the function call.

    The `request` event hook drops `X-API-KEY` on any hop that is not https on
    uspto.gov: these URLs 302 to S3 signed URLs, and httpx strips only
    `Authorization` and `Cookie` across origins, so the ODP key was reaching
    the redirect target verbatim.
    """
    client = httpx.AsyncClient(
        # The same PDF fetched through PTABClient._download_document honors
        # USPTO_DOWNLOAD_TIMEOUT; through the persistent-link route it did not.
        # A flat timeout=60.0 also applies the READ timeout per chunk of a
        # stream that legitimately runs longer than a minute for a 300-page
        # exhibit, so the failure was a truncated download rather than an error.
        timeout=httpx.Timeout(connect=10.0, read=_download_timeout(), write=60.0, pool=5.0),
        follow_redirects=True, event_hooks=USPTO_KEY_EVENT_HOOKS
    )
    response = None
    limiter = get_shared_limiter()
    await _limiter_acquire(limiter)
    try:
        response = await client.send(
            client.build_request(
                "GET", download_url,
                headers={"X-API-KEY": api_key, "Accept": "application/pdf"},
            ),
            stream=True,
        )
        response.raise_for_status()
        iterator = response.aiter_bytes(chunk_size=8192)
        first_chunk = b""
        async for chunk in iterator:
            first_chunk = chunk
            break
        if not first_chunk.startswith(b"%PDF-"):
            logger.error("Upstream body failed %PDF- magic-byte check")
            raise HTTPException(status_code=502,
                                detail="Upstream returned non-PDF content")
    except Exception:
        await _limiter_release(limiter)
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise

    async def stream_body():
        try:
            if first_chunk:
                yield first_chunk
            async for chunk in iterator:
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()
            await _limiter_release(limiter)

    return stream_body()


def _parse_networks(raw: str, env_name: str) -> List:
    """Parse a comma-separated list of IPs/CIDRs into ip_network objects."""
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning(f"Ignoring invalid {env_name} entry: {entry}")
    return networks


def _request_client_ip(request: Request) -> str:
    """Real client IP as resolved by the ip_allowlist middleware (H-1)."""
    ip = getattr(request.state, "client_ip", None)
    if ip:
        return ip
    return request.client.host if request.client else "unknown"


async def _periodic_link_cleanup(interval_seconds: float = 3600.0):
    """Hourly sweep of expired persistent-link rows (L-2).

    Expiry is already enforced at read time; this keeps the SQLite cache
    from accumulating dead rows indefinitely.
    """
    import asyncio
    from .secure_link_cache import get_link_cache
    while True:
        try:
            get_link_cache().cleanup_expired_links()
        except Exception as e:
            logger.warning(f"Persistent-link cleanup failed: {type(e).__name__}: {e}")
        await asyncio.sleep(interval_seconds)


def create_lifespan(api_key: Optional[str] = None):
    """Create lifespan context manager with API key."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application lifespan."""
        import asyncio
        global api_client
        try:
            # Use provided API key or fall back to environment variable
            api_client = PTABClient(api_key=api_key) if api_key else PTABClient()
            logger.info("USPTO PTAB API client initialized for proxy server")
            cleanup_task = asyncio.create_task(_periodic_link_cleanup())
            try:
                yield
            finally:
                # Await the cancellation: cancel() alone only requests it, and
                # the task may never observe it before the loop closes, which
                # surfaces as "Task was destroyed but it is pending".
                cleanup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cleanup_task
                if api_client is not None:
                    await api_client.aclose()
        except Exception as e:
            logger.error(f"Failed to initialize USPTO PTAB API client: {e}")
            raise
    return lifespan


def _add_proxy_middleware(app: FastAPI) -> None:
    """Install the proxy's middleware stack, outermost last (Q-1 split).

    Order matters and is unchanged: request-size limit, security headers,
    CORS, then the IP allowlist. Lifted out of create_proxy_app so the
    factory is wiring rather than the application itself.
    """
    # Add request size limit middleware (BEFORE other middleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_request_size=MAX_REQUEST_SIZE)

    # Add security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Add CORS middleware with strict origins
    cors_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",  # PFW centralized proxy
        "http://127.0.0.1:8080"
    ]
    cors_extra = os.getenv("CORS_EXTRA_ORIGIN", "").strip()
    if cors_extra and re.match(r"^https?://[A-Za-z0-9.:\-]+$", cors_extra):
        cors_origins.append(cors_extra)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        # No cookie and no ambient credential exists on this surface, so
        # allow_credentials=True bought nothing while widening what a
        # cross-origin page may do. The two headers below are the only ones
        # any caller sends.
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Proxy-Token"],
    )

    # IP allowlist: loopback always allowed; extend via PROXY_ALLOWED_IPS
    # (comma-separated IPs or CIDRs, e.g. Docker subnets - Lesson 32)
    allowed_networks = _parse_networks(os.getenv("PROXY_ALLOWED_IPS", ""),
                                       "PROXY_ALLOWED_IPS")

    # Trusted reverse-proxy hops (H-1). When the TCP peer is one of these,
    # the request's real client IP is taken from X-Forwarded-For (rightmost
    # entry — the one appended by the trusted hop) and the request is
    # accepted at this layer: a declared front door decides public
    # reachability, while machine-facing routes stay X-Proxy-Token-gated and
    # rate limiting keys on the real client IP instead of one shared
    # loopback bucket. Without this setting (default), behavior matches the
    # historical loopback-only trust and PROXY_ALLOWED_IPS semantics.
    trusted_proxy_networks = _parse_networks(os.getenv("PROXY_TRUSTED_IPS", ""),
                                             "PROXY_TRUSTED_IPS")


    @app.middleware("http")
    async def ip_allowlist(request: Request, call_next):
        peer_ip = request.client.host if request.client else ""
        try:
            peer_addr = ipaddress.ip_address(peer_ip)
        except ValueError:
            peer_addr = None

        via_trusted_proxy = peer_addr is not None and any(
            peer_addr in net for net in trusted_proxy_networks
        )
        effective_ip = peer_ip
        if via_trusted_proxy:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                effective_ip = forwarded.split(",")[-1].strip()
        request.state.client_ip = effective_ip

        try:
            effective_addr = ipaddress.ip_address(effective_ip)
        except ValueError:
            effective_addr = None
        allowed = via_trusted_proxy or (
            effective_addr is not None and (
                effective_addr.is_loopback
                or any(effective_addr in net for net in allowed_networks)
            )
        )
        if not allowed:
            logger.warning(f"Rejected proxy request from non-allowlisted IP: {effective_ip}")
            return JSONResponse(status_code=403, content={
                "error": True,
                "message": "Client IP not allowed. Configure PROXY_ALLOWED_IPS for non-local access."
            })
        return await call_next(request)


def _register_health_routes(app: FastAPI) -> None:
    """Register the proxy health route (Q-1 split; route unchanged)."""
    @app.get("/")
    async def health_check():
        """Health check endpoint (RF-7: surfaces circuit-breaker state)."""
        payload = {
            "status": "healthy",
            "service": "PTAB Document Proxy",
            "port": app.state.port,
            "note": f"Runs on port {app.state.port} (configurable via PTAB_PROXY_PORT or PROXY_PORT)"
        }
        if api_client is not None:
            try:
                breakers = api_client.get_circuit_breaker_status()
                payload["circuit_breakers"] = breakers
                if any(b.get("state") != "closed" for b in breakers.values()):
                    payload["status"] = "degraded"
            except Exception as e:
                logger.warning(f"Could not read circuit-breaker status: {type(e).__name__}")
        return payload



def _register_persistent_download_route(app: FastAPI) -> None:
    """Register the browser-facing persistent link route (Q-1 split; route unchanged)."""
    @app.get("/download/persistent/{link_hash}")
    async def download_document_persistent(link_hash: str, request: Request):
        """
        Browser-facing persistent download endpoint.

        The 96-bit link hash IS the credential — this route must never carry
        the X-Proxy-Token dependency, because browsers cannot send custom
        headers on navigation (Lessons 41/43). The encrypted payload stores
        the resolved fileDownloadURI, so no document re-search is needed
        (the GET documents endpoint caps at ~25 documents and misses
        unindexed papers like Petitions).
        """
        client_ip = _request_client_ip(request)
        if not rate_limiter.is_allowed(client_ip):
            return _rate_limited_response(client_ip)

        from .secure_link_cache import LinkStoreUnavailable, get_link_cache
        try:
            link_data = get_link_cache().resolve_persistent_link(link_hash)
        except LinkStoreUnavailable:
            # Not the same answer as "expired": telling the caller to generate a
            # new link when the store cannot be read sends them into a loop,
            # because generating one fails the same way.
            raise HTTPException(
                status_code=503,
                detail="Download link store temporarily unavailable; retry shortly."
            )
        if not link_data:
            raise HTTPException(
                status_code=404,
                detail="Download link not found or expired (links are valid for 7 days). "
                       "Generate a new link with PTAB_get_document_download."
            )

        download_url = link_data.get("file_download_uri")
        filename = link_data.get("enhanced_filename") or "document.pdf"

        if not download_url:
            # Legacy payload without a stored URI — resolve via the standard route
            return await download_document(
                link_data["identifier_type"],
                link_data["identifier"],
                link_data["document_id"],
                request
            )

        # Truncated hash only — the full hash is the credential (Lesson 43)
        logger.info(f"Streaming persistent download {link_hash[:8]}...: {filename}")

        try:
            pdf_stream = await _open_upstream_pdf_stream(download_url, api_client.api_key)
        except httpx.HTTPStatusError as e:
            logger.error(f"USPTO API error {e.response.status_code} on persistent download")
            raise HTTPException(status_code=502,
                                detail=f"USPTO API error: {e.response.status_code}")

        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Enhanced-Filename": filename
            },
            background=BackgroundTask(
                lambda: logger.info(f"Persistent download completed: {filename}")
            )
        )



def _register_registry_routes(app: FastAPI) -> None:
    """Register the recent-downloads registry and page routes (Q-1 split; routes unchanged)."""
    @app.post("/api/register-download", dependencies=[Depends(_check_proxy_token)])
    async def api_register_download(request: Request):
        """Register a generated download for the recent-downloads panel/page.

        Reads the body via Request.json() directly — a `payload: dict`
        parameter would make FastAPI return 422 on schema mismatch, which
        httpx callers would not surface (Lesson 25).
        """
        try:
            payload = await request.json()
        except _BodyTooLarge:
            raise  # RequestSizeLimitMiddleware converts this to a 413
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON object expected")
        # Whitelist + length-cap the stored fields (L-1): entries are later
        # rendered on /downloads via client-side template literals. Manual
        # validation (not a typed route param) keeps errors as explicit 400s.
        from .models import RecentDownloadRegistration
        try:
            registration = RecentDownloadRegistration(**payload)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid registration payload: {e}")
        download_id = register_recent_download(
            registration.model_dump(exclude_none=True)
        )
        return {"registered": True, "download_id": download_id}

    @app.get("/api/recent-downloads")
    async def api_recent_downloads(request: Request):
        """Return the recent downloads registry (for the downloads panel/page).

        Each entry's download_url is a live bearer credential, so this
        endpoint never serves the full registry anonymously (C-1): callers
        present either the machine-facing X-Proxy-Token (full registry) or
        the per-registrant viewer key `s` the tool embedded in the
        /downloads page URL (own entries only).
        """
        supplied_token = request.headers.get("X-Proxy-Token", "")
        if supplied_token and _secrets.compare_digest(supplied_token, _get_proxy_token()):
            return {"downloads": get_recent_downloads(include_all=True)}
        viewer_key = request.query_params.get("s", "")
        if not viewer_key:
            raise HTTPException(
                status_code=401,
                detail="Missing viewer key. Open the downloads page via the "
                       "link returned by PTAB_get_document_download."
            )
        return {"downloads": get_recent_downloads(viewer_key=viewer_key)}

    @app.get("/downloads")
    async def downloads_page():
        """Browser-facing downloads page.

        No token (browser navigation can't send headers); protected by the
        same localhost bind + IP allowlist as everything else. ?highlight=
        scrolls to and highlights a specific download_id.
        """
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_DOWNLOADS_PAGE_HTML)


# Machine-facing document download. Defined at module level rather than inside
# create_proxy_app so it is importable and unit-testable without building the
# whole app (Q-1); it closes over nothing — api_client and rate_limiter are
# module globals.
async def download_document(
    identifier_type: str,
    identifier: str,
    document_id: str,
    request: Request
):
    """
    Proxy endpoint for downloading USPTO PTAB documents.

    This endpoint handles authentication with the USPTO API and streams
    the PDF content directly to the browser, enabling direct downloads
    while keeping API keys secure.

    Args:
        identifier_type: Type of identifier (trial, appeal, interference)
        identifier: Trial/appeal/interference number
        document_id: Document ID from documentBag
        request: FastAPI request object (for client IP)
    """
    try:
        # Validate path params with the same validators the MCP tool
        # layer uses (M-2, CWE-93/1236): identifier reaches outbound API
        # calls, the generated filename, and Content-Disposition /
        # X-Identifier headers, where a quote character would break out
        # of the quoted filename attribute.
        identifier_type, identifier, document_id = _validate_download_params(
            identifier_type, identifier, document_id
        )

        # Get client IP for rate limiting
        client_ip = _request_client_ip(request)

        # Apply rate limiting
        if not rate_limiter.is_allowed(client_ip):
            return _rate_limited_response(client_ip)

        # Log download request
        logger.info(
            f"Proxying download for {identifier_type} {identifier}, "
            f"doc {document_id}, IP {client_ip}"
        )

        # Get documents for the identifier via the shared proceeding
        # adapter (dup §2.4 fourth copy — previously drifted from main.py).
        # Trials keep the GET convenience endpoint here: it's fast and
        # persistent links carry their own resolved URI.
        from ..api.proceedings import find_in_bag, get_adapter
        adapter = get_adapter(identifier_type)
        if identifier_type == "trial":
            raw_response = await api_client.get_trial_documents(identifier)
        else:
            raw_response = await adapter.fetch_all_documents(api_client, identifier)

        if raw_response.get('error'):
            raise HTTPException(
                status_code=404,
                detail=raw_response.get('error', 'Documents not found')
            )

        if not raw_response.get(adapter.bag_key):
            raise HTTPException(
                status_code=404,
                detail=f'No documents found for {identifier_type} {identifier}'
            )

        # Find target document; keep the parent bag item for metadata
        # (patent number, etc.)
        target_doc, parent_item = find_in_bag(
            raw_response, identifier_type, document_id
        )

        if not target_doc:
            raise HTTPException(
                status_code=404,
                detail=f"Document with ID '{document_id}' not found"
            )

        # Get download URL
        download_url = target_doc.get('fileDownloadURI')
        if not download_url:
            raise HTTPException(
                status_code=404,
                detail="Download URL not available"
            )

        # One implementation, shared with tools/documents.py (D-3): these two
        # had drifted on which bag the appeal category came from, so the same
        # paper could download under two different filenames depending on the
        # route.
        doc_description = derive_document_description(target_doc, parent_item)

        doc_code = target_doc.get('documentCategory', '')

        # Get filing date from document data
        filing_date = target_doc.get('documentFilingDate')

        # Get patent number from parent item's patentOwnerData (trials)
        # or appellantData (appeals) or interferenceMetaData (interferences)
        patent_number = None
        if parent_item:
            if identifier_type == "trial":
                patent_owner_data = parent_item.get('patentOwnerData', {})
                patent_number = patent_owner_data.get('patentNumber')
            elif identifier_type == "appeal":
                appellant_data = parent_item.get('appellantData', {})
                patent_number = appellant_data.get('patentNumber')
            # Interferences typically don't have a single patent number

        # Generate enhanced filename
        filename = generate_enhanced_filename(
            filing_date=filing_date,
            identifier=identifier,
            patent_number=patent_number,
            document_description=doc_description,
            document_code=doc_code,
            max_desc_length=40
        )

        # Stream the PDF from USPTO API (magic-byte verified, L-9)
        pdf_stream = await _open_upstream_pdf_stream(download_url, api_client.api_key)

        # Set appropriate headers for PDF download
        response_headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Identifier-Type": identifier_type,
            "X-Identifier": identifier,
            "X-Document-ID": document_id,
            "X-Enhanced-Filename": filename
        }

        logger.info(f"Streaming PDF: {filename}")

        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers=response_headers,
            background=BackgroundTask(
                lambda: logger.info(f"Download completed: {filename}")
            )
        )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            logger.error(
                f"USPTO API authentication failed for {identifier_type} "
                f"{identifier}/{document_id}"
            )
            raise HTTPException(
                status_code=502,
                detail="Authentication failed with USPTO API"
            )
        else:
            # Status only — API response bodies stay out of logs
            logger.error(f"USPTO API error {e.response.status_code}")
            raise HTTPException(
                status_code=502,
                detail=f"USPTO API error: {e.response.status_code}"
            )
    except Exception as e:
        logger.error(
            f"Proxy download failed for {identifier_type} {identifier}/{document_id}: {e}"
        )
        # Never the raw exception: an httpx repr embeds the full upstream URL
        # and a sqlite error embeds the database path. The request id is the
        # handle for correlating with the (sanitized) server log.
        raise HTTPException(
            status_code=500,
            detail=f"Download failed (request {generate_request_id()})"
        )


def _register_document_download_route(app: FastAPI) -> None:
    """Register the machine-facing document download route (Q-1 split; route unchanged)."""
    app.add_api_route(
        "/download/{identifier_type}/{identifier}/{document_id}",
        download_document,
        methods=["GET"],
        dependencies=[Depends(_check_proxy_token)],
    )


def _register_rate_limit_route(app: FastAPI) -> None:
    """Register the rate-limit status route (Q-1 split; route unchanged)."""
    # The one machine-facing route that carried neither the proxy token nor a
    # viewer key, while PROXY_TRUSTED_IPS admits everything behind a declared
    # hop. It reports another client's request budget and, before the .get()
    # fix in rate_limiter.py, allocated a permanent dict entry per distinct
    # path segment.
    @app.get("/rate-limit/{client_ip}",
             dependencies=[Depends(_check_proxy_token)])
    async def check_rate_limit(client_ip: str):
        """Check rate limit status for a client IP."""
        return {
            "client_ip": client_ip,
            "remaining_requests": rate_limiter.get_remaining_requests(client_ip),
            "max_requests": rate_limiter.max_requests,
            "time_window": rate_limiter.time_window,
            "reset_time": rate_limiter.get_reset_time(client_ip)
        }


def create_proxy_app(api_key: Optional[str] = None, port: Optional[int] = None) -> FastAPI:
    """
    Create FastAPI application for PTAB document proxy.

    Wiring only: the middleware stack and every route body live in the
    module-level helpers above (Q-1). This function used to contain all of
    them as closures, which put its cyclomatic complexity at 43 against the
    repo's own gate of 10 (pyproject.toml [tool.ruff.lint.mccabe]) and made
    each handler unreachable without building the whole app.

    Args:
        api_key: Optional USPTO API key (from secure storage).
                 If not provided, will attempt to load from environment.
        port: Optional port number for health check response.
              If not provided, reads from PTAB_PROXY_PORT or PROXY_PORT.
    """
    app = FastAPI(
        title="USPTO PTAB Document Proxy",
        description="Secure proxy for USPTO PTAB document downloads",
        version="1.0.0",
        lifespan=create_lifespan(api_key)
    )

    # Store port in app state for health check
    app.state.port = port if port is not None else get_proxy_port()

    _add_proxy_middleware(app)

    _register_health_routes(app)
    _register_persistent_download_route(app)
    _register_registry_routes(app)
    _register_document_download_route(app)
    _register_rate_limit_route(app)

    return app


def run_proxy_cli():
    """CLI entry point for proxy server."""
    import uvicorn
    import sys

    load_env_file()

    from ..config.log_config import setup_logging
    setup_logging()

    default_port = get_proxy_port()
    port = default_port

    # Check for port argument (command line overrides environment variables)
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            logger.warning(f"Invalid port: {sys.argv[1]}, using default {default_port}")
            port = default_port

    logger.info(f"Starting USPTO PTAB Document Proxy on port {port}...")
    logger.info(f"Health check: http://localhost:{port}/")
    logger.info(f"Port {port} (configurable via PTAB_PROXY_PORT or PROXY_PORT)")

    uvicorn.run(
        "ptab_mcp.proxy.server:create_proxy_app",
        factory=True,
        # Loopback default; FASTMCP_HOST enables cross-container topologies
        # where the allowlist sees real (non-loopback) peers (H-1)
        host=os.getenv("FASTMCP_HOST", "127.0.0.1"),
        port=port,
        log_level="info",
        # access lines include request paths, and /download/persistent/{hash}
        # paths embed the link credential
        access_log=False
    )
