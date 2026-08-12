"""Redis client accessor (lazy)."""
import redis
from app.config import Config

_client = None


def get_redis():
    global _client
    if _client is None:
        _client = redis.from_url(Config.REDIS_URL, decode_responses=True)
    return _client
