from abc import ABC, abstractmethod

class BaseStorageProvider(ABC):
    @abstractmethod
    def save_file(self, file_name: str, content_bytes: bytes, project_id: int, project_name: str = "project") -> str:
        """
        Save a file and return the URI or path where it was saved.
        """
        pass
