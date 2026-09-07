from azure.storage.blob import BlobServiceClient
from .base import BaseStorageProvider
from app.config import Config

class AzureStorageProvider(BaseStorageProvider):
    def save_file(self, file_name: str, content_bytes: bytes, project_id: int, project_name: str = "project") -> str:
        safe_project_name = "".join([c if c.isalnum() or c in (" ", "_", "-") else "_" for c in project_name]).strip().replace(" ", "_")
        folder_name = f"project_{project_id}_{safe_project_name}"
        
        try:
            blob_service_client = BlobServiceClient.from_connection_string(Config.AZURE_STORAGE_CONNECTION_STRING)
            container_client = blob_service_client.get_container_client(Config.AZURE_CONTAINER_NAME)
            
            # Construct Azure Blob Key
            blob_name = f"{folder_name}/{file_name}"
            
            # Get blob client and upload
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(content_bytes, overwrite=True)
            
            azure_uri = f"azure://{Config.AZURE_CONTAINER_NAME}/{blob_name}"
            print(f"[Storage] Saved file to Azure Blob: {azure_uri}")
            return azure_uri
            
        except Exception as e:
            print(f"[Storage] Error uploading to Azure Blob: {e}")
            raise e
