from app.config import Config
from .base import BaseDBProvider
from .default_provider import DefaultMySQLProvider
from .aws_provider import AwsMySQLProvider
from .azure_provider import AzureMySQLProvider

class DBFactory:
    _instance = None

    @classmethod
    def get_provider(cls) -> BaseDBProvider:
        if cls._instance is None:
            provider = Config.DB_PROVIDER.upper()
            if provider == "AWS":
                cls._instance = AwsMySQLProvider()
            elif provider == "AZURE":
                cls._instance = AzureMySQLProvider()
            else:
                cls._instance = DefaultMySQLProvider()
        return cls._instance
