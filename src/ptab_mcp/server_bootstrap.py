"""Server bootstrap: proxy lifecycle + transport entry points (SD-1 split).

Owns the background download-proxy task (start, supervision, health), PFW
centralized-proxy detection, and the stdio/HTTP entry points. Imports the
composition root lazily inside functions — main.py imports this module for
its entry-point re-exports.
"""

import asyncio
import contextlib
import os
import re
import time
from typing import Optional

import requests

from .middleware import (
    APIKeyAuthMiddleware,
    SecurityHeadersMiddleware,
    _StreamableHTTPProbeMiddleware,
)
from .proxy.centralized_integration import get_centralized_base_url
from .runtime import settings
from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# Startup/probe timing (RN-3: named instead of scattered literals)
_PROXY_STARTUP_GRACE_SECONDS = 0.5   # give uvicorn a beat to bind before probing
_PROXY_HEALTH_TIMEOUT_SECONDS = 1.0  # local proxy health probe
_PFW_PROBE_TIMEOUT_SECONDS = 2.0     # centralized PFW proxy detection probe

# Global state for proxy server management
_proxy_server_running = False
_proxy_server_task = None
_proxy_startup_lock = asyncio.Lock()  # Prevents concurrent proxy startup attempts


def get_local_proxy_port() -> int:
    """
    Safely parse local proxy port from environment variables.

    Checks PTAB_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic).
    Handles special value "none" which indicates no proxy configured.

    Delegates to the single implementation in proxy/server.py (dedup 1.1).

    Returns:
        int: Proxy port number (default: 8083)
    """
    from .proxy.server import get_proxy_port
    return get_proxy_port()


def _on_proxy_task_done(task: "asyncio.Task") -> None:
    """Supervision hook for the background proxy task (EH-2/RF-2).

    Without this, a proxy that dies after startup leaves
    _proxy_server_running stuck True and the failure invisible — tools keep
    emitting download URLs that no longer work.
    """
    global _proxy_server_running
    _proxy_server_running = False
    if task.cancelled():
        logger.info("Proxy server task cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"Proxy server task died: {type(exc).__name__}: {exc}")
    else:
        logger.warning("Proxy server task exited unexpectedly (no exception)")


def _asyncio_exception_handler(loop, context):
    """Loop-level safety net for uncaught background-task exceptions (EH-9).

    Routes them through our stderr logger — critical in stdio MCP mode,
    where stray output on stdout would corrupt the protocol stream.
    """
    exc = context.get("exception")
    message = context.get("message", "Unhandled asyncio exception")
    if exc is not None:
        logger.error(f"Unhandled asyncio exception: {message}: {type(exc).__name__}: {exc}")
    else:
        logger.error(f"Unhandled asyncio exception: {message}")



def _port_serves_healthy_proxy(port: int) -> bool:
    """True when a PTAB download proxy already answers on the port."""
    try:
        response = requests.get(
            f"http://localhost:{port}/", timeout=_PROXY_HEALTH_TIMEOUT_SECONDS
        )
        return (
            response.status_code == 200
            and response.json().get("service") == "PTAB Document Proxy"
        )
    except Exception:
        return False


async def _run_proxy_server(port: int = 8083):
    """
    Run the FastAPI proxy server.

    Uses API key from Settings (which may come from secure storage or environment variables).
    """
    try:
        import uvicorn
        from .proxy.server import create_proxy_app

        # Pass API key and port from Settings to proxy server
        # This allows proxy to work with secure storage (Windows DPAPI)
        app = create_proxy_app(api_key=settings.uspto_api_key, port=port)
        # Loopback default; FASTMCP_HOST enables cross-container topologies
        # where the proxy's IP allowlist sees real (non-loopback) peers (H-1)
        proxy_host = os.getenv("FASTMCP_HOST", "127.0.0.1")
        config = uvicorn.Config(
            app,
            host=proxy_host,
            port=port,
            log_level="info",
            access_log=False  # Reduce noise in logs
        )
        server = uvicorn.Server(config)
        logger.info(f"HTTP proxy server starting on http://{proxy_host}:{port}")
        await server.serve()

    except SystemExit as e:
        # uvicorn calls sys.exit(1) on startup failure (e.g. port already in
        # use). SystemExit is a BaseException: uncaught it would tear down
        # the whole event loop instead of just this task. Convert it so the
        # supervision done-callback (EH-2) handles it like any other death.
        global _proxy_server_running
        _proxy_server_running = False
        raise RuntimeError(
            f"Proxy server failed to start on port {port} "
            f"(exit {e.code}; port already in use?)"
        ) from e
    except Exception as e:
        _proxy_server_running = False
        logger.error(f"Proxy server failed: {e}")
        raise


async def _ensure_local_proxy_running(port: int = None) -> bool:
    """
    Ensure the local proxy server is running (on-demand startup).

    This function is called when:
    - ENABLE_ALWAYS_ON_PROXY=false (on-demand mode)
    - Centralized proxy is unavailable
    - A document download is requested

    Thread-safe: Uses asyncio.Lock to prevent concurrent startup attempts.

    Args:
        port: Port number for proxy server (default: from get_local_proxy_port())

    Returns:
        True if proxy is running (already running or successfully started)
    """
    global _proxy_server_running, _proxy_server_task

    # Fast path: already running
    if _proxy_server_running:
        return True

    # Use lock to prevent concurrent startup attempts
    async with _proxy_startup_lock:
        # Double-check after acquiring lock (another task may have started it)
        if _proxy_server_running:
            return True

        # Determine port
        if port is None:
            port = get_local_proxy_port()

        # Another PTAB instance may already serve this port (e.g. an agent's
        # always-on stdio server on the same box). If a healthy PTAB proxy
        # answers, reuse it instead of failing to bind — persistent links
        # carry their own resolved URI, so any instance can stream them.
        if _port_serves_healthy_proxy(port):
            logger.info(
                f"Port {port} already serves a healthy PTAB proxy — reusing it"
            )
            _proxy_server_running = True
            return True

        try:
            logger.info(f"📦 On-demand proxy startup: Starting local proxy on port {port}")
            _proxy_server_task = asyncio.create_task(_run_proxy_server(port))
            # Supervise: a task that dies later clears the running flag (EH-2)
            _proxy_server_task.add_done_callback(_on_proxy_task_done)
            _proxy_server_running = True

            # Brief wait to ensure server starts cleanly
            await asyncio.sleep(_PROXY_STARTUP_GRACE_SECONDS)

            # Verify proxy is responding
            import requests
            try:
                response = requests.get(f"http://localhost:{port}/", timeout=_PROXY_HEALTH_TIMEOUT_SECONDS)
                if response.status_code == 200:
                    logger.info(f"✅ On-demand proxy started successfully on port {port}")
                    return True
            except Exception as e:
                # Signal unverified startup to the caller (EH-5) — the task
                # may still bind late, so the running flag stays True and the
                # done-callback clears it if the task actually died.
                logger.warning(f"Proxy started but health check failed: {e}")
                return False

        except Exception as e:
            logger.error(f"❌ Failed to start on-demand proxy: {e}")
            _proxy_server_running = False
            return False

    return _proxy_server_running


def _detect_pfw_proxy() -> Optional[str]:
    """
    Detect if the USPTO PFW MCP proxy is available for centralized downloads.

    Resolution comes from get_centralized_base_url():
    - CENTRALIZED_PROXY_URL (full base URL — Docker hostnames or remote HTTPS)
    - CENTRALIZED_PROXY_PORT (legacy, resolved against localhost)
    - Neither / "none": skip HTTP checks entirely (instant startup)

    Fallback: probe the default PFW port 8080 with retry logic.

    Returns:
        PFW proxy base URL if available, None otherwise
    """
    logger.info("🔍 Checking for centralized USPTO PFW MCP proxy...")

    # INSTANT DETECTION: honor explicit configuration first
    centralized_base_url = get_centralized_base_url()

    # get_centralized_base_url() already folds CENTRALIZED_PROXY_URL and the
    # legacy CENTRALIZED_PROXY_PORT into one answer (RN-4) — None means the
    # PFW proxy is explicitly not configured.
    if centralized_base_url is None:
        # PFW explicitly not configured - skip all HTTP checks (instant startup)
        logger.info("ℹ️  Standalone mode: Using local PTAB proxy (always-on)")
        logger.info("   💡 Configure CENTRALIZED_PROXY_URL to use the PFW centralized proxy:")
        logger.info("      - Unified rate limiting and cross-MCP document sharing")
        logger.info("      - Docker: http://pfw:8080 · Remote: external HTTPS base")
        return None

    # If explicitly configured, probe it first
    if centralized_base_url:
        try:
            response = requests.get(f"{centralized_base_url}/", timeout=_PFW_PROBE_TIMEOUT_SECONDS)
            if response.status_code == 200:
                logger.info("🎯 SUCCESS: Using centralized USPTO proxy ecosystem")
                logger.info(f"   ✅ Detected PFW proxy at {centralized_base_url}")
                logger.info("   ✅ Persistent links available")
                logger.info("   ✅ Enhanced rate limiting")
                logger.info("   ✅ Cross-MCP document sharing")
                return centralized_base_url
        except Exception:
            logger.warning(
                f"   ⚠️  Centralized proxy configured ({centralized_base_url}) "
                "but not responding"
            )

    # Optimized retry configuration for fast startup
    max_retries = 3
    retry_delay = 1.0  # seconds
    timeout = 1.0  # seconds

    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"   Retry {attempt}/{max_retries-1} (waiting for PFW proxy to start)...")
            time.sleep(retry_delay)

        # Check if PFW proxy is running on port 8080 (primary port)
        try:
            pfw_base = "http://localhost:8080"
            response = requests.get(f"{pfw_base}/", timeout=timeout)
            if response.status_code == 200:
                data = response.json()
                if "Patent File Wrapper Proxy" in data.get("service", ""):
                    logger.info("🎯 SUCCESS: Detected PFW centralized proxy on port 8080")
                    logger.info("   ✅ Persistent links available")
                    logger.info("   ✅ Enhanced rate limiting")
                    logger.info("   ✅ Cross-MCP document sharing")
                    os.environ['CENTRALIZED_PROXY_PORT'] = '8080'
                    return pfw_base
        except Exception as probe_error:
            # Absence of the PFW proxy is the normal standalone case, so this
            # is not a warning — but at `pass` a misconfigured
            # CENTRALIZED_PROXY_URL was undiagnosable (EH-8).
            logger.debug(
                "PFW proxy probe failed: %s", type(probe_error).__name__
            )

    # PFW not detected - use standalone mode
    logger.info("ℹ️  Standalone mode: Using local PTAB proxy (always-on)")
    logger.info("   💡 Configure CENTRALIZED_PROXY_URL for the PFW centralized proxy")
    return None


async def run_hybrid_server(enable_always_on: bool = True, proxy_port: int = 8083):
    """
    Run both MCP server and HTTP proxy server concurrently.

    Args:
        enable_always_on: If True, start proxy immediately (default)
        proxy_port: Port for the HTTP proxy server (default: 8083)
    """
    try:
        global _proxy_server_running, _proxy_server_task

        # Loop-level safety net for background-task exceptions (EH-9)
        asyncio.get_running_loop().set_exception_handler(_asyncio_exception_handler)

        # Detect PFW proxy with retry logic
        _detect_pfw_proxy()

        from . import main as _main  # lazy: composition root imports us
        mcp = _main.mcp

        # Start both servers concurrently
        logger.info("Starting hybrid PTAB MCP + HTTP proxy server")

        # Run MCP server in a separate task
        mcp_task = asyncio.create_task(
            asyncio.to_thread(lambda: mcp.run(transport='stdio'))
        )

        # Start proxy server immediately if always-on mode is enabled
        if enable_always_on:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                port_free = s.connect_ex(("127.0.0.1", proxy_port)) != 0

            # A TCP listener is not proof that OUR proxy is there. Verify the
            # service by name the way the on-demand path already does: setting
            # _proxy_server_running on a bare connect made the document tools
            # mint persistent-link URLs (which are bearer credentials) addressed
            # to whatever else happens to hold the port, and POST the download
            # registration plus X-Proxy-Token to it.
            if not port_free and _port_serves_healthy_proxy(proxy_port):
                logger.info(
                    "Port %d already serves a healthy PTAB proxy — reusing it "
                    "(MCP tools are fully available)",
                    proxy_port,
                )
                _proxy_server_running = True
            elif not port_free:
                logger.error(
                    "Port %d is held by a service that is not a PTAB download "
                    "proxy; not starting one and not emitting download links. "
                    "Free the port or set PTAB_PROXY_PORT.",
                    proxy_port,
                )
                _proxy_server_running = False
            else:
                logger.info(f"Always-on mode: Starting HTTP proxy server on port {proxy_port}")
                _proxy_server_task = asyncio.create_task(_run_proxy_server(proxy_port))
                _proxy_server_task.add_done_callback(_on_proxy_task_done)
                _proxy_server_running = True
                # Brief wait to ensure server starts cleanly
                await asyncio.sleep(_PROXY_STARTUP_GRACE_SECONDS)
                logger.info(f"Proxy server started successfully on port {proxy_port}")
        else:
            logger.info("On-demand mode: Proxy will start on first document request")

        # Wait for MCP server to complete (it runs indefinitely)
        await mcp_task

    except KeyboardInterrupt:
        logger.info("Shutting down servers...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        # The proxy task was never cancelled on the way out, so an in-flight PDF
        # stream was dropped mid-transfer and stream_body()'s finally — which
        # releases the cross-process shared rate-limiter slot — might not run.
        if _proxy_server_task is not None and not _proxy_server_task.done():
            _proxy_server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _proxy_server_task
        _proxy_server_running = False


# ==========================================
# SERVER ENTRY POINT
# ==========================================

def run_server():
    """
    Entry point for the ptab-mcp command.
    Called by: uv run ptab-mcp

    Transport is controlled by FASTMCP_TRANSPORT:
      FASTMCP_TRANSPORT=stdio  (default) — Claude Desktop / Claude Code compatible
      FASTMCP_TRANSPORT=http             — HTTP mode for Docker, reverse proxy, basic-host

    HTTP mode environment variables:
      FASTMCP_HOST=0.0.0.0        Bind address (default: 127.0.0.1)
      FASTMCP_PORT=8765           Port (default: 8000; 8765 recommended on Windows —
                                  8000 falls in the Hyper-V/WSL reserved range)
      CORS_EXTRA_ORIGIN=https://… Additional CORS origins beyond localhost (comma-separated)
      INTERNAL_AUTH_SECRET        Required — X-API-KEY auth for all non-health requests

    STDIO mode environment variables:
      ENABLE_ALWAYS_ON_PROXY=true Start download proxy at startup vs on-demand (default: true)
      PTAB_PROXY_PORT=8083        Document proxy port (default: 8083)
    """
    from . import main as _main  # composition root (lazy: avoids circular import)
    mcp = _main.mcp
    _AUTH_PROVIDER = _main._AUTH_PROVIDER

    transport = os.getenv("FASTMCP_TRANSPORT", "stdio")

    if transport == "http":
        # HTTP mode — for Docker, reverse proxy, or basic-host testing

        # Fail fast if INTERNAL_AUTH_SECRET is missing — open-access HTTP is a
        # misconfiguration. In STDIO mode this is fine (local process only).
        # In OAuth mode the surface is bearer-protected by FastMCP instead, so
        # the shared-secret guard (and this check) is skipped.
        if _AUTH_PROVIDER is None:
            from .shared_secure_storage import get_internal_auth_secret
            _auth_secret_check = get_internal_auth_secret() or os.environ.get("INTERNAL_AUTH_SECRET")
            if not _auth_secret_check:
                logger.error(
                    "INTERNAL_AUTH_SECRET is required for HTTP transport mode. "
                    "Set it as an environment variable or store it via the key management system. "
                    "Refusing to start an unauthenticated HTTP server."
                )
                raise SystemExit(1)

        host = os.getenv("FASTMCP_HOST", "127.0.0.1")
        port = int(os.getenv("FASTMCP_PORT", "8000"))

        # Build CORS origins list
        origins = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
        extra_origins = os.getenv("CORS_EXTRA_ORIGIN", "")
        for o in extra_origins.split(","):
            o = o.strip()
            if not o:
                continue
            if not re.match(r"^https?://[a-zA-Z0-9.\-]+(:[0-9]+)?$", o):
                raise ValueError(f"CORS_EXTRA_ORIGIN must be a valid HTTP/HTTPS URL, got: {o}")
            origins.append(o)
            logger.info(f"CORS: added extra origin {o}")

        try:
            from starlette.middleware.cors import CORSMiddleware
            import uvicorn
            from .proxy.server import RequestSizeLimitMiddleware
            # Middleware stack (outermost first): Probe → SecurityHeaders → APIKeyAuth → SizeLimit → CORS → mcp app
            # Probe must be outermost — intercepts claude.ai format probes before auth runs.
            # Security headers wrap everything so they appear on 401 responses too.
            # SizeLimit caps tool-call JSON bodies (M-3) — Content-Length AND
            # a running byte count, so chunked transfer can't bypass it.
            inner = RequestSizeLimitMiddleware(CORSMiddleware(
                mcp.http_app(stateless_http=settings.fastmcp_stateless_http),
                allow_origins=origins,
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "Accept", "Mcp-Session-Id"],
                expose_headers=["Mcp-Session-Id"],
            ))
            if _AUTH_PROVIDER is not None:
                # OAuth mode: FastMCP's bearer middleware guards /mcp (401 +
                # WWW-Authenticate — which already gives claude.ai's format
                # probe the 401 it needs, so the probe shim is redundant), and
                # the OAuth routes (/authorize, /token, /register, /auth/*,
                # /.well-known/*) must be reachable without a shared secret.
                # Headless clients present PTAB_AUTH_INTERNAL_TOKEN as bearer.
                logger.warning(
                    "PTAB_AUTH_MODE=oauth: x-api-key guard and probe shim "
                    "disabled; the MCP surface is protected by bearer tokens."
                )
                app = SecurityHeadersMiddleware(inner)
            else:
                app = _StreamableHTTPProbeMiddleware(
                    SecurityHeadersMiddleware(APIKeyAuthMiddleware(inner))
                )
            # Start the download proxy in a background daemon thread (Lesson 35).
            # uvicorn.run() blocks, so the STDIO asyncio-task pattern never fires
            # here — each thread gets its own event loop via asyncio.run().
            _proxy_port_http = get_local_proxy_port()
            _enable_proxy_http = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"
            if _enable_proxy_http:
                import threading

                def _proxy_thread_target():
                    try:
                        asyncio.run(_run_proxy_server(_proxy_port_http))
                    except Exception as thread_exc:
                        # Thread-level supervision (EH-2): without this the
                        # daemon thread dies silently
                        global _proxy_server_running
                        _proxy_server_running = False
                        logger.error(
                            f"Download proxy thread died: {type(thread_exc).__name__}: {thread_exc}"
                        )
                _pt = threading.Thread(target=_proxy_thread_target, daemon=True, name="download-proxy")
                _pt.start()
                logger.info(f"Download proxy server starting on port {_proxy_port_http} (background thread)")
            logger.info(f"Starting HTTP transport on {host}:{port} (CORS origins: {origins})")
            # access_log off: access lines include request paths, and
            # /download/persistent/{hash} paths embed the link credential
            uvicorn.run(app, host=host, port=port, access_log=False)
        except ImportError as e:
            raise ImportError(
                f"HTTP transport requires uvicorn and starlette: {e}. "
                "Run: uv add uvicorn starlette"
            )
    else:
        # STDIO mode (default) — Claude Desktop / Claude Code
        # Check if always-on proxy should be enabled (default: true)
        enable_always_on = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"

        # Get local proxy port
        default_port = get_local_proxy_port()

        # Run hybrid server with proxy
        asyncio.run(run_hybrid_server(enable_always_on=enable_always_on, proxy_port=default_port))


if __name__ == "__main__":
    run_server()
