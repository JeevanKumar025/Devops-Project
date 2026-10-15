"""Creates a Flask app with the cross-cutting DevOps features every service needs:
/health (liveness+readiness), /metrics (Prometheus text format), JSON access logs
and consistent JSON error responses."""
import json
import os
import threading
import time

from flask import Flask, g, jsonify, request

BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5)


class Metrics:
    def __init__(self, service):
        self.service = service
        self.lock = threading.Lock()
        self.counts = {}      # (method, endpoint, status) -> n
        self.hist = {}        # (method, endpoint) -> [bucket counts..., sum, count]

    def observe(self, method, endpoint, status, seconds):
        with self.lock:
            key = (method, endpoint, str(status))
            self.counts[key] = self.counts.get(key, 0) + 1
            h = self.hist.setdefault((method, endpoint), [0] * len(BUCKETS) + [0.0, 0])
            for i, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    h[i] += 1
            h[-2] += seconds
            h[-1] += 1

    def render(self):
        s, lines = self.service, []
        lines += ["# HELP http_requests_total Total HTTP requests.", "# TYPE http_requests_total counter"]
        with self.lock:
            for (m, e, st), n in sorted(self.counts.items()):
                lines.append(f'http_requests_total{{service="{s}",method="{m}",endpoint="{e}",status="{st}"}} {n}')
            lines += ["# HELP http_request_duration_seconds Request latency.",
                      "# TYPE http_request_duration_seconds histogram"]
            for (m, e), h in sorted(self.hist.items()):
                base = f'service="{s}",method="{m}",endpoint="{e}"'
                for i, bound in enumerate(BUCKETS):
                    lines.append(f'http_request_duration_seconds_bucket{{{base},le="{bound}"}} {h[i]}')
                lines.append(f'http_request_duration_seconds_bucket{{{base},le="+Inf"}} {h[-1]}')
                lines.append(f'http_request_duration_seconds_sum{{{base}}} {h[-2]:.6f}')
                lines.append(f'http_request_duration_seconds_count{{{base}}} {h[-1]}')
        return "\n".join(lines) + "\n"


def create_app(service_name, db=None):
    app = Flask(service_name)
    metrics = Metrics(service_name)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _start():
        g.started = time.perf_counter()

    @app.after_request
    def _finish(response):
        if request.path in ("/health", "/metrics"):
            return response
        elapsed = time.perf_counter() - getattr(g, "started", time.perf_counter())
        endpoint = request.url_rule.rule if request.url_rule else "unmatched"
        metrics.observe(request.method, endpoint, response.status_code, elapsed)
        if os.environ.get("LOG_REQUESTS", "1") != "0":
            print(json.dumps({"service": service_name, "method": request.method, "path": request.path,
                          "status": response.status_code, "ms": round(elapsed * 1000, 1)}), flush=True)
        return response

    @app.get("/health")
    def health():
        if db is not None:
            try:
                db.ping()
            except Exception:
                return jsonify(status="unhealthy", service=service_name), 503
        return jsonify(status="ok", service=service_name)

    @app.get("/metrics")
    def metrics_endpoint():
        return metrics.render(), 200, {"Content-Type": "text/plain; version=0.0.4"}

    @app.errorhandler(404)
    def _404(_):
        return jsonify(error="Not found."), 404

    @app.errorhandler(405)
    def _405(_):
        return jsonify(error="Method not allowed."), 405

    @app.errorhandler(500)
    def _500(_):
        return jsonify(error="Internal server error."), 500

    return app


def json_body():
    """Parsed JSON object from the request, or {} when missing/invalid."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
