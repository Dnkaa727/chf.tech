import unittest
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.api import app
from rag.engine import rubrics, cases, gold_fixture

client = TestClient(app)


class V3ApiTests(unittest.TestCase):
    def test_health_uses_current_catalog_and_provider_key_fallback(self):
        for values, expected in [
            ({}, False),
            ({"LLM_API_KEY": "FAKE_TEST_KEY"}, True),
            ({"OPENAI_API_KEY": "FAKE_TEST_KEY"}, True),
            ({"LLM_API_KEY": "FAKE_TEST_KEY", "LLM_MODEL": ""}, False),
        ]:
            with (
                self.subTest(values=values),
                patch.dict(os.environ, values, clear=True),
            ):
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {
                        "status": "ok",
                        "cards": len(rubrics()),
                        "llm_configured": expected,
                    },
                )

    def test_info(self):
        r = client.get("/api/info")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rubrics"], 25)
        self.assertEqual(r.json()["cases"], 150)

    def test_prepare_all_25(self):
        for cid in rubrics():
            with self.subTest(cid=cid):
                r = client.post(
                    "/api/prepare",
                    json={
                        "card_id": cid,
                        "candidate_answer": "Тестовый ответ кандидата",
                    },
                )
                self.assertEqual(r.status_code, 200)
                self.assertEqual(
                    [x["role"] for x in r.json()["messages"]],
                    ["system", "developer", "user"],
                )

    def test_session_start_all_25(self):
        for cid in rubrics():
            with self.subTest(cid=cid):
                r = client.post("/api/session/start", json={"card_id": cid})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["card_id"], cid)
                self.assertTrue(r.json()["question"])

    def test_session_followup_fake_llm(self):
        case = next(
            x
            for x in cases()
            if x["card_id"] == "PY-ASYNC-01" and x["kind"] == "partial"
        )
        start = client.post(
            "/api/session/start", json={"card_id": case["card_id"]}
        ).json()
        with patch("app.routes.evaluate_live", return_value=gold_fixture(case)):
            r = client.post(
                "/api/session/answer",
                json={
                    "session_id": start["session_id"],
                    "candidate_answer": case["answer"],
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "followup")
        self.assertTrue(r.json()["next_question"])

    def test_evaluate_one_llm_mock(self):
        case = next(
            x
            for x in cases()
            if x["card_id"] == "MQ-ACK-01" and x["kind"] == "excellent"
        )
        with patch("app.routes.evaluate_live", return_value=gold_fixture(case)):
            r = client.post(
                "/api/evaluate",
                json={"card_id": case["card_id"], "candidate_answer": case["answer"]},
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["score"], 10)

    def test_bad_card(self):
        r = client.post("/api/session/start", json={"card_id": "MISSING-CARD"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
