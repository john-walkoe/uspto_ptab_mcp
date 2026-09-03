"""
Sanity tests for MCP App HTML views and their registration.

These are structural checks — real rendering is validated manually in
Claude Desktop via tests/TEST_SUITE.md.
"""

import asyncio
from pathlib import Path
import sys

import pytest

# Add src to path (matches the other test modules)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ptab_mcp.ui import SEARCH_RESULTS_HTML, DOWNLOADS_HTML


@pytest.mark.parametrize("html", [SEARCH_RESULTS_HTML, DOWNLOADS_HTML],
                         ids=["search", "downloads"])
def test_view_structure(html):
    """Views carry the load-bearing MCP App patterns."""
    assert html.strip().startswith("<!DOCTYPE html>")
    # Lesson 2: light color scheme pinned so Claude's dark mode doesn't invert
    assert "color-scheme: light" in html
    # ext-apps SDK from jsDelivr — the only allowed script CDN in the CSP
    assert "cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0" in html
    # ontoolresult must be registered BEFORE connect() (textual order check)
    assert html.index("app.ontoolresult") < html.index("app.connect()")
    # Lesson 24: navigation via app.openLink, never bare window.open only
    assert "app.openLink" in html


def test_search_view_handles_all_proceeding_types():
    """The search view normalizes all three data_type shapes."""
    for marker in ("trialNumber", "appealNumber", "interferenceNumber",
                   "patents.google.com"):
        assert marker in SEARCH_RESULTS_HTML


def test_views_registered_as_resources():
    """Both ui:// resources are registered; 14 tools register by default.

    ptab_manage_users is registration-gated by PTAB_ENABLE_USER_MANAGEMENT
    (default off), so the default (stdio/plain-HTTP) tool count is 14 — the
    15th appears only when the flag is set (see test_user_management_gate).
    """
    from ptab_mcp.main import mcp

    resources = asyncio.run(mcp.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "ui://ptab/search-results.html" in uris
    assert "ui://ptab/recent-downloads.html" in uris

    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    assert len(tools) == 14
    assert "ptab_manage_users" not in tool_names

    # defer_loading contract: exactly the three always-available tools are
    # non-deferred, matching SERVER_INSTRUCTIONS
    non_deferred = {
        t.name for t in tools
        if t.annotations and getattr(t.annotations, "model_extra", {}).get("defer_loading") is False
    }
    assert non_deferred == {"PTAB_search_trials_minimal", "PTAB_get_guidance", "PTAB_get_documents"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ------------------------------------------------------- PT-02 / PT-23 escaping


@pytest.mark.parametrize("html", [SEARCH_RESULTS_HTML, DOWNLOADS_HTML],
                         ids=["search", "downloads"])
def test_views_define_the_escape_helper(html):
    """Both documents carry the same esc() the user-management view had."""
    assert "function esc(s)" in html
    assert "'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'" in html


@pytest.mark.parametrize(
    "field",
    [
        "p.partyA", "p.partyB", "p.decisionType", "p.status", "p.num",
        "p.patentNum", "p.appNum", "p.artUnit", "p.tc",
    ],
)
def test_search_card_escapes_uspto_authored_fields(field):
    """PT-02: party names and decision types are filer-authored free text."""
    assert f"esc({field})" in SEARCH_RESULTS_HTML
    # and no bare interpolation of the same field survives anywhere
    assert "${" + field + "}" not in SEARCH_RESULTS_HTML


def test_search_card_escapes_title_attributes():
    """An unescaped quote in a title="..." attribute closes the attribute."""
    assert 'title="${esc(p.partyA)}"' in SEARCH_RESULTS_HTML
    assert 'title="${esc(p.partyB)}"' in SEARCH_RESULTS_HTML
    assert 'title="${esc(p.decisionType)}"' in SEARCH_RESULTS_HTML


def test_filter_pill_escapes_its_label():
    """Filter pill labels are party names taken straight from the results."""
    assert "esc(label)" in SEARCH_RESULTS_HTML


@pytest.mark.parametrize(
    "field", ["doc.title", "doc.identifier", "doc.proxy_url"]
)
def test_downloads_card_escapes_document_fields(field):
    assert f"esc({field})" in DOWNLOADS_HTML
    assert "${" + field + "}" not in DOWNLOADS_HTML


def test_recent_download_registration_rejects_non_http_schemes():
    """PT-23: download_url lands in an anchor href on the /downloads page."""
    from pydantic import ValidationError

    from ptab_mcp.proxy.models import RecentDownloadRegistration

    base = dict(
        identifier="IPR2024-01353", identifier_type="trial", document_id="1",
    )
    for bad in ("javascript:alert(1)", "data:text/html,<script>x</script>",
                "file:///etc/passwd", "/relative/path"):
        with pytest.raises(ValidationError):
            RecentDownloadRegistration(download_url=bad, **base)

    for good in ("https://api.uspto.gov/x.pdf",
                 "http://127.0.0.1:8083/download/persistent/abc"):
        assert RecentDownloadRegistration(download_url=good, **base).download_url == good


def test_proxy_downloads_page_escapes_the_registry():
    from ptab_mcp.proxy.server import _DOWNLOADS_PAGE_HTML

    assert "function esc(s)" in _DOWNLOADS_PAGE_HTML
    assert "esc(d.download_url)" in _DOWNLOADS_PAGE_HTML
    assert "${d.download_url}" not in _DOWNLOADS_PAGE_HTML


def test_proxy_csp_hashes_the_downloads_page_inline_script():
    """PT-25: default-src 'self' blocked the page's own script."""
    import base64
    import hashlib
    import re

    from ptab_mcp.proxy.server import (
        _CONTENT_SECURITY_POLICY,
        _DOWNLOADS_PAGE_HTML,
    )

    assert "default-src 'self'" in _CONTENT_SECURITY_POLICY
    assert "script-src 'self' 'unsafe-inline'" not in _CONTENT_SECURITY_POLICY

    bodies = re.findall(
        r"<script[^>]*>(.*?)</script>", _DOWNLOADS_PAGE_HTML, re.DOTALL
    )
    assert len(bodies) == 1
    expected = base64.b64encode(
        hashlib.sha256(bodies[0].encode("utf-8")).digest()
    ).decode("ascii")
    assert f"'sha256-{expected}'" in _CONTENT_SECURITY_POLICY
