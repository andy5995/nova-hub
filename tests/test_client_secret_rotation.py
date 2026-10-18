"""Rotating a BBS's client secret: by an admin or the BBS's own sysop.

What matters is what each secret and token can do afterwards. Stopping the
old secret at once also ends the tokens issued with it; a window keeps both
the old secret and its tokens working until it closes.
"""
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, management_app, service_app
from backend.core import rate_limiter
from backend.core.clock import utcnow
from backend.core.database import get_db
from backend.core.security import get_current_user, get_password_hash
from backend.models.database import AuditEvent, Base, Client, ClientOwner, SysopUser

CLIENTS = "/management/api/v1/clients"
TOKEN_URL = "/service/api/v1/auth/token"
VERIFY_URL = "/service/api/v1/auth/verify"


@pytest.fixture
def hub():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = Session()
    admin = SysopUser(username="admin", hashed_password="x", is_superuser=True)
    owner = SysopUser(username="owner", idp_subject="user_owner")
    other = SysopUser(username="other", idp_subject="user_other")
    board = Client(client_id="board", client_secret=get_password_hash("old-secret"),
                   bbs_name="The Board")
    db.add_all([admin, owner, other, board])
    db.commit()
    db.add(ClientOwner(sysop_user_id=owner.id, client_id=board.id))
    db.commit()

    acting = {"user": admin}

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def current_user():
        return Session().get(SysopUser, acting["user"].id)

    saved = {a: dict(a.dependency_overrides) for a in (app, management_app, service_app)}
    for a in (app, management_app, service_app):
        a.dependency_overrides[get_db] = override_get_db
        a.dependency_overrides[get_current_user] = current_user
    rate_limiter._attempts.clear()
    rate_limiter._lockouts.clear()

    def act_as(name):
        acting["user"] = {"admin": admin, "owner": owner, "other": other}[name]

    yield TestClient(app, base_url="https://testserver"), db, act_as, board
    db.close()
    for a, overrides in saved.items():
        a.dependency_overrides.clear()
        a.dependency_overrides.update(overrides)


def _token(client, secret):
    response = client.post(TOKEN_URL, data={"grant_type": "client_credentials",
                                              "client_id": "board", "client_secret": secret})
    return response.json()["access_token"] if response.status_code == 200 else None


def _token_works(client, token):
    return client.get(VERIFY_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def _rotate(client, board, **body):
    return client.post(f"{CLIENTS}/{board.id}/regenerate-secret", json=body or None)


def test_the_bbs_owner_can_rotate_and_another_sysop_cannot(hub):
    client, _, act_as, board = hub

    act_as("other")
    assert _rotate(client, board).status_code == 404
    assert _token(client, "old-secret")

    act_as("owner")
    response = _rotate(client, board)
    assert response.status_code == 200
    assert _token(client, response.json()["client_secret"])


def test_stopping_the_old_secret_ends_its_tokens_too(hub):
    client, _, _, board = hub
    old_token = _token(client, "old-secret")
    assert _token_works(client, old_token)

    body = _rotate(client, board).json()

    assert body["old_secret_until"] is None
    assert _token(client, "old-secret") is None
    assert not _token_works(client, old_token)
    new_token = _token(client, body["client_secret"])
    assert _token_works(client, new_token)


def test_a_window_keeps_the_old_secret_and_its_tokens_until_it_closes(hub):
    client, db, _, board = hub
    old_token = _token(client, "old-secret")

    body = _rotate(client, board, overlap_hours=24).json()

    assert body["old_secret_until"]
    assert _token(client, "old-secret")
    assert _token(client, body["client_secret"])
    assert _token_works(client, old_token)
    assert client.get(f"{CLIENTS}/{board.id}").json()["old_secret_until"] == body["old_secret_until"]

    db.expire_all()
    stored = db.get(Client, board.id)
    stored.previous_secret_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert _token(client, "old-secret") is None
    assert _token(client, body["client_secret"])
    assert client.get(f"{CLIENTS}/{board.id}").json()["old_secret_until"] is None


def test_rotating_again_in_a_window_keeps_only_the_secret_just_replaced(hub):
    client, _, _, board = hub
    second = _rotate(client, board, overlap_hours=24).json()["client_secret"]

    third = _rotate(client, board, overlap_hours=24).json()["client_secret"]

    assert _token(client, "old-secret") is None
    assert _token(client, second) and _token(client, third)


@pytest.mark.parametrize("hours", [-1, 73])
def test_the_window_is_at_most_three_days(hub, hours):
    client, _, _, board = hub
    assert _rotate(client, board, overlap_hours=hours).status_code == 422
    assert _token(client, "old-secret")


def test_the_audit_log_says_who_rotated_and_what_became_of_the_old_secret(hub):
    client, db, act_as, board = hub
    act_as("owner")
    _rotate(client, board, overlap_hours=24)
    act_as("admin")
    _rotate(client, board)

    db.expire_all()
    events = db.query(AuditEvent).filter(AuditEvent.action == "client.secret_regenerated") \
        .order_by(AuditEvent.id).all()
    assert [e.actor for e in events] == ["owner", "admin"]
    assert events[0].detail.startswith("old secret works until ")
    assert events[1].detail == "old secret stopped"
