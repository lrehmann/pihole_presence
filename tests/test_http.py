"""Exercise complete polls against an isolated local HTTP server."""

from __future__ import annotations

from datetime import datetime, timezone

import aiohttp
import pytest
from aiohttp import web

from custom_components.pihole_presence import coordinator as module


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["v6", "v6_authenticated", "legacy"])
async def test_real_http_poll_and_session_cleanup(hass, monkeypatch, api):
    requests = []
    now = datetime.now(timezone.utc).timestamp()

    async def handler(request):
        requests.append((request.method, request.path, dict(request.query)))
        assert request.headers.get("Connection") == "close"
        if api == "legacy":
            if request.path != "/admin/api_db.php":
                raise web.HTTPNotFound()
            assert request.query["auth"] == "test-token"
            return web.json_response(
                {
                    "network": [
                        {
                            "hwaddr": "aa:bb:cc:dd:ee:02",
                            "lastQuery": str(now),
                            "ip": ["192.168.1.20"],
                            "name": ["test-device"],
                        }
                    ]
                }
            )
        if request.path == "/api/auth" and request.method == "POST":
            assert await request.json() == {"password": "test-password"}
            return web.json_response(
                {"session": {"valid": True, "sid": "test-session", "validity": 300}}
            )
        if api == "v6_authenticated":
            assert request.headers.get("X-FTL-SID") == "test-session"
        if request.path == "/api/auth" and request.method == "DELETE":
            return web.Response(status=204)
        if request.path == "/api/network/devices":
            assert request.query["max_devices"] == "999"
            return web.json_response(
                {
                    "devices": [
                        {
                            "hwaddr": "aa:bb:cc:dd:ee:02",
                            "lastQuery": now - 500,
                            "ips": [{"ip": "192.168.1.20", "name": "test-device"}],
                        }
                    ]
                }
            )
        if request.path == "/api/queries":
            return web.json_response(
                {
                    "queries": [{"time": now, "client": {"ip": "192.168.1.20"}}],
                    "cursor": 0,
                }
            )
        # Optional endpoints are absent on this simulated server.
        raise web.HTTPNotFound()

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            monkeypatch.setattr(module, "async_get_clientsession", lambda _: session)
            client = module.PiholeUpdateCoordinator(
                hass,
                f"http://127.0.0.1:{port}/admin/",
                30,
                30,
                password="test-password" if api == "v6_authenticated" else "",
                api_token="test-token",
            )
            try:
                for _ in range(2):
                    data = await client._async_update_data()
                    assert data["aa:bb:cc:dd:ee:02"]["last_query"] == now
            finally:
                await client.async_close()
            assert not session.closed
    finally:
        await runner.cleanup()
    if api == "v6_authenticated":
        assert sum(method == "POST" for method, _, _ in requests) == 1
        assert sum(method == "DELETE" for method, _, _ in requests) == 1
    if api == "legacy":
        assert sum(path == "/api/network/devices" for _, path, _ in requests) == 1
