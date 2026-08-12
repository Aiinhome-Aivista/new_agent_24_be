"""User + RBAC data access."""
from app.extensions.db import query, execute


def get_by_email(email):
    return query("SELECT * FROM users WHERE email=%s", (email,), fetchone=True)


def get_by_id(user_id):
    return query("SELECT id, uuid, name, email, is_active FROM users WHERE id=%s", (user_id,), fetchone=True)


def roles_for(user_id):
    rows = query("""SELECT r.code FROM user_roles ur
                    JOIN roles r ON r.id = ur.role_id WHERE ur.user_id=%s""", (user_id,))
    return [r["code"] for r in rows]


def permissions_for(user_id):
    rows = query("""SELECT DISTINCT p.code FROM user_roles ur
                    JOIN role_permissions rp ON rp.role_id = ur.role_id
                    JOIN permissions p ON p.id = rp.permission_id
                    WHERE ur.user_id=%s""", (user_id,))
    return [r["code"] for r in rows]


def touch_login(user_id):
    execute("UPDATE users SET last_login_at=NOW() WHERE id=%s", (user_id,))
