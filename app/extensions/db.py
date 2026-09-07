"""MySQL connection pool + query helpers. All SQL is issued via repositories."""
import time
from contextlib import contextmanager
import mysql.connector
from app.services.db.factory import DBFactory

_pool = None


def init_pool():
    global _pool
    if _pool is None:
        provider = DBFactory.get_provider()
        _pool = provider.init_pool()
    return _pool


def check_connection():
    """Verify database connection on application startup."""
    try:
        init_pool()
        return True
    except Exception:
        return False


def get_connection():
    """Acquire a pooled connection with intelligent backoff retry to handle concurrent request bursts."""
    pool = init_pool()
    max_attempts = 8
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            conn = pool.get_connection()
            if not conn.is_connected():
                conn.ping(reconnect=True, attempts=2, delay=0.2)
            return conn
        except Exception as e:
            last_exc = e
            if attempt == max_attempts:
                print(f"[Database] Connection pool exhausted after {max_attempts} attempts: {e}")
                raise e
            sleep_time = min(0.08 * (1.6 ** (attempt - 1)), 0.6)
            time.sleep(sleep_time)


@contextmanager
def get_db_connection(autocommit=False):
    """
    Context manager yielding a pooled connection and guaranteeing commit/rollback/close.
    Enables multi-statement transactions over a single connection instead of per-query checkouts.
    """
    conn = get_connection()
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def query(sql: str, params: tuple = (), *, fetchone: bool = False):
    conn = get_connection()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchone() if fetchone else cur.fetchall()
        return rows
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass


def execute(sql: str, params: tuple = (), *, return_id: bool = False, return_rowcount: bool = False):
    conn = get_connection()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        conn.commit()
        last_id = cur.lastrowid
        rowcount = cur.rowcount
        if return_id:
            return last_id
        if return_rowcount:
            return rowcount
        return None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise e
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass
