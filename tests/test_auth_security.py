from app.auth.security import hash_password, verify_password, issue_access, decode


def test_password_hash_roundtrip():
    h = hash_password("Passw0rd!")
    assert verify_password("Passw0rd!", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token = issue_access(42, ["DEVELOPER"], ["workflow.create"])
    payload = decode(token)
    assert payload["sub"] == 42
    assert payload["type"] == "access"
    assert "workflow.create" in payload["perms"]
