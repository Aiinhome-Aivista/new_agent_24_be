import os
from .base import BaseStorageProvider
from app.config import Config

class LocalStorageProvider(BaseStorageProvider):
    def save_file(self, file_name: str, content_bytes: bytes, project_id: int, project_name: str = "project") -> str:
        safe_project_name = "".join([c if c.isalnum() or c in (" ", "_", "-") else "_" for c in project_name]).strip().replace(" ", "_")
        folder_name = f"project_{project_id}_{safe_project_name}"
        
        # Determine the base directory
        base_dir = os.path.abspath(Config.UPLOAD_PATH)
        project_dir = os.path.join(base_dir, folder_name)
        
        # Ensure directory exists
        os.makedirs(project_dir, exist_ok=True)
        
        # Full file path
        file_path = os.path.join(project_dir, file_name)
        
        # Write binary content
        with open(file_path, 'wb') as f:
            f.write(content_bytes)
            
        print(f"[Storage] Saved file to local path: {file_path}")
        return file_path
