"""Auth edges from the code and security review (#87).

Each test is a way in that should stay shut: a service token used as a
session, a disabled account, forged proxy headers, input bcrypt refuses, a
redirect that leaves the hub, game output rendered as HTML, and text that
would break out of a config file or a nodelist line.
"""
import sys
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, management_app, service_app
from backend.api.management import processing as processing_api
from backend.api.management.auth import _safe_next
from backend.core import rate_limiter
from backend.core.config import get_config
from backend.core.database import get_db
from backend.core.security import (
    COOKIE_NAME,
    create_service_token,
    get_password_hash,
    validate_password,
    verify_password,
)
from backend.models.database import (
    AuditEvent,
    Base,
    ClaimLink,
    Client,
    ProcessingRun,
    SysopUser,
)
from backend.schemas.applications import JoinApplicationRequest
from backend.services import claim_links
from backend.services.claim_links import _psd1_str, _toml_str

API = "/management/api/v1"
PASSWORD = "Correct-Horse-9"


@pytest.fixture
def hub():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    admin = SysopUser(username="admin", hashed_password=get_password_hash(PASSWORD),
                      is_superuser=True)
    sysop = SysopUser(username="board", hashed_password=get_password_hash(PASSWORD))
    # A BBS whose client_id happens to equal a sysop's username.
    board = Client(client_id="board", client_secret=get_password_hash("s3cret"),
                   bbs_name="The Board")
    db.add_all([admin, sysop, board])
    db.commit()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    saved = {a: dict(a.dependency_overrides) for a in (app, management_app, service_app)}
    for a in (app, management_app, service_app):
        a.dependency_overrides[get_db] = override_get_db
    rate_limiter._attempts.clear()
    rate_limiter._lockouts.clear()

    yield TestClient(app, base_url="https://testserver"), db, admin, sysop, board
    db.close()
    for a, overrides in saved.items():
        a.dependency_overrides.clear()
        a.dependency_overrides.update(overrides)
    rate_limiter._attempts.clear()
    rate_limiter._lockouts.clear()


def _login(client, username, password=PASSWORD, **headers):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password},
                       headers=headers)


# -- tokens and accounts ------------------------------------------------------

def test_a_service_token_is_not_a_session_on_the_claim_page(hub):
    client, db, _, sysop, board = hub
    token = claim_links.issue(db, board, "admin", user=sysop)[0]
    client.cookies.set(COOKIE_NAME, create_service_token("board"))

    response = client.post(f"{API}/claim/{token}")

    assert response.status_code == 401  # not signed in, whatever the cookie says
    db.expire_all()
    assert db.query(ClaimLink).one().used_at is None


def test_a_disabled_account_cannot_sign_in_and_a_good_sign_in_is_recorded(hub):
    client, db, _, sysop, _ = hub
    assert _login(client, "board").status_code == 200
    db.expire_all()
    assert db.get(SysopUser, sysop.id).last_login is not None

    sysop.is_active = False
    db.commit()
    response = _login(client, "board")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


def test_an_admin_disables_and_enables_an_account_but_not_their_own(hub):
    client, db, admin, sysop, _ = hub
    _login(client, "admin")

    assert client.put(f"{API}/users/{sysop.id}", json={"is_active": False}).json()["is_active"] is False
    assert client.put(f"{API}/users/{sysop.id}", json={"is_active": True}).json()["is_active"] is True
    assert client.put(f"{API}/users/{admin.id}", json={"is_active": False}).status_code == 400

    db.expire_all()
    assert [e.action for e in db.query(AuditEvent).order_by(AuditEvent.id)] == [
        "user.disabled", "user.enabled"]


# -- proxies and rate limits --------------------------------------------------

def test_forwarded_for_from_an_untrusted_peer_does_not_dodge_the_lockout(hub):
    client = hub[0]
    limit = get_config().rate_limiting.auth_attempts_per_minute
    for i in range(limit):
        _login(client, "admin", "wrong", **{"X-Forwarded-For": f"203.0.113.{i}"})

    response = _login(client, "admin", **{"X-Forwarded-For": "198.51.100.7"})

    assert response.status_code == 429


def test_the_trusted_proxy_is_believed_about_the_address_it_saw(hub, monkeypatch):
    client = hub[0]
    monkeypatch.setattr(get_config().security, "trusted_proxies", ["testclient"])
    limit = get_config().rate_limiting.auth_attempts_per_minute
    for _ in range(limit):
        # The left entry is the client's own claim; the proxy appended the right one.
        _login(client, "admin", "wrong", **{"X-Forwarded-For": "10.9.9.9, 203.0.113.5"})

    assert _login(client, "admin", **{"X-Forwarded-For": "203.0.113.5"}).status_code == 429
    assert _login(client, "admin", **{"X-Forwarded-For": "203.0.113.6"}).status_code == 200


def test_the_rate_limiter_forgets_addresses_that_went_quiet(monkeypatch):
    rate_limiter._attempts.clear()
    rate_limiter._lockouts.clear()
    rate_limiter._attempts["192.0.2.1"] = [0.0]
    rate_limiter._lockouts["192.0.2.2"] = 1.0

    rate_limiter._prune(now=1000.0, window=60.0)

    assert not rate_limiter._attempts and not rate_limiter._lockouts


def test_links_ignore_a_forged_forwarded_host_and_refuse_a_bad_host(hub, monkeypatch):
    client, db, _, _, board = hub
    import importlib
    config_mod = importlib.import_module("backend.core.config")
    monkeypatch.setattr(config_mod, "get_config", lambda: {"server": {}})
    _login(client, "admin")

    link = client.post(f"{API}/clients/{board.id}/claim-link",
                       headers={"X-Forwarded-Host": "evil.example"})
    assert link.json()["url"].startswith("https://testserver/claim/")

    bad = client.post(f"{API}/clients/{board.id}/claim-link",
                      headers={"Host": "evil host"})
    assert bad.status_code == 400


# -- passwords ----------------------------------------------------------------

@pytest.mark.parametrize("password", ["a" * 100, "a\x00b", "x"])
def test_bcrypt_input_it_refuses_is_a_failed_check_not_an_error(password):
    assert verify_password(password, get_password_hash("Something-1")) is False
    assert verify_password("Something-1", "not a bcrypt hash") is False


@pytest.mark.parametrize("password", ["Aa1" + "é" * 40, "Aa1aaaaaaaaa\x00"])
def test_a_new_password_must_fit_bcrypt(password):
    with pytest.raises(ValueError):
        validate_password(password)


def test_an_unknown_bbs_takes_as_long_as_a_wrong_secret(hub, monkeypatch):
    client = hub[0]
    checked = []
    real = verify_password

    def counting(plain, hashed):
        checked.append(plain)
        return real(plain, hashed)

    from backend.core import security
    monkeypatch.setattr(security, "verify_password", counting)
    client.post("/service/api/v1/auth/token", data={
        "grant_type": "client_credentials", "client_id": "nobody", "client_secret": "guess"})

    assert checked == ["guess"]


# -- redirects ----------------------------------------------------------------

@pytest.mark.parametrize("path", ["/\t/evil.example", "/\n/evil.example", "//evil.example",
                                  "/\\evil.example", "https://evil.example", "/ok\x7f"])
def test_sign_in_never_redirects_off_the_hub(path):
    assert _safe_next(path) == "/dashboard"


def test_a_hub_path_is_kept():
    assert _safe_next("/clients/3?tab=keys") == "/clients/3?tab=keys"


# -- rendering ----------------------------------------------------------------

def test_a_transcript_that_cannot_be_converted_is_escaped_not_rendered(hub, monkeypatch):
    client, db, _, _, _ = hub
    run = ProcessingRun(status="completed", dosemu_log="<img src=x onerror=alert(1)>")
    db.add(run)
    db.commit()

    async def broken(_):
        raise RuntimeError("terminal-to-html missing")

    monkeypatch.setattr(processing_api, "ansi_to_html", broken)
    _login(client, "admin")
    body = client.get(f"{API}/processing/runs/{run.id}").json()

    assert "<img" not in body["dosemu_output_html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in body["dosemu_output_html"]


def test_config_strings_survive_any_name():
    name = 'Odd "Board"\\\x07\ttab'
    assert tomllib.loads(f"name = {_toml_str(name)}")["name"] == name
    assert _psd1_str("It’s") == "'It’’s'"


@pytest.mark.parametrize("field", ["bbs_name", "city", "sysop_name", "address"])
def test_a_join_application_is_one_line_per_field(field):
    fields = {"bbs_name": "Board", "league_ids": [1], field: "Board\n2"}
    with pytest.raises(ValueError):
        JoinApplicationRequest(**fields)
