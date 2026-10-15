"""Drives the HTML pages like a browser (cookies + CSRF) through the gateway.
    python scripts/ui_smoke_test.py http://localhost:8080 [admin_user admin_password]"""
import re
import sys
import uuid

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")
ADMIN = (sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else ("admin", "admin12345")


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        sys.exit(1)


class Browser:
    def __init__(self):
        self.s, self.html = requests.Session(), ""

    def get(self, path, **kw):
        r = self.s.get(BASE + path, timeout=15, **kw)
        self.html = r.text
        return r

    def post(self, path, **data):
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.html)
        data["csrf_token"] = token.group(1) if token else ""
        r = self.s.post(BASE + path, data=data, timeout=15)
        self.html = r.text
        return r


student, admin = Browser(), Browser()
user = "ui_" + uuid.uuid4().hex[:8]
student.get("/register")
r = student.post("/register", username=user, password="password123", confirmation="password123")
check("register + redirect to home", r.status_code == 200 and "Log out" in r.text)
student.get("/menu")
check("menu page lists food", "Masala Dosa" in student.html)
student.post("/cart/add/1")
student.get("/cart")
check("cart shows item", "Masala Dosa" in student.html)
student.get("/checkout")
r = student.post("/checkout", notes="less spicy", payment_method="online_mock")
check("checkout confirms order", "ORDER PLACED SUCCESSFULLY" in r.text and "received" in r.text, r.text[:300])
order_id = re.search(r"#(\d+)", r.text).group(1)
student.get(f"/orders/{order_id}")
check("order detail page", "Masala Dosa" in student.html and "Paid" in student.html)
student.get("/dashboard")
check("dashboard shows active order", f"#{order_id}" in student.html)
check("csrf is enforced", requests.post(BASE + "/cart/clear", timeout=15).status_code == 400)
check("student blocked from admin pages", "Overview" not in student.get("/admin").text)

admin.get("/login")
r = admin.post("/login", username=ADMIN[0], password=ADMIN[1])
check("admin login", "Menu management" in r.text, r.text[:200])
admin.get(f"/admin/orders/{order_id}")
check("admin order page", "less spicy" in admin.html and user in admin.html)
r = admin.post(f"/admin/orders/{order_id}/status", status="Accepted")
check("admin accepts", "is now Accepted" in r.text)
admin.get("/admin/menu")
check("admin menu page", "Masala Dosa" in admin.html)
r = admin.post("/admin/menu/add", name="Chai", description="Hot masala chai", price="15.50", category_id="5", available="on")
check("admin adds item", "Chai was added" in r.text, r.text[:200])
student.get("/menu")
check("new item visible to students", "Chai" in student.html)
student.get(f"/orders/{order_id}")
check("student sees Accepted", "Accepted" in student.html)
print("UI smoke test passed.")
