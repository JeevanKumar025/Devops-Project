"""User service: registration, login (issues JWT) and profile.

Owns the `users` table. Other services never read this database; they only trust
the signed JWT that this service issues.
"""
import os
import re

from flask import jsonify
from werkzeug.security import check_password_hash, generate_password_hash

from common.appkit import create_app as base_app, json_body
from common.auth import current_user, issue_token, require_auth
from common.db import Database, now_local

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id {pk},
        username TEXT NOT NULL,
        username_key TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'admin')),
        created_at TEXT NOT NULL
    )""",
]


def valid_username(username):
    return re.fullmatch(r"[A-Za-z0-9_]{3,30}", username or "") is not None


def create_app(database_url=None):
    db = Database(database_url)
    db.init_schema(SCHEMA)
    app = base_app("user-service", db)

    def public(user):
        return {"id": user["id"], "username": user["username"], "role": user["role"],
                "created_at": user["created_at"]}

    def create_user(tx, username, password, role):
        return tx.insert(
            "INSERT INTO users (username, username_key, password_hash, role, created_at) "
            "VALUES (:u, :k, :p, :r, :c)",
            u=username, k=username.lower(), p=generate_password_hash(password), r=role, c=now_local())

    # Optional bootstrap admin (set ADMIN_USERNAME / ADMIN_PASSWORD, e.g. from a Kubernetes Secret).
    admin_name, admin_pw = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
    if admin_name and admin_pw and valid_username(admin_name) and len(admin_pw) >= 8:
        try:
            with db.transaction() as tx:
                if not tx.one("SELECT id FROM users WHERE username_key = :k", k=admin_name.lower()):
                    create_user(tx, admin_name, admin_pw, "admin")
        except db.integrity_errors:
            pass  # another replica created it first

    @app.post("/api/auth/register")
    def register():
        data = json_body()
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        if not valid_username(username):
            return jsonify(error="Username must use 3 to 30 letters, numbers, or underscores."), 400
        if len(password) < 8:
            return jsonify(error="Password must contain at least 8 characters."), 400
        try:
            with db.transaction() as tx:
                user_id = create_user(tx, username, password, "student")
                user = tx.one("SELECT * FROM users WHERE id = :i", i=user_id)
        except db.integrity_errors:
            return jsonify(error="That username is already taken. Please choose another."), 409
        return jsonify(token=issue_token(user["id"], user["username"], user["role"]), user=public(user)), 201

    @app.post("/api/auth/login")
    def login():
        data = json_body()
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", ""))
        with db.transaction() as tx:
            user = tx.one("SELECT * FROM users WHERE username_key = :k", k=username)
        if user is None or not check_password_hash(user["password_hash"], password):
            return jsonify(error="Invalid username or password."), 401
        return jsonify(token=issue_token(user["id"], user["username"], user["role"]), user=public(user))

    @app.get("/api/users/me")
    @require_auth()
    def me():
        with db.transaction() as tx:
            user = tx.one("SELECT * FROM users WHERE id = :i", i=current_user()["id"])
        if user is None:
            return jsonify(error="Account no longer exists."), 401
        return jsonify(user=public(user))

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
