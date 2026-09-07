from mysql.connector import pooling
from app.config import Config
from .base import BaseDBProvider

class AzureMySQLProvider(BaseDBProvider):
    def __init__(self):
        self._pool = None

    def init_pool(self):
        if self._pool is None:
            effective_pool_size = max(1, min(int(Config.MYSQL_POOL_SIZE), 32))
            print(f"[Database] Connecting to Azure Database for MySQL at {Config.AZURE_DB_HOST}:{Config.AZURE_DB_PORT} (DB: {Config.AZURE_DB_DATABASE}, User: {Config.AZURE_DB_USER}, Pool Size: {effective_pool_size})...")
            try:
                self._pool = pooling.MySQLConnectionPool(
                    pool_name="tdd_pool_azure",
                    pool_size=effective_pool_size,
                    pool_reset_session=True,
                    host=Config.AZURE_DB_HOST,
                    port=Config.AZURE_DB_PORT,
                    database=Config.AZURE_DB_DATABASE,
                    user=Config.AZURE_DB_USER,
                    password=Config.AZURE_DB_PASSWORD,
                    autocommit=False,
                    connection_timeout=15,
                )
                print(f"[Database] Connection successful: connected to {Config.AZURE_DB_DATABASE} on Azure")
            except Exception as e:
                print(f"[Database] Connection failed on Azure ({Config.AZURE_DB_HOST}:{Config.AZURE_DB_PORT}): {e}")
                raise e
        return self._pool
