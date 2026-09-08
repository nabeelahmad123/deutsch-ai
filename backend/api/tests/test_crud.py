"""CRUD coverage for the thin FastAPI layer."""

WORD = {
    "lemma": "Haus",
    "article": "das",
    "plural": "Häuser",
    "translation_en": "house",
    "cefr_level": "A1",
    "frequency_rank": 51,
    "ipa_or_audio_ref": "haʊ̯s",
}


def _mk(client, **over):
    body = {**WORD, **over}
    r = client.post("/words", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_word_create_get_and_dup(client):
    wid = _mk(client)["id"]
    assert client.get(f"/words/{wid}").json()["lemma"] == "Haus"
    assert client.get("/words/9999").status_code == 404
    assert client.post("/words", json=WORD).status_code == 409  # unique lemma


def test_word_list_is_a_paginated_envelope(client):
    _mk(client, lemma="Haus", cefr_level="A1", frequency_rank=51)
    _mk(client, lemma="Buch", cefr_level="A2", frequency_rank=700, topic="education", article="das")
    _mk(client, lemma="Zug", cefr_level="A2", frequency_rank=900, topic="transport", article="der")

    page = client.get("/words").json()
    assert page["total"] == 3 and page["limit"] == 100 and page["offset"] == 0
    assert [w["lemma"] for w in page["items"]] == ["Haus", "Buch", "Zug"]  # by frequency_rank

    assert client.get("/words", params={"cefr_level": "A2"}).json()["total"] == 2
    assert client.get("/words", params={"topic": "transport"}).json()["total"] == 1
    assert client.get("/words", params={"article": "der"}).json()["total"] == 1  # only Zug
    assert client.get("/words", params={"q": "bu"}).json()["items"][0]["lemma"] == "Buch"


def test_word_list_pagination(client):
    for i in range(5):
        _mk(client, lemma=f"w{i}", frequency_rank=100 + i)
    page = client.get("/words", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert [w["lemma"] for w in page["items"]] == ["w2", "w3"]


def test_word_list_rejects_bad_params(client):
    assert client.get("/words", params={"cefr_level": "C1"}).status_code == 422
    assert client.get("/words", params={"limit": 0}).status_code == 422
    assert client.get("/words", params={"offset": -1}).status_code == 422


def test_topics_endpoint(client):
    _mk(client, lemma="Buch", frequency_rank=700, topic="education")
    _mk(client, lemma="Schule", frequency_rank=710, topic="education")
    _mk(client, lemma="Zug", frequency_rank=900, topic="transport")
    _mk(client, lemma="Ding", frequency_rank=950)  # no topic
    topics = client.get("/topics").json()
    assert topics == [
        {"topic": "education", "count": 2},
        {"topic": "transport", "count": 1},
    ]


def test_word_validation_rejects_bad_rank(client):
    assert client.post("/words", json={**WORD, "frequency_rank": 0}).status_code == 422


def test_user_and_review_log_flow(client):
    assert client.post("/users", json={"target": "work"}).status_code == 201
    assert client.get("/users/1").json()["target"] == "work"
    assert client.get("/users/2").status_code == 404

    _mk(client)
    ok = client.post(
        "/review-logs",
        json={
            "user_id": 1,
            "word_id": 1,
            "correct": True,
            "response_time_ms": 900,
            "source": "new",
        },
    )
    assert ok.status_code == 201

    missing_word = client.post(
        "/review-logs",
        json={
            "user_id": 1,
            "word_id": 42,
            "correct": True,
            "response_time_ms": 900,
            "source": "new",
        },
    )
    assert missing_word.status_code == 404
    assert len(client.get("/users/1/review-logs").json()) == 1
    assert client.get("/users/99/review-logs").status_code == 404
