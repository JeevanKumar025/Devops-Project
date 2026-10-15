"""End-to-end smoke test against a running system (via the gateway).
    python scripts/smoke_test.py http://localhost:8080 [admin_user admin_password]
Used by CI after `docker compose up` and by you after a deployment."""
import sys
import uuid

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")
ADMIN = (sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else ("admin", "admin12345")
passed = 0


def check(name, condition, detail=""):
    global passed
    print(("PASS " if condition else "FAIL ") + name + (f"  {detail}" if not condition else ""))
    if not condition:
        sys.exit(1)
    passed += 1


def call(method, path, token=None, **kw):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.request(method, BASE + path, headers=headers, timeout=15, **kw)


check("frontend home page", call("GET", "/").status_code == 200)
menu = call("GET", "/api/menu")
check("menu service via gateway", menu.status_code == 200 and len(menu.json()["items"]) >= 1)
item = menu.json()["items"][0]

name = "smoke_" + uuid.uuid4().hex[:8]
reg = call("POST", "/api/auth/register", json={"username": name, "password": "password123"})
check("register student", reg.status_code == 201)
student = reg.json()["token"]

order = call("POST", "/api/orders", student, json={"items": [{"food_id": item["id"], "quantity": 2}],
                                                    "payment_method": "online_mock"})
check("place order", order.status_code == 201, order.text)
order = order.json()["order"]
check("server-side total", order["total"] == 2 * item["price"])
check("payment service recorded payment", order["payment_status"] == "Paid")

check("anonymous cannot place order", call("POST", "/api/orders", json={}).status_code == 401)
check("student cannot use admin API", call("GET", "/api/admin/orders", student).status_code == 403)

login = call("POST", "/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
check("admin login", login.status_code == 200, login.text)
admin = login.json()["token"]
r = call("POST", f"/api/admin/orders/{order['id']}/status", admin, json={"status": "Accepted"})
check("admin accepts order", r.status_code == 200 and r.json()["order"]["status"] == "Accepted")
mine = call("GET", f"/api/orders/{order['id']}", student).json()["order"]
check("student sees updated status", mine["status"] == "Accepted")
print(f"\nAll {passed} checks passed.")
