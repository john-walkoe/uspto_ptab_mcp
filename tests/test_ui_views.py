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
    assert non_deferred == {"search_trials_minimal", "ptab_get_guidance", "ptab_get_documents"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
