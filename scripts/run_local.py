"""Run the whole system on one machine WITHOUT Docker (SQLite databases in ./.local).
    python scripts/run_local.py            ->  http://localhost:8080
Stop with Ctrl+C. Admin login: admin / admin12345"""
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, ".local")
os.makedirs(DATA, exist_ok=True)
env = dict(os.environ, PYTHONPATH=ROOT, LOG_REQUESTS=os.environ.get("LOG_REQUESTS", "0"),
           JWT_SECRET="local-dev-secret-local-dev-secret-0123", SECRET_KEY="local-dev-session-key",
           ADMIN_USERNAME="admin", ADMIN_PASSWORD="admin12345", GATEWAY_URL="http://127.0.0.1:8080",
           MENU_SERVICE_URL="http://127.0.0.1:5002", PAYMENT_SERVICE_URL="http://127.0.0.1:5004")
procs = []


def start(name, script, port):
    e = dict(env, PORT=str(port), DATABASE_URL=f"sqlite:///{os.path.join(DATA, name)}.db")
    procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, script)], env=e, cwd=ROOT))


for name, script, port in [("user", "services/user/app.py", 5001), ("menu", "services/menu/app.py", 5002),
                           ("order", "services/order/app.py", 5003), ("payment", "services/payment/app.py", 5004),
                           ("frontend", "frontend/app.py", 5000), ("gateway", "scripts/dev_gateway.py", 8080)]:
    start(name, script, port)
print("CampusEats running at http://localhost:8080  (Ctrl+C to stop)")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for p in procs:
        p.send_signal(signal.SIGTERM)
