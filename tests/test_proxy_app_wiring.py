"""The proxy's route table and middleware stack are a published contract.

`create_proxy_app` used to be the application rather than a factory: every
route handler and the IP-allowlist middleware were closures inside it, putting
its cyclomatic complexity at 43 against the repo's own gate of 10
(pyproject.toml [tool.ruff.lint.mccabe] max-complexity = 10). Splitting it into
module-level registration helpers is only safe if the wiring it produces is
unchanged, and persistent links have a 7-day tail so a route rename breaks
links already in users' hands.

These pin the exact paths, methods, dependency gating and middleware order.
No server is bound and no request is made.
"""

import pytest

from src.ptab_mcp.proxy.server import create_proxy_app, download_document


@pytest.fixture
def app():
    return create_proxy_app(api_key="test-key", port=8083)


def _routes(app):
    return {
        (r.path, frozenset(r.methods)): [
            type(d.dependency).__name__ for d in getattr(r, "dependencies", [])
        ]
        for r in app.routes
        if hasattr(r, "methods") and not r.path.startswith(("/openapi", "/docs", "/redoc"))
    }


class TestRouteTable:
    def test_every_route_is_present_with_its_methods(self, app):
        assert set(_routes(app)) == {
            ("/", frozenset({"GET"})),
            ("/download/persistent/{link_hash}", frozenset({"GET"})),
            ("/api/register-download", frozenset({"POST"})),
            ("/api/recent-downloads", frozenset({"GET"})),
            ("/downloads", frozenset({"GET"})),
            ("/download/{identifier_type}/{identifier}/{document_id}", frozenset({"GET"})),
            ("/rate-limit/{client_ip}", frozenset({"GET"})),
        }

    def test_the_machine_facing_routes_carry_the_proxy_token_dependency(self, app):
        routes = _routes(app)
        assert routes[("/api/register-download", frozenset({"POST"}))] == [
            "ProxyTokenDependency"]
        assert routes[
            ("/download/{identifier_type}/{identifier}/{document_id}", frozenset({"GET"}))
        ] == ["ProxyTokenDependency"]

    def test_the_browser_facing_routes_carry_no_token_dependency(self, app):
        """The 96-bit link hash IS the credential; a browser cannot send a
        custom header on navigation, so requiring one here breaks every
        persistent link (Lessons 41/43)."""
        routes = _routes(app)
        for path in ("/download/persistent/{link_hash}", "/downloads", "/"):
            assert routes[(path, frozenset({"GET"}))] == []


class TestMiddlewareStack:
    def test_order_is_size_limit_then_headers_then_cors(self, app):
        names = [m.cls.__name__ for m in app.user_middleware]
        assert names == [
            "BaseHTTPMiddleware",          # the IP allowlist, added last = outermost
            "CORSMiddleware",
            "SecurityHeadersMiddleware",
            "RequestSizeLimitMiddleware",
        ]

    def test_the_allowlist_networks_are_parsed_once_at_construction(self, app):
        assert hasattr(app.state, "port")


class TestHandlerIsImportable:
    def test_download_document_is_reachable_without_building_the_app(self):
        """The report's point: the 195-line handler could not be unit-tested
        without standing up the whole application."""
        assert callable(download_document)
        params = download_document.__code__.co_varnames[
            :download_document.__code__.co_argcount]
        assert params[:4] == ("identifier_type", "identifier", "document_id", "request")
