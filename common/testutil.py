"""Helpers for the unit tests (each service is loaded by file path so that the
four `app.py` files never clash)."""
import importlib.util
import os
import sys
import tempfile

from common.auth import issue_token

os.environ.setdefault("LOG_REQUESTS", "0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_service(name):
    spec = importlib.util.spec_from_file_location(f"{name}_service_app", os.path.join(ROOT, "services", name, "app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def temp_db_url():
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    return f"sqlite:///{path}"


def bearer(user_id=1, username="alice", role="student"):
    return {"Authorization": f"Bearer {issue_token(user_id, username, role)}"}


def load_frontend():
    spec = importlib.util.spec_from_file_location("frontend_app", os.path.join(ROOT, "frontend", "app.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["frontend_app"] = module   # Flask finds templates/ via the module's file path
    spec.loader.exec_module(module)
    return module
