"""Route protection + RBAC enforced on the backend (never only in the UI)."""
from functools import wraps
from flask import request, g
import jwt as pyjwt
from app.auth.security import decode
from app.errors.handlers import fail


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return fail("UNAUTHORIZED", "Missing bearer token", 401)
        try:
            payload = decode(header.split(" ", 1)[1])
        except pyjwt.ExpiredSignatureError:
            return fail("TOKEN_EXPIRED", "Access token expired", 401)
        except pyjwt.InvalidTokenError:
            return fail("INVALID_TOKEN", "Invalid access token", 401)
        if payload.get("type") != "access":
            return fail("INVALID_TOKEN", "Not an access token", 401)
        raw_sub = payload.get("sub")
        g.user_id = int(raw_sub) if str(raw_sub).isdigit() else raw_sub
        g.roles = payload.get("roles", [])
        g.perms = payload.get("perms", [])
        return fn(*args, **kwargs)
    return wrapper


def require_permission(*needed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            perms = set(getattr(g, "perms", []))
            if "admin.manage" in perms:  # admin superset
                return fn(*args, **kwargs)
            if not set(needed).issubset(perms):
                return fail("FORBIDDEN", "Insufficient permission", 403,
                            {"required": list(needed)})
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_role(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not set(roles).intersection(getattr(g, "roles", [])):
                return fail("FORBIDDEN", "Insufficient role", 403, {"required": list(roles)})
            return fn(*args, **kwargs)
        return wrapper
    return deco
