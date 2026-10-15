import unittest

from common.testutil import bearer, load_service, temp_db_url

svc = load_service("payment")
ALICE, BOB, ADMIN = bearer(1, "alice"), bearer(2, "bob"), bearer(9, "boss", "admin")


class PaymentServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = svc.create_app(temp_db_url()).test_client()

    def pay(self, method="pay_at_canteen", headers=ALICE, amount=5000):
        return self.client.post("/api/payments", json={"order_id": 1, "amount": amount, "method": method}, headers=headers)

    def test_requires_authentication(self):
        self.assertEqual(self.client.post("/api/payments", json={}).status_code, 401)

    def test_statuses_by_method(self):
        self.assertEqual(self.pay("pay_at_canteen").json["payment"]["status"], "Pending")
        self.assertEqual(self.pay("online_mock").json["payment"]["status"], "Paid")

    def test_validation(self):
        self.assertEqual(self.pay("bitcoin").status_code, 400)
        self.assertEqual(self.pay(amount=0).status_code, 400)

    def test_only_owner_or_admin_can_read(self):
        pid = self.pay().json["payment"]["id"]
        self.assertEqual(self.client.get(f"/api/payments/{pid}", headers=ALICE).status_code, 200)
        self.assertEqual(self.client.get(f"/api/payments/{pid}", headers=BOB).status_code, 404)
        self.assertEqual(self.client.get(f"/api/payments/{pid}", headers=ADMIN).status_code, 200)

    def test_refund_flow(self):
        pid = self.pay("online_mock").json["payment"]["id"]
        self.assertEqual(self.client.post(f"/api/payments/{pid}/refund", headers=ALICE).json["payment"]["status"], "Refunded")
        self.assertEqual(self.client.post(f"/api/payments/{pid}/refund", headers=ALICE).status_code, 409)
        self.assertEqual(self.client.post(f"/api/payments/{pid}/refund", headers=BOB).status_code, 404)


if __name__ == "__main__":
    unittest.main()
