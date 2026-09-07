from app.config import Config
from .base import BaseStorageProvider
from .local_storage import LocalStorageProvider
from .aws_storage import AwsStorageProvider
from .azure_storage import AzureStorageProvider

class StorageFactory:
    @staticmethod
    def get_provider() -> BaseStorageProvider:
        provider = Config.CLOUD_PROVIDER.upper()
        
        if provider == "AWS":
            return AwsStorageProvider()
        elif provider == "AZURE":
            return AzureStorageProvider()
        else:
            return LocalStorageProvider()
