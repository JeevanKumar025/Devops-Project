"""Menu service: categories and food items (public reads, admin writes).

Owns `categories` and `food_items`. The order service asks it for current prices
through POST /api/menu/lookup, so a browser can never choose its own price.
"""
import os

from flask import jsonify, request

from common.appkit import create_app as base_app, json_body
from common.auth import current_user, require_auth
from common.db import Database, now_local

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS categories (
        id {pk}, name TEXT NOT NULL UNIQUE)""",
    """CREATE TABLE IF NOT EXISTS food_items (
        id {pk},
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        price INTEGER NOT NULL CHECK (price >= 0),
        category_id INTEGER NOT NULL REFERENCES categories(id),
        image TEXT,
        available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
        created_at TEXT NOT NULL)""",
]

CATEGORIES = ["Breakfast", "Meals", "Snacks", "Fast Food", "Beverages", "Desserts"]
# Prices are integer paise (8500 = Rs 85.00) so money maths never uses floats.
FOODS = [
    ("Masala Dosa", "Crisp dosa with potato masala, chutney, and sambar.", 8500, 1,
     "https://commons.wikimedia.org/wiki/Special:FilePath/A%20plate%20of%20South%20Indian%20Masala%20Dosa.jpg?width=900"),
    ("Veg Thali", "Rice, dal, seasonal vegetables, roti, and curd.", 12000, 2,
     "https://commons.wikimedia.org/wiki/Special:FilePath/Indian%20Veg%20Thaali.jpg?width=900"),
    ("Samosa", "Freshly fried potato samosa with mint chutney.", 2000, 3,
     "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=900&q=80"),
    ("Classic Burger", "Veg patty, lettuce, tomato, cheese, and house sauce.", 12000, 4,
     "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=900&q=80"),
    ("Cold Coffee", "Chilled coffee blended with milk and ice cream.", 6000, 5,
     "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?auto=format&fit=crop&w=900&q=80"),
    ("Brownie", "Warm chocolate brownie with a soft centre.", 7000, 6,
     "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?auto=format&fit=crop&w=900&q=80"),
]

SELECT_ITEMS = ("SELECT f.id, f.name, f.description, f.price, f.category_id, c.name AS category_name, "
                "f.image, f.available FROM food_items f JOIN categories c ON c.id = f.category_id")


def validate_food(data, categories):
    """Return (clean_fields, error_message)."""
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    image = str(data.get("image") or "").strip() or None
    price, category_id = data.get("price"), data.get("category_id")
    if not isinstance(price, int) or isinstance(price, bool) or price < 0:
        return None, "Price must be a whole number of paise (0 or more)."
    if not name or len(name) > 80 or not description or len(description) > 300 or (image and len(image) > 500):
        return None, "Enter a name, description, valid price, and category."
    if not isinstance(category_id, int) or category_id not in categories:
        return None, "Enter a name, description, valid price, and category."
    return {"name": name, "description": description, "price": price, "category_id": category_id,
            "image": image, "available": 1 if data.get("available") else 0}, None


def create_app(database_url=None):
    db = Database(database_url)
    db.init_schema(SCHEMA)
    app = base_app("menu-service", db)

    # Seed the starter menu once (safe if several replicas start together).
    try:
        with db.transaction() as tx:
            if not tx.one("SELECT id FROM categories LIMIT 1"):
                for i, name in enumerate(CATEGORIES, 1):
                    tx.execute("INSERT INTO categories (id, name) VALUES (:i, :n)", i=i, n=name)
                for name, desc, price, cat, image in FOODS:
                    tx.execute("INSERT INTO food_items (name, description, price, category_id, image, available, created_at) "
                               "VALUES (:n, :d, :p, :c, :i, 1, :t)", n=name, d=desc, p=price, c=cat, i=image, t=now_local())
    except db.integrity_errors:
        pass

    def category_ids(tx):
        return {r["id"] for r in tx.all("SELECT id FROM categories")}

    @app.get("/api/menu/categories")
    def categories():
        with db.transaction() as tx:
            return jsonify(categories=tx.all("SELECT id, name FROM categories ORDER BY name"))

    @app.get("/api/menu")
    def list_menu():
        """Available items for students. Optional ?search= and ?category=."""
        sql, params = SELECT_ITEMS + " WHERE f.available = 1", {}
        search = request.args.get("search", "").strip()
        category = request.args.get("category", type=int)
        if search:
            sql += " AND LOWER(f.name) LIKE :s"
            params["s"] = f"%{search.lower()}%"
        if category:
            sql += " AND f.category_id = :c"
            params["c"] = category
        with db.transaction() as tx:
            return jsonify(items=tx.all(sql + " ORDER BY c.name, f.name", **params))

    @app.get("/api/menu/admin/items")
    @require_auth("admin")
    def admin_list():
        with db.transaction() as tx:
            return jsonify(items=tx.all(SELECT_ITEMS + " ORDER BY f.created_at DESC, f.id DESC"))

    @app.get("/api/menu/items/<int:food_id>")
    def get_item(food_id):
        with db.transaction() as tx:
            item = tx.one(SELECT_ITEMS + " WHERE f.id = :i", i=food_id)
        if item is None:
            return jsonify(error="That menu item was not found."), 404
        return jsonify(item=item)

    @app.post("/api/menu/lookup")
    def lookup():
        """Used by the order service: current price/availability for a list of ids."""
        ids = json_body().get("ids")
        if not isinstance(ids, list) or len(ids) > 50 or not all(isinstance(i, int) for i in ids):
            return jsonify(error="ids must be a list of integers."), 400
        if not ids:
            return jsonify(items=[])
        names = {f"i{n}": v for n, v in enumerate(ids)}
        marks = ", ".join(f":{k}" for k in names)
        with db.transaction() as tx:
            return jsonify(items=tx.all(SELECT_ITEMS + f" WHERE f.id IN ({marks})", **names))

    @app.post("/api/menu/items")
    @require_auth("admin")
    def create_item():
        with db.transaction() as tx:
            fields, error = validate_food(json_body(), category_ids(tx))
            if error:
                return jsonify(error=error), 400
            new_id = tx.insert("INSERT INTO food_items (name, description, price, category_id, image, available, created_at) "
                               "VALUES (:name, :description, :price, :category_id, :image, :available, :t)",
                               t=now_local(), **fields)
            return jsonify(item=tx.one(SELECT_ITEMS + " WHERE f.id = :i", i=new_id)), 201

    @app.put("/api/menu/items/<int:food_id>")
    @require_auth("admin")
    def update_item(food_id):
        with db.transaction() as tx:
            if not tx.one("SELECT id FROM food_items WHERE id = :i", i=food_id):
                return jsonify(error="That menu item was not found."), 404
            fields, error = validate_food(json_body(), category_ids(tx))
            if error:
                return jsonify(error=error), 400
            tx.execute("UPDATE food_items SET name=:name, description=:description, price=:price, "
                       "category_id=:category_id, image=:image, available=:available WHERE id=:i", i=food_id, **fields)
            return jsonify(item=tx.one(SELECT_ITEMS + " WHERE f.id = :i", i=food_id))

    @app.post("/api/menu/items/<int:food_id>/toggle")
    @require_auth("admin")
    def toggle_item(food_id):
        with db.transaction() as tx:
            cur = tx.execute("UPDATE food_items SET available = 1 - available WHERE id = :i", i=food_id)
            if cur.rowcount == 0:
                return jsonify(error="That menu item was not found."), 404
            return jsonify(item=tx.one(SELECT_ITEMS + " WHERE f.id = :i", i=food_id))

    @app.delete("/api/menu/items/<int:food_id>")
    @require_auth("admin")
    def delete_item(food_id):
        # Past orders keep their own copy of the item name and price, so deleting is safe.
        with db.transaction() as tx:
            cur = tx.execute("DELETE FROM food_items WHERE id = :i", i=food_id)
        if cur.rowcount == 0:
            return jsonify(error="That menu item was not found."), 404
        return jsonify(deleted=food_id)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)))
