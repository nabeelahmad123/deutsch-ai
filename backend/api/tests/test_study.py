"""Study-flow endpoints for the minimal frontend (LG-19)."""

import base64
import json


def _seed(client):
    client.post("/users", json={"target": "work"})
    for i in range(1, 41):
        client.post(
            "/words",
            json={
                "lemma": f"wort{i}",
                "article": "das" if i % 2 else None,
                "plural": f"pluralofword{i}" if i % 2 else None,
                "translation_en": f"meaning {i}",
                "cefr_level": "A1" if i <= 20 else "A2",
                "frequency_rank": i,
                "topic": "work" if i in (2, 4) else None,
            },
        )


def _expected_answer(qid: str) -> str:
    return json.loads(base64.urlsafe_b64decode(qid.split(":", 1)[1]))["r"]


def test_full_session_flow(client):
    _seed(client)

    session = client.post("/study/sessions", json={"user_id": 1, "minutes_available": 10}).json()
    assert session["session_id"] == 1
    words = session["review_words"] + session["new_words"]
    assert words and all("lemma" in w for w in words)

    quiz = client.post(
        "/study/quiz",
        json={"word_ids": [w["id"] for w in words[:4]], "quiz_type": "en_to_de"},
    ).json()
    assert len(quiz) == 4
    assert all(q["prompt"].startswith("Translate to German") for q in quiz)

    right = client.post(
        "/study/answers",
        json={
            "user_id": 1,
            "question_id": quiz[0]["question_id"],
            "user_answer": _expected_answer(quiz[0]["question_id"]),
        },
    ).json()
    assert right["correct"] is True
    assert right["new_state"]["repetitions"] == 1

    wrong = client.post(
        "/study/answers",
        json={"user_id": 1, "question_id": quiz[1]["question_id"], "user_answer": "nope"},
    ).json()
    assert wrong["correct"] is False
    assert wrong["expected"] == quiz[1]["prompt"].split(": ", 1)[1] or wrong["expected"]

    summary = client.post("/study/sessions/1/finish", json={"words_covered": 2}).json()
    assert summary["words_covered"] == 2

    progress = client.get("/study/users/1/progress").json()
    assert progress["total_reviews"] == 2
    assert progress["words_seen"] == 2
    assert progress["overall_accuracy"] == 0.5
    assert isinstance(progress["due_words"], list)
    assert len(progress["weak_words"]) == 2
    assert [row["level"] for row in progress["by_level"]] == ["A1", "A2", "B1", "B2"]
    assert sum(row["seen"] for row in progress["by_level"]) == 2


def test_self_graded_review_flow(client):
    _seed(client)
    session = client.post("/study/sessions", json={"user_id": 1, "minutes_available": 10}).json()
    words = session["review_words"] + session["new_words"]

    r1 = client.post(
        "/study/review", json={"user_id": 1, "word_id": words[0]["id"], "correct": True}
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["correct"] is True
    assert body["new_state"]["repetitions"] == 1

    client.post("/study/review", json={"user_id": 1, "word_id": words[1]["id"], "correct": False})
    progress = client.get("/study/users/1/progress").json()
    assert progress["total_reviews"] == 2
    assert progress["overall_accuracy"] == 0.5


def test_session_can_pin_a_cefr_level(client):
    _seed(client)  # words 1-20 are A1, 21-40 are A2
    s = client.post(
        "/study/sessions",
        json={"user_id": 1, "minutes_available": 30, "cefr_level": "A2"},
    ).json()
    new_ids = [w["id"] for w in s["new_words"]]
    assert new_ids and all(w["cefr_level"] == "A2" for w in s["new_words"])
    assert min(new_ids) >= 21

    bad = client.post(
        "/study/sessions", json={"user_id": 1, "minutes_available": 10, "cefr_level": "C1"}
    )
    assert bad.status_code == 422


def test_answer_returns_and_persists_a_diagnosis(client):
    _seed(client)  # word 1 = "wort1", article "das", plural "pluralofword1"
    client.post("/study/sessions", json={"user_id": 1, "minutes_available": 10})
    q = client.post("/study/quiz", json={"word_ids": [1], "quiz_type": "en_to_de"}).json()[0]
    ref = _expected_answer(q["question_id"])  # "wort1"

    wrong = client.post(
        "/study/answers",
        json={"user_id": 1, "question_id": q["question_id"], "user_answer": "pluralofword1"},
    ).json()
    assert wrong["correct"] is False
    assert wrong["error_type"] == "wrong_plural"
    assert wrong["feedback"]

    right = client.post(
        "/study/answers",
        json={"user_id": 1, "question_id": q["question_id"], "user_answer": ref},
    ).json()
    assert right["correct"] and right["error_type"] is None and right["feedback"] == ""

    logs = client.get("/users/1/review-logs").json()
    assert any(x["error_type"] == "wrong_plural" for x in logs)
    assert all(x["error_type"] is None for x in logs if x["correct"])


def test_conversation_flow_without_llm_credentials(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:1")  # no real call
    _seed(client)

    start = client.post(
        "/study/conversation", json={"user_id": 1, "scenario": "cafe", "minutes": 10}
    )
    assert start.status_code == 201
    body = start.json()
    assert body["session_id"] and body["level"] and body["opener"]
    assert 3 <= len(body["targets"]) <= 15
    target_ids = [w["id"] for w in body["targets"]]

    turn = client.post(
        "/study/conversation/turn",
        json={
            "session_id": body["session_id"],
            "user_id": 1,
            "scenario": "cafe",
            "target_word_ids": target_ids,
            "history": [{"role": "assistant", "content": body["opener"]}],
            "user_message": "Ich möchte einen Kaffee, bitte.",
        },
    ).json()
    assert turn["available"] is False  # graceful degradation
    assert turn["reply"] and turn["used_word_ids"] == []

    fin = client.post(
        "/study/conversation/finish",
        json={
            "session_id": body["session_id"],
            "user_id": 1,
            "used_word_ids": target_ids[:2],
            "turns": 3,
        },
    ).json()
    assert fin["words_practised"] == 2 and fin["turns"] == 3

    progress = client.get("/study/users/1/progress").json()
    assert progress["total_reviews"] == 2  # the two used words got a correct review


def test_conversation_unknown_user_is_404(client):
    _seed(client)
    assert (
        client.post(
            "/study/conversation", json={"user_id": 999, "scenario": "cafe", "minutes": 10}
        ).status_code
        == 404
    )


def test_dashboard_endpoint(client):
    _seed(client)
    session = client.post("/study/sessions", json={"user_id": 1, "minutes_available": 10}).json()
    wid = (session["review_words"] + session["new_words"])[0]["id"]
    client.post("/study/review", json={"user_id": 1, "word_id": wid, "correct": True})

    d = client.get("/study/users/1/dashboard")
    assert d.status_code == 200
    body = d.json()
    assert body["total_reviews"] == 1 and body["words_known"] == 1
    assert len(body["daily_activity"]) == 30
    assert [row["level"] for row in body["by_level"]] == ["A1", "A2", "B1", "B2"]
    assert {"learning", "young", "mature"} == set(body["maturity"])

    assert client.get("/study/users/999/dashboard").status_code == 404


def test_review_unknown_word_is_404(client):
    _seed(client)
    assert (
        client.post(
            "/study/review", json={"user_id": 1, "word_id": 99999, "correct": True}
        ).status_code
        == 404
    )


def test_multiple_choice_quiz_has_options(client):
    _seed(client)
    quiz = client.post(
        "/study/quiz", json={"word_ids": [5, 6, 7], "quiz_type": "multiple_choice"}
    ).json()
    assert all(len(q["options"]) == 4 for q in quiz)
    assert all(q["prompt"].startswith("What does") for q in quiz)


def test_error_paths(client):
    _seed(client)
    assert (
        client.post("/study/sessions", json={"user_id": 99, "minutes_available": 10}).status_code
        == 404
    )
    assert (
        client.post("/study/quiz", json={"word_ids": [1], "quiz_type": "bogus"}).status_code == 422
    )
    assert (
        client.post(
            "/study/answers", json={"user_id": 1, "question_id": "garbage", "user_answer": "x"}
        ).status_code
        == 422
    )
    assert client.get("/study/users/99/progress").status_code == 404
    assert client.post("/study/sessions/999/finish", json={"words_covered": 1}).status_code == 404


def test_session_rejects_out_of_range_minutes(client):
    _seed(client)
    assert (
        client.post("/study/sessions", json={"user_id": 1, "minutes_available": 0}).status_code
        == 422
    )
    assert (
        client.post("/study/sessions", json={"user_id": 1, "minutes_available": 999}).status_code
        == 422
    )
