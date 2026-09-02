"""CRUD coverage for the thin FastAPI layer (build-order step 1)."""

WORD = {
    "lemma": "Haus",
    "article": "das",
    "plural": "Häuser",
    "translation_en": "house",
    "cefr_level": "A1",
    "frequency_rank": 51,
    "ipa_or_audio_ref": "haʊ̯s",
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_word_create_get_list_and_dup(client):
    created = client.post("/words", json=WORD)
    assert created.status_code == 201
    wid = created.json()["id"]

    assert client.get(f"/words/{wid}").json()["lemma"] == "Haus"
    assert client.get("/words/9999").status_code == 404
    assert client.post("/words", json=WORD).status_code == 409  # unique lemma

    a2 = {**WORD, "lemma": "Buch", "cefr_level": "A2", "frequency_rank": 700}
    client.post("/words", json=a2)
    assert len(client.get("/words", params={"cefr_level": "A1"}).json()) == 1
    assert len(client.get("/words").json()) == 2


def test_word_validation_rejects_bad_rank(client):
    assert client.post("/words", json={**WORD, "frequency_rank": 0}).status_code == 422


def test_user_and_review_log_flow(client):
    assert client.post("/users", json={"target": "work"}).status_code == 201
    assert client.get("/users/1").json()["target"] == "work"
    assert client.get("/users/2").status_code == 404

    client.post("/words", json=WORD)
    log = client.post(
        "/review-logs",
        json={
            "user_id": 1,
            "word_id": 1,
            "correct": True,
            "response_time_ms": 900,
            "source": "new",
        },
    )
    assert log.status_code == 201

    assert (
        client.post(
            "/review-logs",
            json={
                "user_id": 1,
                "word_id": 42,
                "correct": True,
                "response_time_ms": 900,
                "source": "new",
            },
        ).status_code
        == 404
    )
    assert len(client.get("/users/1/review-logs").json()) == 1
