"""Order service: checkout, order history and the canteen's status workflow.

Owns `orders` and `order_items`. It talks to two other services over HTTP:
  * menu-service    -> current price / availability of each item
  * payment-service -> records the payment for the order
Each order keeps its own copy of item names/prices and the username, so it never
needs to query another service's database.

Checkout is a small "saga": the order is saved first, then payment is requested;
if the payment service fails, the order is cancelled (compensating action).
"""
import os

import requests
from flask import jsonify, request

from common.appkit import create_app as base_app, json_body
from common.auth import bearer_token, current_user, require_auth
from common.db import Database, now_local, today_local

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS orders (
        id {pk},
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        total INTEGER NOT NULL CHECK (total >= 0),
        notes TEXT,
        payment_method TEXT NOT NULL,
        payment_id INTEGER,
        payment_status TEXT NOT NULL DEFAULT 'Processing',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS order_items (
        id {pk},
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        food_item_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        price INTEGER NOT NULL CHECK (price >= 0))""",
    "CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)",
    "CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id)",
]
STATUSES = ["Pending", "Accepted", "Preparing", "Ready", "Completed", "Rejected", "Cancelled"]
TRANSITIONS = {"Pending": ["Accepted", "Rejected"], "Accepted": ["Preparing", "Rejected"],
               "Preparing": ["Ready"], "Ready": ["Completed"]}
PAYMENT_METHODS = ("pay_at_canteen", "online_mock")
TIMEOUT = 5


class DownstreamError(Exception):
    """A dependent service was unreachable or refused the request."""


# --- calls to other services (module-level so tests can replace them) -------
def menu_lookup(ids):
    url = os.environ.get("MENU_SERVICE_URL", "http://localhost:5002")
    try:
        r = requests.post(f"{url}/api/menu/lookup", json={"ids": ids}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["items"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise DownstreamError("menu-service") from exc


def payment_create(token, order_id, amount, method):
    url = os.environ.get("PAYMENT_SERVICE_URL", "http://localhost:5004")
    try:
        r = requests.post(f"{url}/api/payments", timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}"},
                          json={"order_id": order_id, "amount": amount, "method": method})
        r.raise_for_status()
        return r.json()["payment"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise DownstreamError("payment-service") from exc


def payment_refund(token, payment_id):
    """Best effort: a refund failure must never block cancelling an order."""
    url = os.environ.get("PAYMENT_SERVICE_URL", "http://localhost:5004")
    try:
        r = requests.post(f"{url}/api/payments/{payment_id}/refund", timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {token}"})
        return r.json().get("payment") if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def create_app(database_url=None):
    db = Database(database_url)
    db.init_schema(SCHEMA)
    app = base_app("order-service", db)

    def with_items(tx, orders):
        """Attach `lines` (list) and `item_summary` (text) to each order."""
        if not orders:
            return orders
        ids = {f"o{n}": o["id"] for n, o in enumerate(orders)}
        marks = ", ".join(f":{k}" for k in ids)
        rows = tx.all(f"SELECT order_id, name, quantity, price FROM order_items WHERE order_id IN ({marks}) ORDER BY id", **ids)
        by_order = {}
        for row in rows:
            by_order.setdefault(row["order_id"], []).append(row)
        for order in orders:
            lines = by_order.get(order["id"], [])
            order["lines"] = lines
            order["item_summary"] = ", ".join(f"{l['quantity']} × {l['name']}" for l in lines)
        return orders

    def visible(order, user):
        return order is not None and (user["role"] == "admin" or order["user_id"] == user["id"])

    # ------------------------------------------------------------- students
    @app.post("/api/orders")
    @require_auth("student")
    def place_order():
        user, data = current_user(), json_body()
        raw_items = data.get("items")
        notes = str(data.get("notes") or "").strip()
        method = data.get("payment_method", "pay_at_canteen")
        if method not in PAYMENT_METHODS:
            return jsonify(error="Unknown payment method."), 400
        if len(notes) > 300:
            return jsonify(error="Instructions must be 300 characters or fewer."), 400
        if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 30:
            return jsonify(error="Your cart is empty."), 400
        quantities = {}
        for entry in raw_items:
            try:
                fid, qty = int(entry["food_id"]), int(entry["quantity"])
            except (KeyError, TypeError, ValueError):
                return jsonify(error="Invalid cart item."), 400
            if not 1 <= qty <= 20:
                return jsonify(error="Quantity must be between 1 and 20."), 400
            quantities[fid] = min(quantities.get(fid, 0) + qty, 20)

        try:
            menu = {item["id"]: item for item in menu_lookup(list(quantities))}
        except DownstreamError:
            return jsonify(error="Menu service is unavailable. Please try again shortly."), 503
        if len(menu) != len(quantities) or any(not menu[f]["available"] for f in quantities):
            return jsonify(error="One or more cart items are no longer available."), 409

        # Prices come from the menu service, never from the client.
        total = sum(menu[f]["price"] * q for f, q in quantities.items())
        now = now_local()
        with db.transaction() as tx:
            order_id = tx.insert(
                "INSERT INTO orders (user_id, username, status, total, notes, payment_method, payment_status, created_at, updated_at) "
                "VALUES (:u, :n, 'Pending', :t, :notes, :m, 'Processing', :now, :now)",
                u=user["id"], n=user["username"], t=total, notes=notes or None, m=method, now=now)
            for fid, qty in quantities.items():
                tx.execute("INSERT INTO order_items (order_id, food_item_id, name, quantity, price) VALUES (:o, :f, :n, :q, :p)",
                           o=order_id, f=fid, n=menu[fid]["name"], q=qty, p=menu[fid]["price"])

        try:
            payment = payment_create(bearer_token(), order_id, total, method)
        except DownstreamError:
            with db.transaction() as tx:   # compensating action
                tx.execute("UPDATE orders SET status = 'Cancelled', payment_status = 'Failed', updated_at = :t WHERE id = :i",
                           t=now_local(), i=order_id)
            return jsonify(error="Payment service is unavailable, so the order was cancelled. Please try again."), 503

        with db.transaction() as tx:
            tx.execute("UPDATE orders SET payment_id = :p, payment_status = :s WHERE id = :i",
                       p=payment["id"], s=payment["status"], i=order_id)
            order = with_items(tx, [tx.one("SELECT * FROM orders WHERE id = :i", i=order_id)])[0]
        return jsonify(order=order), 201

    @app.get("/api/orders")
    @require_auth()
    def my_orders():
        limit = request.args.get("limit", type=int)
        sql = "SELECT * FROM orders WHERE user_id = :u ORDER BY created_at DESC, id DESC"
        if limit:
            sql += f" LIMIT {max(1, min(limit, 200))}"
        with db.transaction() as tx:
            return jsonify(orders=with_items(tx, tx.all(sql, u=current_user()["id"])))

    @app.get("/api/orders/<int:order_id>")
    @require_auth()
    def get_order(order_id):
        user = current_user()
        with db.transaction() as tx:
            order = tx.one("SELECT * FROM orders WHERE id = :i", i=order_id)
            if not visible(order, user):       # same 404 for "missing" and "someone else's"
                return jsonify(error="That order was not found."), 404
            order = with_items(tx, [order])[0]
        order["allowed_statuses"] = TRANSITIONS.get(order["status"], []) if user["role"] == "admin" else []
        return jsonify(order=order)

    @app.post("/api/orders/<int:order_id>/cancel")
    @require_auth("student")
    def cancel_order(order_id):
        user = current_user()
        with db.transaction() as tx:
            # One atomic statement checks owner AND status, so it cannot race.
            cur = tx.execute("UPDATE orders SET status = 'Cancelled', updated_at = :t "
                             "WHERE id = :i AND user_id = :u AND status = 'Pending'", t=now_local(), i=order_id, u=user["id"])
            if cur.rowcount != 1:
                return jsonify(error="Only your pending orders can be cancelled."), 409
            order = tx.one("SELECT * FROM orders WHERE id = :i", i=order_id)
        if order["payment_id"]:
            refunded = payment_refund(bearer_token(), order["payment_id"])
            if refunded:
                with db.transaction() as tx:
                    tx.execute("UPDATE orders SET payment_status = :s WHERE id = :i", s=refunded["status"], i=order_id)
                order["payment_status"] = refunded["status"]
        return jsonify(order=order)

    # ---------------------------------------------------------------- admin
    @app.get("/api/admin/orders")
    @require_auth("admin")
    def admin_orders():
        status = request.args.get("status", "")
        sql, params = "SELECT * FROM orders", {}
        if status in STATUSES:
            sql += " WHERE status = :s"
            params["s"] = status
        with db.transaction() as tx:
            orders = tx.all(sql + " ORDER BY created_at DESC, id DESC", **params)
            return jsonify(orders=with_items(tx, orders), statuses=STATUSES)

    @app.get("/api/admin/stats")
    @require_auth("admin")
    def admin_stats():
        with db.transaction() as tx:
            overview = tx.one(
                "SELECT COUNT(*) AS orders, "
                "COALESCE(SUM(CASE WHEN status = 'Completed' THEN total ELSE 0 END), 0) AS revenue, "
                "COALESCE(SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END), 0) AS pending, "
                "COALESCE(SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END), 0) AS completed "
                "FROM orders WHERE created_at LIKE :d", d=today_local() + "%")
            incoming = tx.all("SELECT * FROM orders ORDER BY CASE status WHEN 'Pending' THEN 0 ELSE 1 END, "
                              "created_at DESC, id DESC LIMIT 8")
            return jsonify(overview=overview, incoming=with_items(tx, incoming))

    @app.post("/api/admin/orders/<int:order_id>/status")
    @require_auth("admin")
    def update_status(order_id):
        requested = json_body().get("status")
        with db.transaction() as tx:
            order = tx.one("SELECT * FROM orders WHERE id = :i", i=order_id)
            if order is None:
                return jsonify(error="That order was not found."), 404
            if requested not in TRANSITIONS.get(order["status"], []):
                return jsonify(error="That status change is not allowed."), 409
            tx.execute("UPDATE orders SET status = :s, updated_at = :t WHERE id = :i", s=requested, t=now_local(), i=order_id)
        if requested == "Rejected" and order["payment_id"]:
            refunded = payment_refund(bearer_token(), order["payment_id"])
            if refunded:
                with db.transaction() as tx:
                    tx.execute("UPDATE orders SET payment_status = :s WHERE id = :i", s=refunded["status"], i=order_id)
        with db.transaction() as tx:
            return jsonify(order=with_items(tx, [tx.one("SELECT * FROM orders WHERE id = :i", i=order_id)])[0])

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)))
