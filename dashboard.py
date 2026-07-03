"""Local dashboard for the kicktipp bot's results.

A zero-dependency (stdlib only) web server that visualises:

  * the community's position-over-time (bump chart with a Spieltag slider),
    reconstructed from data/ranking_history.jsonl,
  * "crazy" tips — exact hits on lopsided scores and total tendency misses,
    colour-coded, from data/tips_history.jsonl, and
  * a personal section listing every bot tip, whether it came true, and the
    Claude reasoning behind the llm picks (parsed from the launchd log).

    uv run python dashboard.py            # → http://localhost:8765

Re-runs ranking_history.py lazily on /api/refresh so the standings can be
refreshed without restarting the server.

The payload-building logic lives in dashboard_data.py, shared with the
read-only hosted deployment (api/data.py on Vercel — see ADR 0009). This file
only owns the parts that are inherently local: the live Kicktipp re-login on
/api/refresh, and serving the page itself.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard_data import build_payload

ROOT = Path(__file__).parent
WEB_DIR = ROOT / "web"
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))


def _refresh_ranking() -> dict:
    """Live re-scrape of the standings history. Best-effort; returns a status."""
    try:
        from dotenv import load_dotenv
        from kicktipp import KicktippClient
        from ranking_history import build_ranking_history

        load_dotenv()
        client = KicktippClient(
            os.environ["KICKTIPP_EMAIL"],
            os.environ["KICKTIPP_PASSWORD"],
            os.environ["KICKTIPP_COMMUNITY"],
        )
        client.login()
        n = build_ranking_history(client)
        return {"ok": True, "rows": n}
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return {"ok": False, "error": str(exc)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path in ("/", "/index.html"):
            html = (WEB_DIR / "dashboard.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path.startswith("/api/data"):
            self._send_json(build_payload(include_personal=True))
        elif self.path.startswith("/api/refresh"):
            self._send_json(_refresh_ranking())
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # quieten the per-request stderr noise
        pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"kicktipp dashboard → {url}  (Ctrl+C to stop)")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()


if __name__ == "__main__":
    main()
