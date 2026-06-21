#!/usr/bin/env python3
"""
End-to-end demo for the Image Proxy integration.

With Home Assistant running (``scripts/develop``) and the integration added,
this script:

1. Connects to the HA WebSocket API and authenticates with a long-lived token.
2. Sends an ``image_proxy/register`` command mapping a demo key to a public
   test image URL (public so it passes the SSRF guard with no Sonos present).
3. Prints the ready-to-open img URL and fetches it, showing the served bytes
   and the response headers.

Environment:
    HA_TOKEN   (required) a Home Assistant long-lived access token.
    HA_URL     (optional) base URL, default http://localhost:8123.
    DEMO_SRC   (optional) source image URL, default a public httpbin PNG.
    DEMO_KEY   (optional) cache key, default "demo:httpbin-png".
"""

from __future__ import annotations

import asyncio
import os
import sys

import aiohttp

DEFAULT_URL = "http://localhost:8123"
DEFAULT_SRC = "https://httpbin.org/image/png"
DEFAULT_KEY = "demo:httpbin-png"


def _token_or_exit() -> str:
    """Return HA_TOKEN or print setup instructions and exit non-zero."""
    token = os.environ.get("HA_TOKEN")
    if not token:
        print("HA_TOKEN is not set.")
        print()
        print("Create a long-lived access token in Home Assistant:")
        print("  Profile (bottom-left) > Security > Long-lived access tokens")
        print("Then run, for example:")
        print('  HA_TOKEN="<your token>" ./scripts/demo')
        sys.exit(1)
    return token


async def _register(
    session: aiohttp.ClientSession, base: str, token: str, key: str, src: str
) -> None:
    """Open the WS API, authenticate, and send one register command."""
    ws_url = base.replace("http://", "ws://").replace("https://", "wss://")
    async with session.ws_connect(f"{ws_url}/api/websocket") as ws:
        # auth handshake: receive auth_required, send token, expect auth_ok.
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        auth = await ws.receive_json()
        if auth.get("type") != "auth_ok":
            print(f"Authentication failed: {auth}")
            sys.exit(1)

        await ws.send_json(
            {
                "id": 1,
                "type": "image_proxy/register",
                "items": [{"key": key, "src": src}],
            }
        )
        result = await ws.receive_json()
        print(f"register -> {result.get('result', result)}")


async def _fetch(session: aiohttp.ClientSession, img_url: str) -> None:
    """GET the img URL and print status, headers, and byte count."""
    async with session.get(img_url) as resp:
        body = await resp.read()
        print(f"GET {img_url}")
        print(f"  status:        {resp.status}")
        print(f"  Content-Type:  {resp.headers.get('Content-Type')}")
        print(f"  Cache-Control: {resp.headers.get('Cache-Control')}")
        print(f"  ETag:          {resp.headers.get('ETag')}")
        print(f"  bytes:         {len(body)}")


async def _main() -> None:
    """Run the register + fetch demo."""
    token = _token_or_exit()
    base = os.environ.get("HA_URL", DEFAULT_URL).rstrip("/")
    src = os.environ.get("DEMO_SRC", DEFAULT_SRC)
    key = os.environ.get("DEMO_KEY", DEFAULT_KEY)
    img_url = f"{base}/api/image_proxy/img/{key}"

    async with aiohttp.ClientSession() as session:
        await _register(session, base, token, key, src)
        # Give the background warm task a moment to fetch the blob.
        await asyncio.sleep(1.0)
        print()
        print(f"Open this URL from an allowlisted client:\n  {img_url}")
        print()
        await _fetch(session, img_url)


if __name__ == "__main__":
    asyncio.run(_main())
