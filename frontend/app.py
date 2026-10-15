"""CampusEats web frontend.

A thin Flask app that renders the HTML pages. It has NO database: every piece of
data comes from the microservices through the API gateway (GATEWAY_URL), and the
login token (JWT) issued by the user service is kept in the signed session cookie.
The CSRF protection, templates and styling are unchanged from the original
CS50 project.
"""
import functools
import hmac
import os
import secrets
import time
from decimal import Decimal, InvalidOperation

import requests
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

from common.appkit import Metrics

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080").rstrip("/")
TIMEOUT = 8
ACTIVE_STATUSES = ("Pending", "Accepted", "Preparing", "Ready")


class ServiceUnavailable(Exception):
    pass


class SessionExpired(Exception):
    pass


def format_price(paise):
    return f"₹{paise // 100:,}.{paise % 100:02d}"


def parse_price(value):
    """Rupees typed in a form -> integer paise (None if invalid)."""
    try:
        price = Decimal(value)
        if not price.is_finite() or price < 0:
            return None
        paise = price * 100
        return int(paise) if paise == paise.to_integral_value() else None
    except (InvalidOperation, ValueError):
        return None


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.jinja_env.filters["price"] = format_price
    metrics = Metrics("frontend")

    # ---------------------------------------------------------- API client
    def api(method, path, **kwargs):
        """Call a backend service through the gateway. Returns (status_code, json)."""
        headers = {}
        if session.get("token"):
            headers["Authorization"] = f"Bearer {session['token']}"
        try:
            response = requests.request(method, f"{GATEWAY_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise ServiceUnavailable(str(exc)) from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 401 and session.get("token"):
            raise SessionExpired()
        if response.status_code in (502, 503, 504) and not body:
            raise ServiceUnavailable(f"{path} returned {response.status_code}")
        return response.status_code, body

    @app.errorhandler(ServiceUnavailable)
    def service_down(_):
        return render_template("error.html"), 503

    @app.errorhandler(SessionExpired)
    def session_expired(_):
        session.clear()
        flash("Your session expired. Please log in again.", "warning")
        return redirect(url_for("login"))

    # ------------------------------------------------ CSRF, metrics, health
    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def validate_csrf_token():
        g.started = time.perf_counter()
        if request.method == "POST":
            submitted, expected = request.form.get("csrf_token", ""), session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(submitted, expected):
                abort(400)

    @app.after_request
    def record_metrics(response):
        if request.path not in ("/health", "/metrics") and not request.path.startswith("/static"):
            endpoint = request.url_rule.rule if request.url_rule else "unmatched"
            metrics.observe(request.method, endpoint, response.status_code, time.perf_counter() - g.started)
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "frontend"}

    @app.get("/metrics")
    def metrics_endpoint():
        return metrics.render(), 200, {"Content-Type": "text/plain; version=0.0.4"}

    @app.context_processor
    def inject_current_user():
        if session.get("user_id") is None:
            return {"current_user": None}
        return {"current_user": {"username": session.get("username"), "role": session.get("role")}}

    # ----------------------------------------------------------- decorators
    def role_required(role):
        def decorator(view):
            @functools.wraps(view)
            def wrapped(*args, **kwargs):
                if session.get("user_id") is None:
                    flash("Please log in to continue.", "warning")
                    return redirect(url_for("login"))
                if session.get("role") != role:   # the services enforce this again from the JWT
                    if role == "admin":
                        flash("Administrator access is required.", "danger")
                        return redirect(url_for("index"))
                    flash("Student access is required for ordering.", "warning")
                    return redirect(url_for("admin_dashboard"))
                return view(*args, **kwargs)
            return wrapped
        return decorator

    student_required, admin_required = role_required("student"), role_required("admin")

    def as_list_row(order):
        order["items"] = order.get("item_summary", "")
        return order

    # ------------------------------------------------------------------ cart
    def cart_items():
        cart = session.get("cart", {})
        try:
            clean = {str(int(i)): int(q) for i, q in cart.items() if 0 < int(q) <= 20}
        except (TypeError, ValueError):
            session["cart"] = {}
            return [], 0
        if clean != cart:
            session["cart"] = clean
        if not clean:
            return [], 0
        status, body = api("POST", "/api/menu/lookup", json={"ids": [int(i) for i in clean]})
        if status != 200:
            raise ServiceUnavailable("menu lookup failed")
        found = {item["id"]: item for item in body["items"]}
        if len(found) != len(clean):    # deleted items must not stay in the cart
            session["cart"] = {k: v for k, v in clean.items() if int(k) in found}
            clean = session["cart"]
        items = [{"id": i["id"], "name": i["name"], "price": i["price"], "available": i["available"],
                  "quantity": clean[str(i["id"])], "line_total": i["price"] * clean[str(i["id"])]} for i in found.values()]
        items.sort(key=lambda item: item["name"].lower())
        return items, sum(item["line_total"] for item in items)

    # --------------------------------------------------------------- public
    @app.route("/")
    def index():
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return render_template("index.html")

    @app.route("/menu")
    def menu():
        if session.get("role") == "admin":
            flash("The student menu is not part of the administrator workspace.", "warning")
            return redirect(url_for("admin_dashboard"))
        search = request.args.get("search", "").strip()
        category_id = request.args.get("category", type=int)
        params = {k: v for k, v in (("search", search), ("category", category_id)) if v}
        _, menu_body = api("GET", "/api/menu", params=params)
        _, cat_body = api("GET", "/api/menu/categories")
        return render_template("menu.html", foods=menu_body.get("items", []), categories=cat_body.get("categories", []),
                               search=search, selected_category=category_id)

    # --------------------------------------------------------------- student
    @app.route("/cart")
    @student_required
    def cart():
        items, total = cart_items()
        return render_template("cart.html", items=items, total=total)

    @app.route("/cart/add/<int:food_id>", methods=["POST"])
    @student_required
    def add_to_cart(food_id):
        status, body = api("GET", f"/api/menu/items/{food_id}")
        food = body.get("item")
        if status != 200 or not food["available"]:
            flash("That food item is currently unavailable.", "danger")
            return redirect(url_for("menu"))
        cart_data = session.get("cart", {})
        cart_data[str(food_id)] = min(int(cart_data.get(str(food_id), 0)) + 1, 20)
        session["cart"] = cart_data
        flash(f"{food['name']} added to your cart.", "success")
        return redirect(url_for("menu"))

    @app.route("/cart/update/<int:food_id>", methods=["POST"])
    @student_required
    def update_cart(food_id):
        cart_data, key = session.get("cart", {}), str(food_id)
        if key not in cart_data:
            flash("That item is not in your cart.", "warning")
            return redirect(url_for("cart"))
        action = request.form.get("action")
        if action == "increase":
            cart_data[key] = min(int(cart_data[key]) + 1, 20)
        elif action == "decrease":
            cart_data[key] = int(cart_data[key]) - 1
            if cart_data[key] <= 0:
                cart_data.pop(key)
        elif action == "remove":
            cart_data.pop(key)
        else:
            flash("Invalid cart update.", "danger")
            return redirect(url_for("cart"))
        session["cart"] = cart_data
        return redirect(url_for("cart"))

    @app.route("/cart/clear", methods=["POST"])
    @student_required
    def clear_cart():
        session["cart"] = {}
        flash("Your cart has been emptied.", "success")
        return redirect(url_for("cart"))

    @app.route("/checkout", methods=["GET", "POST"])
    @student_required
    def checkout():
        items, total = cart_items()
        if not items:
            flash("Your cart is empty. Add something delicious first.", "warning")
            return redirect(url_for("menu"))
        if any(not item["available"] for item in items):
            flash("One or more cart items are no longer available. Please update your cart.", "danger")
            return redirect(url_for("cart"))
        if request.method == "POST":
            notes = request.form.get("notes", "").strip()
            method = request.form.get("payment_method", "pay_at_canteen")
            payload = {"items": [{"food_id": i["id"], "quantity": i["quantity"]} for i in items],
                       "notes": notes, "payment_method": method}
            status, body = api("POST", "/api/orders", json=payload)
            if status != 201:
                flash(body.get("error", "Could not place your order. Please try again."), "danger")
                return render_template("checkout.html", items=items, total=total, notes=notes, payment_method=method)
            session["cart"] = {}
            order = body["order"]
            return render_template("order_confirmation.html", order_id=order["id"], total=order["total"], order=order)
        return render_template("checkout.html", items=items, total=total, notes="", payment_method="pay_at_canteen")

    @app.route("/dashboard")
    @student_required
    def dashboard():
        _, body = api("GET", "/api/orders")
        orders = [as_list_row(o) for o in body.get("orders", [])]
        active = next((o for o in orders if o["status"] in ACTIVE_STATUSES), None)
        return render_template("dashboard.html", user={"username": session["username"]}, active_order=active,
                               recent_orders=orders[:4], total_orders=len(orders))

    @app.route("/orders")
    @student_required
    def orders():
        _, body = api("GET", "/api/orders")
        return render_template("orders.html", orders=[as_list_row(o) for o in body.get("orders", [])])

    @app.route("/orders/<int:order_id>")
    @student_required
    def order(order_id):
        status, body = api("GET", f"/api/orders/{order_id}")
        if status != 200:
            flash("That order was not found.", "danger")
            return redirect(url_for("orders"))
        return render_template("order.html", order=body["order"], items=body["order"]["lines"])

    @app.route("/orders/<int:order_id>/cancel", methods=["POST"])
    @student_required
    def cancel_order(order_id):
        status, body = api("POST", f"/api/orders/{order_id}/cancel")
        flash("Order cancelled successfully." if status == 200 else body.get("error", "Could not cancel the order."),
              "success" if status == 200 else "danger")
        return redirect(url_for("order", order_id=order_id))

    @app.route("/profile")
    @student_required
    def profile():
        _, body = api("GET", "/api/users/me")
        return render_template("profile.html", user=body["user"])

    # ----------------------------------------------------------------- admin
    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        _, body = api("GET", "/api/admin/stats")
        return render_template("admin/dashboard.html", overview=body["overview"],
                               incoming_orders=[as_list_row(o) for o in body["incoming"]])

    @app.route("/admin/orders")
    @admin_required
    def admin_orders():
        selected = request.args.get("status", "")
        _, body = api("GET", "/api/admin/orders", params={"status": selected} if selected else None)
        statuses = body.get("statuses", [])
        return render_template("admin/orders.html", orders=[as_list_row(o) for o in body.get("orders", [])],
                               statuses=statuses, selected_status=selected if selected in statuses else "")

    @app.route("/admin/orders/<int:order_id>")
    @admin_required
    def admin_order(order_id):
        status, body = api("GET", f"/api/orders/{order_id}")
        if status != 200:
            flash("That order was not found.", "danger")
            return redirect(url_for("admin_orders"))
        o = body["order"]
        return render_template("admin/order.html", order=o, items=o["lines"], allowed_statuses=o["allowed_statuses"])

    @app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
    @admin_required
    def update_order_status(order_id):
        status, body = api("POST", f"/api/admin/orders/{order_id}/status", json={"status": request.form.get("status")})
        if status == 200:
            flash(f"Order #{order_id} is now {body['order']['status']}.", "success")
        else:
            flash(body.get("error", "That status change is not allowed."), "danger")
        return redirect(url_for("admin_order", order_id=order_id))

    @app.route("/admin/menu")
    @admin_required
    def admin_menu():
        _, body = api("GET", "/api/menu/admin/items")
        return render_template("admin/menu.html", foods=body.get("items", []))

    def food_form_payload():
        return {"name": request.form.get("name", "").strip(), "description": request.form.get("description", "").strip(),
                "price": parse_price(request.form.get("price", "")), "category_id": request.form.get("category_id", type=int),
                "image": request.form.get("image", "").strip() or None, "available": request.form.get("available") == "on"}

    @app.route("/admin/menu/add", methods=["GET", "POST"])
    @admin_required
    def add_food():
        _, cats = api("GET", "/api/menu/categories")
        if request.method == "POST":
            status, body = api("POST", "/api/menu/items", json=food_form_payload())
            if status == 201:
                flash(f"{body['item']['name']} was added to the menu.", "success")
                return redirect(url_for("admin_menu"))
            flash(body.get("error", "Enter a name, description, valid price, and category."), "danger")
        return render_template("admin/edit_food.html", food=None, categories=cats["categories"])

    @app.route("/admin/menu/<int:food_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_food(food_id):
        status, body = api("GET", f"/api/menu/items/{food_id}")
        if status != 200:
            flash("That menu item was not found.", "danger")
            return redirect(url_for("admin_menu"))
        food = body["item"]
        _, cats = api("GET", "/api/menu/categories")
        if request.method == "POST":
            status, body = api("PUT", f"/api/menu/items/{food_id}", json=food_form_payload())
            if status == 200:
                flash(f"{body['item']['name']} was updated.", "success")
                return redirect(url_for("admin_menu"))
            flash(body.get("error", "Enter a name, description, valid price, and category."), "danger")
        return render_template("admin/edit_food.html", food=food, categories=cats["categories"])

    @app.route("/admin/menu/<int:food_id>/availability", methods=["POST"])
    @admin_required
    def toggle_food_availability(food_id):
        status, body = api("POST", f"/api/menu/items/{food_id}/toggle")
        flash("Availability updated." if status == 200 else "That menu item was not found.",
              "success" if status == 200 else "danger")
        return redirect(url_for("admin_menu"))

    @app.route("/admin/menu/<int:food_id>/delete", methods=["POST"])
    @admin_required
    def delete_food(food_id):
        status, _ = api("DELETE", f"/api/menu/items/{food_id}")
        flash("Menu item deleted." if status == 200 else "That menu item was not found.",
              "success" if status == 200 else "danger")
        return redirect(url_for("admin_menu"))

    # ------------------------------------------------------------------ auth
    def start_session(body):
        session.clear()
        session.update(token=body["token"], user_id=body["user"]["id"], username=body["user"]["username"],
                       role=body["user"]["role"])

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if session.get("user_id"):
            return redirect(url_for("index"))
        if request.method == "POST":
            password = request.form.get("password", "")
            if password != request.form.get("confirmation", ""):
                flash("Passwords do not match.", "danger")
            else:
                status, body = api("POST", "/api/auth/register",
                                   json={"username": request.form.get("username", "").strip(), "password": password})
                if status == 201:
                    start_session(body)
                    flash("Your CampusEats account is ready!", "success")
                    return redirect(url_for("index"))
                flash(body.get("error", "Could not create your account."), "danger")
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user_id"):
            return redirect(url_for("index"))
        if request.method == "POST":
            status, body = api("POST", "/api/auth/login",
                               json={"username": request.form.get("username", "").strip(),
                                     "password": request.form.get("password", "")})
            if status == 200:
                start_session(body)
                flash("Welcome back!", "success")
                return redirect(url_for("admin_dashboard") if body["user"]["role"] == "admin" else url_for("dashboard"))
            flash(body.get("error", "Invalid username or password."), "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("index"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
