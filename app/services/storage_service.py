import os
from .storage.factory import StorageFactory

def save_file(file_name: str, content_bytes: bytes, project_id: int, project_name: str = " project\) -> str:
    """
    Saves the file using the globally configured Storage Provider (AWS, AZURE, DEFAULT).
    Returns the storage URI or path.
    """
    provider = StorageFactory.get_provider()
    return provider.save_file(file_name, content_bytes, project_id, project_name)

def init_upload_dir():
    from app.config import Config
    """Ensure upload directory exists for local development"""
    os.makedirs(Config.UPLOAD_PATH, exist_ok=True)
