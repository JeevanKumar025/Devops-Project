"""Frontend tests: the gateway is replaced by a fake so no other service is needed."""
import re
import unittest
from unittest import mock

import requests

from common.testutil import load_frontend

fe = load_frontend()
MENU = {"items": [{"id": 1, "name": "Masala Dosa", "description": "Crisp", "price": 8500, "category_id": 1,
                   "category_name": "Breakfast", "image": None, "available": 1}]}
CATS = {"categories": [{"id": 1, "name": "Breakfast"}]}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def fake_gateway(method, url, **kwargs):
    path = url.split("://", 1)[1].split("/", 1)[1]
    if path == "api/menu":
        return FakeResponse(200, MENU)
    if path == "api/menu/categories":
        return FakeResponse(200, CATS)
    if path == "api/auth/login":
        ok = kwargs["json"]["password"] == "password123"
        user = {"id": 1, "username": kwargs["json"]["username"], "role": "student"}
        return FakeResponse(200, {"token": "t", "user": user}) if ok else FakeResponse(401, {"error": "Invalid username or password."})
    if path == "api/orders":
        return FakeResponse(200, {"orders": []})
    return FakeResponse(404, {})


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.client = fe.create_app().test_client()
        patcher = mock.patch.object(fe.requests, "request", side_effect=fake_gateway)
        patcher.start()
        self.addCleanup(patcher.stop)

    def csrf(self, path):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.client.get(path).get_data(as_text=True)).group(1)

    def test_public_pages_render_from_service_data(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("Masala Dosa", self.client.get("/menu").get_data(as_text=True))

    def test_protected_pages_redirect_to_login(self):
        r = self.client.get("/dashboard")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/login"))
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_post_without_csrf_token_is_rejected(self):
        self.assertEqual(self.client.post("/login", data={"username": "a", "password": "b"}).status_code, 400)

    def test_login_stores_token_and_role_in_session(self):
        token = self.csrf("/login")
        r = self.client.post("/login", data={"csrf_token": token, "username": "alice", "password": "password123"})
        self.assertEqual(r.status_code, 302)
        with self.client.session_transaction() as s:
            self.assertEqual((s["token"], s["role"], s["username"]), ("t", "student", "alice"))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_bad_login_shows_error_from_user_service(self):
        token = self.csrf("/login")
        r = self.client.post("/login", data={"csrf_token": token, "username": "alice", "password": "nope"})
        self.assertIn("Invalid username or password.", r.get_data(as_text=True))

    def test_backend_outage_shows_friendly_503_page(self):
        with mock.patch.object(fe.requests, "request", side_effect=requests.ConnectionError("down")):
            r = self.client.get("/menu")
        self.assertEqual(r.status_code, 503)
        self.assertIn("not responding", r.get_data(as_text=True))

    def test_health(self):
        self.assertEqual(self.client.get("/health").get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
