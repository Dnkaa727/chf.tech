"""A repeated request must not become an answer to an unasked follow-up."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app
from app.routes import SESSIONS
from rag.engine import cases, gold_fixture


def partial_case():
    return next(
        case
        for case in cases()
        if case["card_id"] == "PY-ASYNC-01" and case["kind"] == "partial"
    )


def test_concurrent_answers_to_one_question_do_not_consume_two_turns():
    case = partial_case()
    entered, release = Event(), Event()

    def evaluate(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5), "Test did not release the provider response"
        return gold_fixture(case)

    with TestClient(app) as client:
        started = client.post(
            "/api/session/start", json={"card_id": case["card_id"]}
        ).json()
        sid = started["session_id"]
        payload = {"session_id": sid, "candidate_answer": case["answer"]}
        try:
            with patch("app.routes.evaluate_live", side_effect=evaluate) as provider:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    first = pool.submit(
                        client.post, "/api/session/answer", json=payload
                    )
                    try:
                        assert entered.wait(timeout=5), (
                            "First request did not reach evaluation"
                        )
                        duplicate = client.post("/api/session/answer", json=payload)
                        assert duplicate.status_code == 409
                        assert provider.call_count == 1
                        assert SESSIONS[sid].history == []
                    finally:
                        release.set()
                    assert first.result(timeout=5).status_code == 200
            session = SESSIONS[sid]
            assert len(session.history) == 1
            assert session.history[0]["question"] == started["question"]
            assert session.followups_asked == 1
        finally:
            SESSIONS.pop(sid, None)


def test_provider_failure_releases_the_session_for_retry():
    case = partial_case()
    with TestClient(app) as client:
        sid = client.post(
            "/api/session/start", json={"card_id": case["card_id"]}
        ).json()["session_id"]
        payload = {"session_id": sid, "candidate_answer": case["answer"]}
        try:
            with patch(
                "app.routes.evaluate_live",
                side_effect=[RuntimeError("unavailable"), gold_fixture(case)],
            ):
                assert (
                    client.post("/api/session/answer", json=payload).status_code == 502
                )
                assert SESSIONS[sid].history == []
                assert (
                    client.post("/api/session/answer", json=payload).status_code == 200
                )
            assert len(SESSIONS[sid].history) == 1
        finally:
            SESSIONS.pop(sid, None)
