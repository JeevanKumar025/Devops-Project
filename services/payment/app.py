"""Payment service (simulated). No real money moves: this models the payment
step of the order flow so the order service has a real service to call.

  pay_at_canteen -> status 'Pending'  (student pays at the counter)
  online_mock    -> status 'Paid'     (instantly approved, for demo)
Cancelled/rejected orders trigger POST /api/payments/<id>/refund.
"""
import os

from flask import jsonify

from common.appkit import create_app as base_app, json_body
from common.auth import current_user, require_auth
from common.db import Database, now_local

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS payments (
        id {pk},
        order_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL CHECK (amount > 0),
        method TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id)",
]
METHODS = {"pay_at_canteen": "Pending", "online_mock": "Paid"}


def create_app(database_url=None):
    db = Database(database_url)
    db.init_schema(SCHEMA)
    app = base_app("payment-service", db)

    @app.post("/api/payments")
    @require_auth()
    def create_payment():
        data = json_body()
        order_id, amount, method = data.get("order_id"), data.get("amount"), data.get("method")
        if not isinstance(order_id, int) or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            return jsonify(error="order_id and a positive integer amount (paise) are required."), 400
        if method not in METHODS:
            return jsonify(error=f"method must be one of: {', '.join(METHODS)}."), 400
        now = now_local()
        with db.transaction() as tx:
            pid = tx.insert("INSERT INTO payments (order_id, user_id, amount, method, status, created_at, updated_at) "
                            "VALUES (:o, :u, :a, :m, :s, :t, :t)",
                            o=order_id, u=current_user()["id"], a=amount, m=method, s=METHODS[method], t=now)
            payment = tx.one("SELECT * FROM payments WHERE id = :i", i=pid)
        return jsonify(payment=payment), 201

    @app.get("/api/payments/<int:payment_id>")
    @require_auth()
    def get_payment(payment_id):
        user = current_user()
        with db.transaction() as tx:
            payment = tx.one("SELECT * FROM payments WHERE id = :i", i=payment_id)
        if payment is None or (user["role"] != "admin" and payment["user_id"] != user["id"]):
            return jsonify(error="Payment not found."), 404
        return jsonify(payment=payment)

    @app.post("/api/payments/<int:payment_id>/refund")
    @require_auth()
    def refund(payment_id):
        user = current_user()
        with db.transaction() as tx:
            payment = tx.one("SELECT * FROM payments WHERE id = :i", i=payment_id)
            if payment is None or (user["role"] != "admin" and payment["user_id"] != user["id"]):
                return jsonify(error="Payment not found."), 404
            new_status = {"Paid": "Refunded", "Pending": "Cancelled"}.get(payment["status"])
            if new_status is None:
                return jsonify(error=f"A {payment['status']} payment cannot be refunded."), 409
            tx.execute("UPDATE payments SET status = :s, updated_at = :t WHERE id = :i",
                       s=new_status, t=now_local(), i=payment_id)
            return jsonify(payment=tx.one("SELECT * FROM payments WHERE id = :i", i=payment_id))

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 5004)))
