import pytest

from app.core import auth
from app.core.enums import Role
from app.core.errors import DomainError
from tests.factories import make_user


def test_password_hash_verifies_only_the_right_password():
    hashed = auth.hash_password("abcd1234")

    assert hashed != "abcd1234"
    assert auth.verify_password("abcd1234", hashed)
    assert not auth.verify_password("abcd12345", hashed)


def test_access_token_carries_user_and_session():
    token = auth.issue_access_token(user_id=3, session_id=7)

    claims = auth.decode_access_token(token)
    assert (claims.user_id, claims.session_id) == (3, 7)


def test_tampered_token_is_rejected():
    token = auth.issue_access_token(user_id=3, session_id=7)

    with pytest.raises(DomainError) as error:
        auth.decode_access_token(token[:-2] + "xx")
    assert error.value.code == "UNAUTHENTICATED"


def test_writer_may_act_only_on_own_resources(db):
    writer = make_user(db, "newbie@club.tw", Role.WRITER)
    publisher = make_user(db, "pr@club.tw", Role.PUBLISHER)

    auth.ensure_owner_or_role(writer, owner_id=writer.id, min_role=Role.PUBLISHER)
    auth.ensure_owner_or_role(publisher, owner_id=writer.id, min_role=Role.PUBLISHER)
    with pytest.raises(DomainError) as error:
        auth.ensure_owner_or_role(writer, owner_id=publisher.id, min_role=Role.PUBLISHER)
    assert (error.value.status_code, error.value.code) == (403, "FORBIDDEN")


def test_role_order_is_admin_publisher_writer():
    assert auth.has_role(Role.ADMIN, Role.PUBLISHER)
    assert auth.has_role(Role.PUBLISHER, Role.PUBLISHER)
    assert not auth.has_role(Role.WRITER, Role.PUBLISHER)
    assert not auth.has_role(Role.PUBLISHER, Role.ADMIN)
