"""Minimal Python stand-in for the Nginx gateway, ONLY for running without Docker.
Routes /api/... to the right service exactly like gateway/nginx.conf does."""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

ROUTES = [  # (path prefix, service base URL)
    ("/api/auth", os.environ.get("USER_URL", "http://127.0.0.1:5001")),
    ("/api/users", os.environ.get("USER_URL", "http://127.0.0.1:5001")),
    ("/api/menu", os.environ.get("MENU_URL", "http://127.0.0.1:5002")),
    ("/api/orders", os.environ.get("ORDER_URL", "http://127.0.0.1:5003")),
    ("/api/admin", os.environ.get("ORDER_URL", "http://127.0.0.1:5003")),
    ("/api/payments", os.environ.get("PAYMENT_URL", "http://127.0.0.1:5004")),
    ("/", os.environ.get("FRONTEND_URL", "http://127.0.0.1:5000")),
]


class Proxy(BaseHTTPRequestHandler):
    def _forward(self):
        base = next(b for p, b in ROUTES if self.path.startswith(p))
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")}
        try:
            r = requests.request(self.command, base + self.path, data=body, headers=headers,
                                 allow_redirects=False, timeout=15)
        except requests.RequestException:
            self.send_response(502); self.end_headers(); self.wfile.write(b'{"error":"bad gateway"}'); return
        self.send_response(r.status_code)
        for k, v in r.headers.items():
            if k.lower() not in ("transfer-encoding", "connection", "content-encoding", "content-length"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(r.content)))
        self.end_headers()
        self.wfile.write(r.content)

    do_GET = do_POST = do_PUT = do_DELETE = _forward

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"dev gateway on :{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Proxy).serve_forever()
