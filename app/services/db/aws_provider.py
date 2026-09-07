from mysql.connector import pooling
from app.config import Config
from .base import BaseDBProvider

class AwsMySQLProvider(BaseDBProvider):
    def __init__(self):
        self._pool = None

    def init_pool(self):
        if self._pool is None:
            effective_pool_size = max(1, min(int(Config.MYSQL_POOL_SIZE), 32))
            print(f"[Database] Connecting to AWS RDS MySQL at {Config.AWS_RDS_HOST}:{Config.AWS_RDS_PORT} (DB: {Config.AWS_RDS_DATABASE}, User: {Config.AWS_RDS_USER}, Pool Size: {effective_pool_size})...")
            try:
                self._pool = pooling.MySQLConnectionPool(
                    pool_name="tdd_pool_aws",
                    pool_size=effective_pool_size,
                    pool_reset_session=True,
                    host=Config.AWS_RDS_HOST,
                    port=Config.AWS_RDS_PORT,
                    database=Config.AWS_RDS_DATABASE,
                    user=Config.AWS_RDS_USER,
                    password=Config.AWS_RDS_PASSWORD,
                    autocommit=False,
                    connection_timeout=15,
                )
                print(f"[Database] Connection successful: connected to {Config.AWS_RDS_DATABASE} on AWS RDS")
            except Exception as e:
                print(f"[Database] Connection failed on AWS RDS ({Config.AWS_RDS_HOST}:{Config.AWS_RDS_PORT}): {e}")
                raise e
        return self._pool
