import unittest

from common.testutil import bearer, load_service, temp_db_url

svc = load_service("order")
ALICE, BOB, ADMIN = bearer(1, "alice"), bearer(2, "bob"), bearer(9, "boss", "admin")
MENU = {1: {"id": 1, "name": "Masala Dosa", "price": 8500, "available": 1},
        2: {"id": 2, "name": "Veg Thali", "price": 12000, "available": 1},
        3: {"id": 3, "name": "Samosa", "price": 2000, "available": 0}}


class OrderServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = svc.create_app(temp_db_url()).test_client()
        self.refunds, self.payments = [], []
        self.menu_down = self.payment_down = False
        svc.menu_lookup = self.fake_menu
        svc.payment_create = self.fake_payment
        svc.payment_refund = self.fake_refund

    # fakes replace the HTTP calls to the other microservices
    def fake_menu(self, ids):
        if self.menu_down:
            raise svc.DownstreamError("menu-service")
        return [MENU[i] for i in ids if i in MENU]

    def fake_payment(self, token, order_id, amount, method):
        if self.payment_down:
            raise svc.DownstreamError("payment-service")
        self.payments.append((order_id, amount, method))
        return {"id": 100 + order_id, "status": "Paid" if method == "online_mock" else "Pending"}

    def fake_refund(self, token, payment_id):
        self.refunds.append(payment_id)
        return {"id": payment_id, "status": "Refunded"}

    def order(self, items=None, headers=ALICE, **extra):
        body = {"items": items if items is not None else [{"food_id": 1, "quantity": 2}, {"food_id": 2, "quantity": 1}], **extra}
        return self.client.post("/api/orders", json=body, headers=headers)

    def test_total_is_calculated_from_menu_service_prices(self):
        r = self.order(total=1, price=1)                     # client-supplied values are ignored
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json["order"]["total"], 2 * 8500 + 12000)
        self.assertEqual(r.json["order"]["item_summary"], "2 × Masala Dosa, 1 × Veg Thali")
        self.assertEqual(self.payments, [(1, 29000, "pay_at_canteen")])

    def test_online_payment_is_recorded(self):
        order = self.order(payment_method="online_mock").json["order"]
        self.assertEqual(order["payment_status"], "Paid")

    def test_rejects_bad_requests(self):
        self.assertEqual(self.order(items=[]).status_code, 400)
        self.assertEqual(self.order(items=[{"food_id": 1, "quantity": 99}]).status_code, 400)
        self.assertEqual(self.order(items=[{"food_id": 3, "quantity": 1}]).status_code, 409)     # unavailable
        self.assertEqual(self.order(items=[{"food_id": 404, "quantity": 1}]).status_code, 409)   # unknown
        self.assertEqual(self.order(payment_method="cheque").status_code, 400)
        self.assertEqual(self.order(notes="x" * 301).status_code, 400)

    def test_admin_cannot_place_orders_and_anonymous_cannot_either(self):
        self.assertEqual(self.order(headers=ADMIN).status_code, 403)
        self.assertEqual(self.client.post("/api/orders", json={}).status_code, 401)

    def test_menu_service_down_gives_503(self):
        self.menu_down = True
        self.assertEqual(self.order().status_code, 503)

    def test_payment_failure_cancels_order(self):
        self.payment_down = True
        self.assertEqual(self.order().status_code, 503)
        orders = self.client.get("/api/orders", headers=ALICE).json["orders"]
        self.assertEqual((orders[0]["status"], orders[0]["payment_status"]), ("Cancelled", "Failed"))

    def test_students_only_see_their_own_orders(self):
        oid = self.order().json["order"]["id"]
        self.assertEqual(self.client.get(f"/api/orders/{oid}", headers=ALICE).status_code, 200)
        self.assertEqual(self.client.get(f"/api/orders/{oid}", headers=BOB).status_code, 404)
        self.assertEqual(self.client.get("/api/orders", headers=BOB).json["orders"], [])
        self.assertEqual(self.client.post(f"/api/orders/{oid}/cancel", headers=BOB).status_code, 409)

    def test_cancel_pending_refunds_payment_but_not_after_accept(self):
        first = self.order(payment_method="online_mock").json["order"]["id"]
        r = self.client.post(f"/api/orders/{first}/cancel", headers=ALICE)
        self.assertEqual(r.json["order"]["status"], "Cancelled")
        self.assertEqual(r.json["order"]["payment_status"], "Refunded")
        self.assertEqual(self.refunds, [100 + first])
        second = self.order().json["order"]["id"]
        self.client.post(f"/api/admin/orders/{second}/status", json={"status": "Accepted"}, headers=ADMIN)
        self.assertEqual(self.client.post(f"/api/orders/{second}/cancel", headers=ALICE).status_code, 409)

    def test_admin_status_workflow(self):
        oid = self.order().json["order"]["id"]
        url = f"/api/admin/orders/{oid}/status"
        self.assertEqual(self.client.post(url, json={"status": "Completed"}, headers=ADMIN).status_code, 409)
        for status in ("Accepted", "Preparing", "Ready", "Completed"):
            self.assertEqual(self.client.post(url, json={"status": status}, headers=ADMIN).json["order"]["status"], status)
        self.assertEqual(self.client.post(url, json={"status": "Pending"}, headers=ADMIN).status_code, 409)
        self.assertEqual(self.client.post(url, json={"status": "Accepted"}, headers=ALICE).status_code, 403)

    def test_rejecting_refunds_and_admin_sees_allowed_actions(self):
        oid = self.order(payment_method="online_mock").json["order"]["id"]
        self.assertEqual(self.client.get(f"/api/orders/{oid}", headers=ADMIN).json["order"]["allowed_statuses"], ["Accepted", "Rejected"])
        r = self.client.post(f"/api/admin/orders/{oid}/status", json={"status": "Rejected"}, headers=ADMIN)
        self.assertEqual(r.json["order"]["payment_status"], "Refunded")

    def test_admin_listing_and_stats(self):
        self.order()
        self.order(headers=BOB)
        self.assertEqual(len(self.client.get("/api/admin/orders", headers=ADMIN).json["orders"]), 2)
        self.assertEqual(len(self.client.get("/api/admin/orders?status=Ready", headers=ADMIN).json["orders"]), 0)
        self.assertEqual(self.client.get("/api/admin/orders", headers=ALICE).status_code, 403)
        stats = self.client.get("/api/admin/stats", headers=ADMIN).json
        self.assertEqual((stats["overview"]["orders"], stats["overview"]["pending"]), (2, 2))


if __name__ == "__main__":
    unittest.main()
