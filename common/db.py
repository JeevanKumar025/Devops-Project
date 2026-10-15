"""Tiny database layer: SQLite for local dev/tests, PostgreSQL in Docker/Kubernetes.

Every service owns its own database. The service picks the engine from the
DATABASE_URL environment variable:
    sqlite:///path/to/file.db          (default for local runs and unit tests)
    postgresql://user:pass@host:5432/db (used by docker-compose and Kubernetes)

SQL is written once with :named parameters and works on both engines.
"""
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

_PARAM = re.compile(r"(?<!:):([A-Za-z_]\w*)")


def now_local():
    """Current time as 'YYYY-MM-DD HH:MM:SS' in the campus timezone (default IST)."""
    offset = int(os.environ.get("UTC_OFFSET_MINUTES", "330"))
    tz = timezone(timedelta(minutes=offset))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def today_local():
    return now_local()[:10]


class Tx:
    """One transaction. Use db.transaction() rather than creating this directly."""

    def __init__(self, conn, is_pg):
        self.conn, self.is_pg = conn, is_pg

    def _sql(self, sql):
        return _PARAM.sub(r"%(\1)s", sql) if self.is_pg else sql

    def execute(self, sql, **params):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        return cur

    def all(self, sql, **params):
        return [dict(r) for r in self.execute(sql, **params).fetchall()]

    def one(self, sql, **params):
        row = self.execute(sql, **params).fetchone()
        return dict(row) if row is not None else None

    def insert(self, sql, **params):
        """Run an INSERT and return the new row id (works on SQLite >= 3.35 and PostgreSQL)."""
        return self.execute(sql + " RETURNING id", **params).fetchone()["id"]


class Database:
    def __init__(self, url=None):
        self.url = url or os.environ.get("DATABASE_URL", "sqlite:///campuseats.db")
        self.is_pg = self.url.startswith(("postgres://", "postgresql://"))
        if self.is_pg:
            import psycopg2
            self.integrity_errors = (psycopg2.IntegrityError,)
        else:
            self.path = self.url.replace("sqlite:///", "", 1)
            self.integrity_errors = (sqlite3.IntegrityError,)

    def _connect(self):
        if self.is_pg:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            return psycopg2.connect(self.url, cursor_factory=RealDictCursor, connect_timeout=5)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transaction(self):
        conn = self._connect()
        try:
            yield Tx(conn, self.is_pg)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self, statements, retries=40, delay=1.5):
        """Create tables. Retries so a service can start before its database is ready."""
        pk = "SERIAL PRIMARY KEY" if self.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for attempt in range(retries):
            try:
                for stmt in statements:
                    # Own transaction per statement: on PostgreSQL a failed statement would
                    # otherwise abort the rest (two replicas may create tables at once).
                    try:
                        with self.transaction() as tx:
                            tx.execute(stmt.replace("{pk}", pk))
                    except self.integrity_errors:
                        pass
                return
            except Exception as exc:  # database not up yet
                if attempt == retries - 1:
                    raise
                print(f"[db] waiting for database ({exc.__class__.__name__}), retry {attempt + 1}", flush=True)
                time.sleep(delay)

    def ping(self):
        with self.transaction() as tx:
            tx.execute("SELECT 1")
