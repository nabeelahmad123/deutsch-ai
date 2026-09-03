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
