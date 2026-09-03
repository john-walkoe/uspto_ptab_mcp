"""Host allowlist for the outbound USPTO API key.

httpx strips only `Authorization` and `Cookie` when a response redirects away
from the origin (`_client.py::_redirect_headers`). The ODP key travels in
`X-API-KEY`, so with `follow_redirects=True` it reached whatever host the
302 named — including the S3 signed URLs the document endpoints redirect to,
which do not need it. The key is shared by all four USPTO MCPs.

`strip_api_key_off_uspto` is an httpx *request* event hook. httpx runs the
request hooks once per hop inside `_send_handling_redirects`, so one hook
covers both the initial send (validating the host before the key is
attached) and every redirect after it.
"""

from urllib.parse import urlsplit

#: Header names that carry the ODP key. httpx headers are case-insensitive,
#: so one spelling is enough, but the tuple documents both in-repo spellings.
API_KEY_HEADERS = ("X-API-KEY",)

#: Only https on uspto.gov (or a subdomain) may receive the key.
_ALLOWED_HOST_SUFFIX = ".uspto.gov"
_ALLOWED_HOST = "uspto.gov"


def is_uspto_url(url) -> bool:
    """True when `url` is an https URL on a uspto.gov host."""
    parts = urlsplit(str(url))
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return host == _ALLOWED_HOST or host.endswith(_ALLOWED_HOST_SUFFIX)


async def strip_api_key_off_uspto(request) -> None:
    """httpx request event hook: drop the ODP key before any hop that is not
    https on uspto.gov."""
    if not is_uspto_url(request.url):
        for header in API_KEY_HEADERS:
            request.headers.pop(header, None)


#: Ready-made `event_hooks=` value for an httpx client that sends the key.
USPTO_KEY_EVENT_HOOKS = {"request": [strip_api_key_off_uspto]}
