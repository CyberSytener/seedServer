from app.api.auth_routes import (
    _is_valid_public_email,
    _normalize_public_username,
    _resolve_open_registration_identity,
)
from app.infrastructure.db.sqlite import DB


def test_open_registration_normalizes_missing_username():
    username = _normalize_public_username("")

    assert username.startswith("neo_")
    assert len(username) >= 7


def test_open_registration_uses_local_email_when_email_is_missing(tmp_path):
    db = DB(str(tmp_path / "auth.db"))
    db.init_schema()

    username, email = _resolve_open_registration_identity(db, "New User", "")

    assert username == "new_user"
    assert email == "new_user@users.neoeats.local"


def test_open_registration_avoids_existing_username_and_email(tmp_path):
    db = DB(str(tmp_path / "auth.db"))
    db.init_schema()
    db.execute(
        "INSERT INTO users(id, email, meta_json, is_admin, is_banned) VALUES(?,?,?,?,?)",
        ("neo_user", "neo@example.com", "{}", 0, 0),
    )

    username, email = _resolve_open_registration_identity(db, "neo_user", "neo@example.com")

    assert username != "neo_user"
    assert email.endswith("@users.neoeats.local")


def test_open_registration_email_validation():
    assert _is_valid_public_email("person@example.com") is True
    assert _is_valid_public_email("person") is False
