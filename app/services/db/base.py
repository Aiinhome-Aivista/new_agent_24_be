from abc import ABC, abstractmethod

class BaseDBProvider(ABC):
    @abstractmethod
    def init_pool(self):
        """
        Initialize and return the database connection pool.
        """
        pass
