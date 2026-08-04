"""Loopback-only proxy that adds LM Studio authentication for Codex OSS mode.

The token is read from the process environment and is never logged or persisted.
"""

from __future__ import annotations

import os
import json
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


UPSTREAM_ORIGIN = os.environ.get(
    "PAMPAPILOT_LMSTUDIO_UPSTREAM_ORIGIN", "http://127.0.0.1:1234"
).rstrip("/")
API_KEY = os.environ.get("LM_STUDIO_API_KEY", "")
LISTEN_PORT = int(os.environ.get("PAMPAPILOT_LMSTUDIO_PROXY_PORT", "1235"))
DEBUG_TOOL_TYPES = os.environ.get("PAMPAPILOT_CODEX_PROXY_DEBUG") == "1"
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward()

    def do_PATCH(self) -> None:  # noqa: N802
        self._forward()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        if DEBUG_TOOL_TYPES and body and self.path.endswith("/responses"):
            try:
                payload = json.loads(body)
                tool_types = [
                    (tool.get("type"), tool.get("name"))
                    for tool in payload.get("tools", [])
                ]
                print(f"Codex tool types: {tool_types}", file=sys.stderr, flush=True)
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "authorization"
        }
        if API_KEY:
            headers["Authorization"] = f"Bearer {API_KEY}"

        request = Request(
            f"{UPSTREAM_ORIGIN}{self.path}",
            data=body,
            headers=headers,
            method=self.command,
        )
        try:
            response = urlopen(request, timeout=600)
        except HTTPError as error:
            response = error

        with response:
            self.send_response(response.status)
            for key, value in response.headers.items():
                if key.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(key, value)
            self.end_headers()
            shutil.copyfileobj(response, self.wfile, length=64 * 1024)


def main() -> None:
    if not API_KEY:
        raise SystemExit("LM_STUDIO_API_KEY is required")
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), ProxyHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
