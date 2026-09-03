"""One source for the browser security headers both ASGI stacks emit.

The process runs two independent web stacks — the FastMCP HTTP surface
(`middleware.py`, raw ASGI) and the download side-car (`proxy/server.py`,
Starlette `BaseHTTPMiddleware`) — and each carried its own
`SecurityHeadersMiddleware` with its own header list. Same name, no shared
type, two places to fix a header (F-8).

The Content-Security-Policy is deliberately NOT here: the two surfaces have
genuinely different policies, because the proxy's `/downloads` page carries an
inline script whose SHA-256 hash is computed from the served bytes at import.
Everything else is identical and lives here.
"""

#: Static headers, in the order both stacks emitted them.
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)

#: Emitted only over TLS. It used to go out unconditionally, including on the
#: plain-HTTP loopback listener, where it is inert in browsers but misleading
#: in an audit and a hazard if the hostname later resolves publicly (PT-32).
HSTS_HEADER: tuple[str, str] = (
    "Strict-Transport-Security",
    "max-age=31536000; includeSubDomains",
)


def is_tls(scheme: str, forwarded_proto: str = "") -> bool:
    """True when the request arrived over TLS, directly or via a declared hop."""
    if scheme == "https":
        return True
    return forwarded_proto.split(",")[0].strip().lower() == "https"
