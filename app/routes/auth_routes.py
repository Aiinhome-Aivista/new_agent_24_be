from flask import Blueprint, request, g
from app.errors.handlers import ok, fail
from app.auth.security import verify_password, issue_access, issue_refresh, decode, hash_password
from app.auth.decorators import require_auth
from app.repositories.user_repo import get_by_email, get_by_id, roles_for, permissions_for, touch_login
from app.audit.audit_log import record as audit
import jwt as pyjwt

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    email, password = body.get("email"), body.get("password")
    if not email or not password:
        return fail("VALIDATION_ERROR", "email and password are required")
    user = get_by_email(email)
    if not user or not verify_password(password, user["password_hash"]) or not user["is_active"]:
        return fail("INVALID_CREDENTIALS", "Invalid email or password", 401)

    roles = roles_for(user["id"])
    perms = permissions_for(user["id"])
    touch_login(user["id"])
    audit("authentication", user_id=user["id"], status="SUCCESS")
    return ok({
        "access_token": issue_access(user["id"], roles, perms),
        "refresh_token": issue_refresh(user["id"]),
        "user": {"id": user["id"], "name": user["name"], "email": user["email"],
                 "roles": roles, "permissions": perms},
    })


@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    body = request.get_json(silent=True) or {}
    token = body.get("refresh_token", "")
    try:
        payload = decode(token)
    except pyjwt.InvalidTokenError:
        return fail("INVALID_TOKEN", "Invalid refresh token", 401)
    if payload.get("type") != "refresh":
        return fail("INVALID_TOKEN", "Not a refresh token", 401)
    uid = payload["sub"]
    roles, perms = roles_for(uid), permissions_for(uid)
    return ok({"access_token": issue_access(uid, roles, perms)})


@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    user = get_by_id(g.user_id)
    if not user:
        return fail("NOT_FOUND", "User not found", 404)
    return ok({**user, "roles": g.roles, "permissions": g.perms})


@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    audit("authentication", user_id=g.user_id, status="LOGOUT")
    return ok({}, "Logged out")
