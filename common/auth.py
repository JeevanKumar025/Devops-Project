"""JWT helpers shared by all services (HS256, one shared secret)."""
import functools
import os
import time

import jwt
from flask import g, jsonify, request

ALGORITHM = "HS256"
TOKEN_HOURS = 8


def _secret():
    return os.environ.get("JWT_SECRET", "dev-only-secret-change-me-before-deploying-0123456789")


def issue_token(user_id, username, role):
    now = int(time.time())
    payload = {"sub": str(user_id), "username": username, "role": role,
               "iat": now, "exp": now + TOKEN_HOURS * 3600}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def bearer_token():
    header = request.headers.get("Authorization", "")
    return header[7:] if header.startswith("Bearer ") else None


def current_user():
    """Return {'id', 'username', 'role'} from the request's JWT, or None."""
    if "user" not in g:
        g.user = None
        token = bearer_token()
        if token:
            try:
                claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
                g.user = {"id": int(claims["sub"]), "username": claims["username"], "role": claims["role"]}
            except (jwt.PyJWTError, KeyError, ValueError):
                g.user = None
    return g.user


def require_auth(*roles):
    """Decorator: 401 without a valid token, 403 if the role is not allowed."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return jsonify(error="Authentication required."), 401
            if roles and user["role"] not in roles:
                return jsonify(error="You do not have permission for this action."), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator
