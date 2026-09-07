from mysql.connector import pooling
from app.config import Config
from .base import BaseDBProvider

class DefaultMySQLProvider(BaseDBProvider):
    def __init__(self):
        self._pool = None

    def init_pool(self):
        if self._pool is None:
            effective_pool_size = max(1, min(int(Config.MYSQL_POOL_SIZE), 32))
            print(f"[Database] Connecting to Local MySQL at {Config.MYSQL_HOST}:{Config.MYSQL_PORT} (DB: {Config.MYSQL_DATABASE}, User: {Config.MYSQL_USER}, Pool Size: {effective_pool_size})...")
            try:
                self._pool = pooling.MySQLConnectionPool(
                    pool_name="tdd_pool_default",
                    pool_size=effective_pool_size,
                    pool_reset_session=True,
                    host=Config.MYSQL_HOST,
                    port=Config.MYSQL_PORT,
                    database=Config.MYSQL_DATABASE,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                    autocommit=False,
                    connection_timeout=15,
                )
                print(f"[Database] Connection successful: connected to {Config.MYSQL_DATABASE} on {Config.MYSQL_HOST}:{Config.MYSQL_PORT}")
            except Exception as e:
                print(f"[Database] Connection failed ({Config.MYSQL_HOST}:{Config.MYSQL_PORT}): {e}")
                raise e
        return self._pool
