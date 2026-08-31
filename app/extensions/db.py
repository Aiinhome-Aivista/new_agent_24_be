"""MySQL connection pool + query helpers. All SQL is issued via repositories."""
import mysql.connector
from mysql.connector import pooling
from app.config import Config

_pool = None


def init_pool():
    global _pool
    if _pool is None:
        print(f"[Database] Connecting to MySQL at {Config.MYSQL_HOST}:{Config.MYSQL_PORT} (DB: {Config.MYSQL_DATABASE}, User: {Config.MYSQL_USER})...")
        try:
            _pool = pooling.MySQLConnectionPool(
                pool_name="tdd_pool",
                pool_size=Config.MYSQL_POOL_SIZE,
                pool_reset_session=True,
                host=Config.MYSQL_HOST,
                port=Config.MYSQL_PORT,
                database=Config.MYSQL_DATABASE,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                autocommit=False,
                connection_timeout=10,
                init_command="SET SESSION wait_timeout = 30, SESSION interactive_timeout = 30",
            )
            print(f"[Database] Connection successful: connected to {Config.MYSQL_DATABASE} on {Config.MYSQL_HOST}:{Config.MYSQL_PORT}")
        except Exception as e:
            print(f"[Database] Connection failed ({Config.MYSQL_HOST}:{Config.MYSQL_PORT}): {e}")
            raise e
    return _pool


def check_connection():
    """Verify database connection on application startup."""
    try:
        init_pool()
        return True
    except Exception:
        return False


def get_connection():
    pool = init_pool()
    try:
        conn = pool.get_connection()
        if not conn.is_connected():
            conn.ping(reconnect=True, attempts=3, delay=1)
        return conn
    except Exception:
        import time
        time.sleep(0.05)
        conn = pool.get_connection()
        if not conn.is_connected():
            conn.ping(reconnect=True, attempts=3, delay=1)
        return conn


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


def execute(sql: str, params: tuple = (), *, return_id: bool = False):
    conn = get_connection()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        conn.commit()
        last_id = cur.lastrowid
        return last_id if return_id else None
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

