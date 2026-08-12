"""JWT (access + refresh) and bcrypt password hashing."""
import datetime
import bcrypt
import jwt
from app.config import Config


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def _encode(payload: dict, minutes: int = None, days: int = None) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    exp = now + (datetime.timedelta(minutes=minutes) if minutes else datetime.timedelta(days=days))
    return jwt.encode({**payload, "iat": now, "exp": exp}, Config.JWT_SECRET, algorithm="HS256")


def issue_access(user_id: int, roles: list, permissions: list) -> str:
    return _encode({"sub": user_id, "type": "access", "roles": roles, "perms": permissions},
                   minutes=Config.JWT_ACCESS_MINUTES)


def issue_refresh(user_id: int) -> str:
    return _encode({"sub": user_id, "type": "refresh"}, days=Config.JWT_REFRESH_DAYS)


def decode(token: str) -> dict:
    return jwt.decode(token, Config.JWT_SECRET, algorithms=["HS256"])
