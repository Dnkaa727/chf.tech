"""Catalog/rubric contracts, registry validation and immutable session versions."""

import copy
import hashlib
import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.api import app
from rag.engine import TopicSession, messages_for, rubrics
from rag.registry import get_registry

ROOT = Path(__file__).resolve().parents[1]


class ExistingCatalogContracts(unittest.TestCase):
    def test_all_125_rubric_criteria_and_file_content_stay_unchanged(self):
        content = (ROOT / "data/rubrics_all_25.json").read_bytes()
        self.assertEqual(
            hashlib.sha256(content).hexdigest(),
            "0698c2471a0bc74bda33c16123584a66097c211a90fc0e4bd1bdad433af13c03",
        )
        self.assertEqual(sum(len(r["criteria"]) for r in rubrics().values()), 125)

    def test_catalog_and_rubrics_have_one_current_source(self):
        registry = get_registry()
        cards = registry.cards()
        self.assertEqual(len(cards), 25)
        self.assertEqual(set(cards), set(registry.rubrics()))
        self.assertTrue(
            all(
                "criteria" not in c and "followup_questions" not in c
                for c in cards.values()
            )
        )
        self.assertEqual(
            sum(len(r["criteria"]) for r in registry.rubrics().values()), 125
        )

    def test_search_selects_current_catalog_and_omits_hidden_rubrics(self):
        from rag.registry import CardNotFound, public_card

        registry = get_registry()
        entry = registry.select(query="индексы PostgreSQL")
        self.assertEqual(entry.card["id"], "PG-QUERY-01")
        self.assertEqual(
            registry.select(query="сессии и транзакции", competency="SQLAlchemy").card[
                "id"
            ],
            "ORM-SESSION-01",
        )
        with self.assertRaises(CardNotFound):
            registry.select(query="садовая лопата")
        result = public_card(entry.card)
        self.assertFalse({"criteria", "anchors", "followup_questions"} & set(result))
        self.assertTrue(result["source_urls"])

    def test_search_accepts_aliases_without_matching_inside_other_competencies(self):
        from rag.registry import AmbiguousCardSelection

        for query, competency in (
            ("pgsql", "PostgreSQL"),
            ("SQLAlchemy", "SQLAlchemy"),
        ):
            with self.subTest(query=query):
                with self.assertRaises(AmbiguousCardSelection) as result:
                    get_registry().select(query=query)
                self.assertGreater(len(result.exception.candidates), 1)
                self.assertTrue(
                    all(
                        c["competency"] == competency
                        for c in result.exception.candidates
                    )
                )

    def test_session_start_contract_and_question(self):
        from app.routes import SESSIONS

        response = TestClient(app).post(
            "/api/session/start", json={"card_id": "PY-ASYNC-01"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.addCleanup(SESSIONS.pop, body["session_id"], None)
        self.assertEqual(
            set(body), {"session_id", "card_id", "question", "status", "max_followups"}
        )
        self.assertEqual(body["question"], rubrics()["PY-ASYNC-01"]["question"])

    def test_prompt_uses_only_current_criteria(self):
        content = messages_for("PY-ASYNC-01", "Ответ кандидата")[1]["content"]
        self.assertIn("PY-ASYNC-01-K1", content)
        self.assertNotIn("PY-ASYNC-01-C1", content)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.kb = json.loads(
            (ROOT / "data/knowledge_base.json").read_text(encoding="utf-8")
        )
        self.kb["schema_version"] = "2.0"
        for card in self.kb["cards"]:
            card.pop("criteria", None)
            card.pop("followup_questions", None)
        self.rs = json.loads(
            (ROOT / "data/rubrics_all_25.json").read_text(encoding="utf-8")
        )

    def registry(self, kb=None, rs=None):
        from rag.registry import CardRegistry

        return CardRegistry(kb or self.kb, rs or self.rs)

    def test_one_to_one_mapping_and_copy_isolation(self):
        registry = self.registry()
        self.assertEqual(len(registry.cards()), 25)
        self.assertEqual(set(registry.cards()), set(registry.rubrics()))
        entry = registry.get("PY-ASYNC-01")
        self.assertEqual(entry.card["id"], entry.rubric["card_id"])
        self.assertNotIn("criteria", entry.card)
        entry.rubric["criteria"].clear()
        self.assertEqual(len(registry.get("PY-ASYNC-01").rubric["criteria"]), 5)
        self.kb["cards"].clear()
        self.assertEqual(len(registry.cards()), 25)

    def test_duplicate_card_and_rubric_ids_are_rejected_before_indexing(self):
        for source in ("cards", "rubrics"):
            for append in (False, True):
                with self.subTest(source=source, append=append):
                    kb, rs = copy.deepcopy(self.kb), copy.deepcopy(self.rs)
                    rows = kb["cards"] if source == "cards" else rs["rubrics"]
                    if append:
                        rows.append(copy.deepcopy(rows[0]))
                    else:
                        rows[1] = copy.deepcopy(rows[0])
                    with self.assertRaisesRegex(ValueError, "Duplicate"):
                        self.registry(kb, rs)

    def test_missing_or_extra_rubric_is_rejected(self):
        for edit in ("missing", "orphan"):
            with self.subTest(edit=edit):
                rs = copy.deepcopy(self.rs)
                if edit == "missing":
                    rs["rubrics"].pop()
                else:
                    rs["rubrics"][0]["card_id"] = "ORPHAN-CARD"
                with self.assertRaises(ValueError):
                    self.registry(rs=rs)

    def test_all_shared_metadata_fields_must_match(self):
        for field in (
            "competency",
            "topic",
            "question",
            "target_level",
            "source_card_id",
        ):
            with self.subTest(field=field):
                rs = copy.deepcopy(self.rs)
                rs["rubrics"][0][field] = "Different value"
                with self.assertRaises(ValueError):
                    self.registry(rs=rs)

    def test_invalid_criteria_versions_and_followups_are_rejected(self):
        for edit in ("duplicate", "points", "anchors", "followup", "version"):
            with self.subTest(edit=edit):
                rs = copy.deepcopy(self.rs)
                r = rs["rubrics"][0]
                if edit == "duplicate":
                    r["criteria"][1]["id"] = r["criteria"][0]["id"]
                elif edit == "points":
                    r["criteria"][0]["max_points"] = True
                elif edit == "anchors":
                    del r["criteria"][0]["anchors"]["1"]
                elif edit == "followup":
                    r["criteria"][0]["followup_question"] = " "
                else:
                    r["version"] = ""
                with self.assertRaises(ValueError):
                    self.registry(rs=rs)

    def test_current_catalog_cannot_contain_scoring_or_followups(self):
        for field in ("criteria", "followup_questions", "red_flag_definitions"):
            with self.subTest(field=field):
                kb = copy.deepcopy(self.kb)
                kb["cards"][0][field] = []
                with self.assertRaises(ValueError):
                    self.registry(kb=kb)

    def test_registry_loads_each_json_once_and_caches_the_snapshot(self):
        import rag.registry as module

        with TemporaryDirectory() as directory:
            kb_path, rs_path = (
                Path(directory) / "kb.json",
                Path(directory) / "rubrics.json",
            )
            kb_path.write_text(json.dumps(self.kb), encoding="utf-8")
            rs_path.write_text(json.dumps(self.rs), encoding="utf-8")
            with (
                patch.object(module, "KB_PATH", kb_path),
                patch.object(module, "RUBRICS_PATH", rs_path),
            ):
                module.get_registry.cache_clear()
                try:
                    with patch.object(
                        module, "strict_json_loads", wraps=module.strict_json_loads
                    ) as reader:
                        first = module.get_registry()
                        self.assertIs(module.get_registry(), first)
                        self.assertEqual(reader.call_count, 2)
                    with patch.object(
                        Path,
                        "read_text",
                        side_effect=AssertionError("Unexpected disk read"),
                    ):
                        first.get("PG-QUERY-01")
                        messages_for("PG-QUERY-01", "Answer")
                finally:
                    module.get_registry.cache_clear()

    def test_session_version_survives_file_change_and_registry_reload(self):
        import rag.registry as module
        from rag.llm import evaluate_live

        cid = "PY-ASYNC-01"
        original = self.registry()
        session = TopicSession(cid, registry=original)
        old = copy.deepcopy(session.rubric)
        self.rs["rubrics"][1]["version"] = "changed-test-version"
        self.rs["rubrics"][1]["criteria"][0]["id"] = cid + "-NEW-K1"
        self.rs["rubrics"][1]["criteria"][0]["anchors"]["2"] = "Changed test anchor"
        with TemporaryDirectory() as directory:
            kb_path, rs_path = (
                Path(directory) / "kb.json",
                Path(directory) / "rubrics.json",
            )
            kb_path.write_text(json.dumps(self.kb), encoding="utf-8")
            rs_path.write_text(json.dumps(self.rs), encoding="utf-8")
            with (
                patch.object(module, "KB_PATH", kb_path),
                patch.object(module, "RUBRICS_PATH", rs_path),
            ):
                module.get_registry.cache_clear()
                try:
                    new = TopicSession(cid)
                    self.assertNotEqual(session.rubric_hash, new.rubric_hash)
                    self.assertNotEqual(session.rubric_version, new.rubric_version)
                    self.assertEqual(session.rubric, old)
                    output = {
                        "criteria": {
                            c["id"]: {
                                "points": 0,
                                "quote": "",
                                "reason": "Not covered.",
                            }
                            for c in old["criteria"]
                        },
                        "red_flags": [],
                        "uncertainty": "low",
                        "abstained": False,
                        "summary": "Test.",
                        "error_updates": [],
                        "resolutions": [],
                    }
                    response = BytesIO(
                        json.dumps(
                            {"choices": [{"message": {"content": json.dumps(output)}}]}
                        ).encode()
                    )
                    with (
                        patch.dict(
                            os.environ,
                            {
                                "LLM_API_KEY": "FAKE_TEST_TOKEN",
                                "LLM_JSON_MODE": "schema",
                                "LLM_MESSAGE_MODE": "developer",
                                "LLM_PIPELINE_MODE": "one_stage",
                            },
                        ),
                        patch(
                            "urllib.request.urlopen", return_value=response
                        ) as transport,
                        patch.object(
                            Path,
                            "read_text",
                            side_effect=AssertionError("Unexpected disk read"),
                        ),
                    ):
                        result = evaluate_live(cid, "Answer", rubric=session.rubric)
                    self.assertEqual(result["score"], 0)
                    payload = json.loads(transport.call_args.args[0].data)
                    self.assertIn(old["version"], payload["messages"][1]["content"])
                    self.assertNotIn(
                        "Changed test anchor", payload["messages"][1]["content"]
                    )
                    ids = payload["response_format"]["json_schema"]["schema"][
                        "properties"
                    ]["criteria"]["required"]
                    self.assertEqual(ids, [c["id"] for c in old["criteria"]])
                finally:
                    module.get_registry.cache_clear()

    def test_canonical_file_has_no_legacy_scoring_fields(self):
        kb = json.loads((ROOT / "data/knowledge_base.json").read_text(encoding="utf-8"))
        self.assertEqual(kb["schema_version"], "2.0")
        self.assertTrue(
            all(
                "criteria" not in c and "followup_questions" not in c
                for c in kb["cards"]
            )
        )

    def test_application_startup_rejects_an_invalid_registry(self):
        from rag.registry import RegistryValidationError

        with patch(
            "app.api.get_registry",
            side_effect=RegistryValidationError("Invalid release"),
        ):
            with self.assertRaises(RegistryValidationError):
                with TestClient(app):
                    self.fail("Invalid data must prevent application startup")


if __name__ == "__main__":
    unittest.main()
