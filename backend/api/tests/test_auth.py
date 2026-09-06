"""Lightweight username/password login."""

from backend.api.security import hash_password, verify_password


def test_hash_roundtrip_and_salting():
    h1 = hash_password("hunter2")
    h2 = hash_password("hunter2")
    assert h1 != h2  # per-hash salt
    assert verify_password("hunter2", h1)
    assert not verify_password("hunter3", h1)
    assert not verify_password("hunter2", None)
    assert not verify_password("hunter2", "garbage")


def test_register_then_login(client):
    r = client.post(
        "/auth/register", json={"username": "alice", "password": "s3cret", "target": "exam"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice" and body["target"] == "exam"
    uid = body["id"]

    ok = client.post("/auth/login", json={"username": "alice", "password": "s3cret"})
    assert ok.status_code == 200 and ok.json()["id"] == uid

    # the id works everywhere a user id is expected
    assert client.get(f"/users/{uid}").json()["username"] == "alice"
    s = client.post("/study/sessions", json={"user_id": uid, "minutes_available": 10})
    assert s.status_code == 201


def test_login_is_case_insensitive_on_username(client):
    client.post("/auth/register", json={"username": "Bob", "password": "passsss"})
    assert (
        client.post("/auth/login", json={"username": "bob", "password": "passsss"}).status_code
        == 200
    )


def test_duplicate_username_rejected(client):
    client.post("/auth/register", json={"username": "carol", "password": "passsss"})
    dup = client.post("/auth/register", json={"username": "carol", "password": "other1"})
    assert dup.status_code == 409


def test_bad_credentials_rejected(client):
    client.post("/auth/register", json={"username": "dave", "password": "passsss"})
    assert (
        client.post("/auth/login", json={"username": "dave", "password": "wrong1"}).status_code
        == 401
    )
    assert (
        client.post("/auth/login", json={"username": "nobody", "password": "passsss"}).status_code
        == 401
    )


def test_register_validation(client):
    assert (
        client.post("/auth/register", json={"username": "x y", "password": "passsss"}).status_code
        == 422
    )
    assert (
        client.post("/auth/register", json={"username": "ok", "password": "no"}).status_code == 422
    )
