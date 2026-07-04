"""Vercel Python Function: GET /api/data — community-only dashboard payload.

Reuses dashboard_data.build_payload(include_personal=False), the same logic
the local dashboard.py uses for the full payload. See ADR 0009.
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard_data import build_payload  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        # A bare 500 with no body is nearly impossible to debug from outside
        # the Vercel function logs, so surface the real traceback in the
        # response instead of letting it bubble up as FUNCTION_INVOCATION_FAILED.
        try:
            body = json.dumps(build_payload(include_personal=False), ensure_ascii=False).encode("utf-8")
        except Exception:  # noqa: BLE001 - deliberately broad, see comment above
            body = traceback.format_exc().encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # quieten the per-request stderr noise
        pass
