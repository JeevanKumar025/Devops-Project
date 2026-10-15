import os
import unittest

from common.testutil import bearer, load_service, temp_db_url

svc = load_service("user")


class UserServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = svc.create_app(temp_db_url()).test_client()

    def register(self, username="alice", password="password123"):
        return self.client.post("/api/auth/register", json={"username": username, "password": password})

    def test_register_returns_token_and_student_role(self):
        r = self.register()
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json["token"])
        self.assertEqual(r.json["user"]["role"], "student")
        self.assertNotIn("password_hash", r.json["user"])

    def test_duplicate_username_is_case_insensitive(self):
        self.register("Alice")
        self.assertEqual(self.register("alice").status_code, 409)

    def test_validation(self):
        self.assertEqual(self.register("a!", "password123").status_code, 400)
        self.assertEqual(self.register("bob_ok", "short").status_code, 400)

    def test_login(self):
        self.register()
        ok = self.client.post("/api/auth/login", json={"username": "ALICE", "password": "password123"})
        self.assertEqual(ok.status_code, 200)
        bad = self.client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"})
        self.assertEqual(bad.status_code, 401)

    def test_me_requires_valid_token(self):
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)
        self.assertEqual(self.client.get("/api/users/me", headers={"Authorization": "Bearer junk"}).status_code, 401)
        token = self.register().json["token"]
        r = self.client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.json["user"]["username"], "alice")

    def test_bootstrap_admin_from_environment(self):
        os.environ.update(ADMIN_USERNAME="boss", ADMIN_PASSWORD="adminpass1")
        try:
            client = svc.create_app(temp_db_url()).test_client()
        finally:
            del os.environ["ADMIN_USERNAME"], os.environ["ADMIN_PASSWORD"]
        r = client.post("/api/auth/login", json={"username": "boss", "password": "adminpass1"})
        self.assertEqual(r.json["user"]["role"], "admin")

    def test_health_and_metrics(self):
        self.assertEqual(self.client.get("/health").json["status"], "ok")
        self.register()
        text = self.client.get("/metrics").get_data(as_text=True)
        self.assertIn('http_requests_total{service="user-service"', text)


if __name__ == "__main__":
    unittest.main()
