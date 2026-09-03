"""The always-on proxy startup path must verify WHOSE proxy holds the port.

`run_hybrid_server` treated a successful TCP connect on the proxy port as proof
that a PTAB download proxy was there and set `_proxy_server_running = True`.
Anything bound to 8083 satisfied that. The document tools then minted
`http://localhost:8083/download/persistent/{hash}` URLs — each hash IS the
bearer credential for that document — addressed to the foreign listener, and
`_register_download_via_proxy` POSTed the registration plus `X-Proxy-Token` to
it. The on-demand path already answered this correctly with
`_port_serves_healthy_proxy`, which fetches `/` and checks the service name.

These drive the decision helper directly rather than standing up a server; no
socket is opened and no network call is made.
"""

import pytest

from src.ptab_mcp import server_bootstrap


@pytest.fixture(autouse=True)
def reset_flag():
    server_bootstrap._proxy_server_running = False
    yield
    server_bootstrap._proxy_server_running = False


class TestPortOccupantVerification:
    def test_a_foreign_listener_is_not_a_ptab_proxy(self, monkeypatch):
        """Any 200 whose body does not name the service must not count."""
        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"service": "Some Other Service"}

        monkeypatch.setattr(server_bootstrap.requests, "get", lambda *a, **k: _Resp())

        assert server_bootstrap._port_serves_healthy_proxy(8083) is False

    def test_a_non_json_body_is_not_a_ptab_proxy(self, monkeypatch):
        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                raise ValueError("not json")

        monkeypatch.setattr(server_bootstrap.requests, "get", lambda *a, **k: _Resp())

        assert server_bootstrap._port_serves_healthy_proxy(8083) is False

    def test_our_own_proxy_is_recognized(self, monkeypatch):
        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"service": "PTAB Document Proxy"}

        monkeypatch.setattr(server_bootstrap.requests, "get", lambda *a, **k: _Resp())

        assert server_bootstrap._port_serves_healthy_proxy(8083) is True

    def test_the_always_on_path_consults_the_health_check(self):
        """The busy-port branch must call _port_serves_healthy_proxy, not just
        report the port as in use. Guards against a revert to the bare
        connect_ex test, which is the whole defect."""
        import inspect

        source = inspect.getsource(server_bootstrap.run_hybrid_server)
        busy_branch = source.split("port_free = s.connect_ex")[1]
        assert "_port_serves_healthy_proxy(proxy_port)" in busy_branch
        # And the negative branch must refuse rather than pretend
        assert "_proxy_server_running = False" in busy_branch
