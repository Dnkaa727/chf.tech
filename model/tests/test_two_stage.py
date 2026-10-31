"""Tests for semantic segmentation, criterion routing and evidence-ID scoring."""

import json
import os
import unittest
from io import BytesIO
from unittest.mock import patch

from rag.engine import (
    rubrics,
    segmentation_schema_for,
    segmentation_messages_for,
    validate_segments,
    scoring_schema_for,
    scoring_messages_for,
    check_segmented_output,
)
from rag.llm import evaluate_live
from rag.diagnostics import EvaluationValidationError


ANSWER = (
    "Если я вызову time.sleep(2) внутри async def, я заблокирую event loop. "
    "time.sleep — синхронная блокирующая функция и останавливает поток. "
    "Для ожидания нужно использовать await asyncio.sleep(2), который передаёт управление event loop. "
    "Обычный requests тоже блокирует цикл. Можно использовать aiohttp или перенести вызов в поток "
    "через asyncio.to_thread. Для CPU-bound вычислений await не поможет: они продолжат блокировать "
    "поток, поэтому их стоит вынести в отдельные процессы или воркеры. "
    "Проверить задержки можно двумя корутинами с логами."
)


def raw_segmentation():
    return {
        "segments": [
            {
                "quote": "time.sleep — синхронная блокирующая функция и останавливает поток.",
                "claim_type": "mechanism",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K1",
                        "reason": "Объясняет механизм блокировки.",
                    }
                ],
            },
            {
                "quote": "Для ожидания нужно использовать await asyncio.sleep(2)",
                "claim_type": "solution",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K2",
                        "reason": "Предлагает неблокирующее ожидание.",
                    }
                ],
            },
            {
                "quote": "который передаёт управление event loop.",
                "claim_type": "mechanism",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K2",
                        "reason": "Объясняет передачу управления.",
                    }
                ],
            },
            {
                "quote": "Обычный requests тоже блокирует цикл.",
                "claim_type": "cause",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K3",
                        "reason": "Распознаёт блокирующий синхронный I/O.",
                    }
                ],
            },
            {
                "quote": "Можно использовать aiohttp",
                "claim_type": "solution",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K3",
                        "reason": "Предлагает асинхронный HTTP-клиент.",
                    }
                ],
            },
            {
                "quote": "перенести вызов в поток через asyncio.to_thread.",
                "claim_type": "solution",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K3",
                        "reason": "Предлагает thread offloading.",
                    }
                ],
            },
            {
                "quote": "Для CPU-bound вычислений await не поможет: они продолжат блокировать поток,",
                "claim_type": "limitation",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K4",
                        "reason": "Различает CPU-bound и async I/O.",
                    }
                ],
            },
            {
                "quote": "их стоит вынести в отдельные процессы или воркеры.",
                "claim_type": "solution",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K4",
                        "reason": "Предлагает процессы или воркеры.",
                    }
                ],
            },
            {
                "quote": "Проверить задержки можно двумя корутинами с логами.",
                "claim_type": "test",
                "criterion_links": [
                    {
                        "criterion_id": "PY-ASYNC-01-K5",
                        "reason": "Предлагает проверку конкурентных задач.",
                    }
                ],
            },
        ]
    }


def scoring_output(segments):
    rubric = rubrics()["PY-ASYNC-01"]
    criteria = {}
    for criterion in rubric["criteria"]:
        cid = criterion["id"]
        ids = [
            s["segment_id"]
            for s in segments
            if any(link["criterion_id"] == cid for link in s["criterion_links"])
        ]
        criteria[cid] = {
            "points": 2 if ids else 0,
            "segment_assessments": (
                {sid: "supports" for sid in ids}
                if ids
                else {"__no_evidence__": "not_applicable"}
            ),
            "reason": "Все связанные фрагменты учтены."
            if ids
            else "Нет релевантных доказательств.",
        }
    return {
        "reviewed_segment_ids": {s["segment_id"]: True for s in segments},
        "criteria": criteria,
        "red_flag_checks": {
            flag["id"]: {
                "detected": False,
                "evidence_ids": [],
                "reason": "Нет подтверждения этого флага.",
            }
            for flag in rubric["red_flag_definitions"]
        },
        "uncertainty": "low",
        "abstained": False,
        "summary": "Проверочная оценка.",
        "error_updates": [],
        "resolutions": [],
    }


class ProviderResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def provider_json(value):
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(value, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ]
    }
    return ProviderResponse(json.dumps(body, ensure_ascii=False).encode("utf-8"))


class TwoStageEngineTests(unittest.TestCase):
    def setUp(self):
        self.rubric = rubrics()["PY-ASYNC-01"]
        self.segments = validate_segments("PY-ASYNC-01", ANSWER, raw_segmentation())

    def test_segmentation_prompt_contains_criteria_and_does_not_score(self):
        schema = segmentation_schema_for("PY-ASYNC-01")
        messages = segmentation_messages_for("PY-ASYNC-01", ANSWER)
        self.assertEqual(schema["properties"]["segments"]["type"], "array")
        self.assertIn("PY-ASYNC-01-K3", messages[1]["content"])
        self.assertIn("Не выставляй баллы", messages[0]["content"])
        self.assertIn(ANSWER, messages[2]["content"])

    def test_segment_quotes_are_recovered_exactly_from_source(self):
        raw = raw_segmentation()
        raw["segments"][0]["quote"] = (
            "time.sleep — СИНХРОННАЯ блокирующая функция и останавливает поток"
        )
        segments = validate_segments("PY-ASYNC-01", ANSWER, raw)
        self.assertEqual(
            segments[0]["quote"],
            "time.sleep — синхронная блокирующая функция и останавливает поток",
        )
        self.assertEqual(
            ANSWER[segments[0]["start"] : segments[0]["end"]], segments[0]["quote"]
        )

    def test_unalignable_or_unknown_criterion_segment_fails_closed(self):
        raw = raw_segmentation()
        raw["segments"][0]["quote"] = "Модель придумала несуществующую цитату."
        unverified = validate_segments("PY-ASYNC-01", ANSWER, raw)
        self.assertEqual(unverified[0]["source_alignment"], "unverified")
        self.assertIsNone(unverified[0]["start"])
        raw = raw_segmentation()
        raw["segments"][0]["criterion_links"][0]["criterion_id"] = "OTHER-CARD-K1"
        with self.assertRaises(EvaluationValidationError):
            validate_segments("PY-ASYNC-01", ANSWER, raw)

    def test_scoring_prompt_receives_python_assigned_ids_and_full_segments(self):
        schema = scoring_schema_for("PY-ASYNC-01", self.segments)
        messages = scoring_messages_for(
            "PY-ASYNC-01", ANSWER, self.segments, output_schema=schema
        )
        self.assertIn("S001", messages[1]["content"])
        self.assertIn("segment_assessments", messages[1]["content"])
        self.assertIn("ВСЕ смысловые фрагменты", messages[0]["content"])
        self.assertIn(ANSWER, messages[2]["content"])

    def test_python_rejects_unreviewed_or_unclassified_routed_segments(self):
        output = scoring_output(self.segments)
        output["reviewed_segment_ids"].pop(next(iter(output["reviewed_segment_ids"])))
        with self.assertRaises(EvaluationValidationError):
            check_segmented_output("PY-ASYNC-01", ANSWER, self.segments, output)
        output = scoring_output(self.segments)
        output["criteria"]["PY-ASYNC-01-K3"]["segment_assessments"].pop("S005")
        with self.assertRaises(EvaluationValidationError):
            check_segmented_output("PY-ASYNC-01", ANSWER, self.segments, output)

    def test_scoring_reconstructs_multiple_exact_evidence_quotes_for_one_criterion(
        self,
    ):
        output = scoring_output(self.segments)
        result = check_segmented_output("PY-ASYNC-01", ANSWER, self.segments, output)
        self.assertEqual(result["score"], 10)
        k3 = result["criteria"]["PY-ASYNC-01-K3"]
        self.assertEqual(len(k3["evidence"]), 3)
        self.assertTrue(all(quote["quote"] in ANSWER for quote in k3["evidence"]))
        self.assertIn("aiohttp", " ".join(x["quote"] for x in k3["evidence"]))

    def test_contradictory_segment_is_retained_and_requires_review_without_flag(self):
        answer = "await time.sleep(2) делает ожидание неблокирующим."
        raw = {
            "segments": [
                {
                    "quote": answer,
                    "claim_type": "solution",
                    "criterion_links": [
                        {
                            "criterion_id": "PY-ASYNC-01-K2",
                            "reason": "Предложено решение.",
                        }
                    ],
                }
            ]
        }
        segments = validate_segments("PY-ASYNC-01", answer, raw)
        output = scoring_output(segments)
        row = output["criteria"]["PY-ASYNC-01-K2"]
        row["points"] = 0
        row["segment_assessments"] = {"S001": "contradicts"}
        result = check_segmented_output("PY-ASYNC-01", answer, segments, output)
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(
            result["criteria"]["PY-ASYNC-01-K2"]["evidence"][0]["relation"],
            "contradicts",
        )

    def test_significant_contradiction_keeps_evidence_for_session_error_protocol(self):
        answer = "await time.sleep(2) makes the wait non-blocking."
        raw = {
            "segments": [
                {
                    "quote": answer,
                    "claim_type": "solution",
                    "criterion_links": [
                        {
                            "criterion_id": "PY-ASYNC-01-K2",
                            "reason": "Предложено решение.",
                        }
                    ],
                }
            ]
        }
        segments = validate_segments("PY-ASYNC-01", answer, raw)
        output = scoring_output(segments)
        row = output["criteria"]["PY-ASYNC-01-K2"]
        row["points"] = 0
        row["segment_assessments"] = {"S001": "contradicts"}
        output["red_flag_checks"]["confidently_incorrect"] = {
            "detected": True,
            "evidence_ids": ["S001"],
            "reason": "The proposed await expression is technically invalid.",
        }
        output["error_updates"] = [
            {
                "flag_id": "confidently_incorrect",
                "error_id": None,
                "criterion_id": "PY-ASYNC-01-K2",
                "reason": "The incorrect fix directly affects the non-blocking wait criterion.",
            }
        ]
        result = check_segmented_output("PY-ASYNC-01", answer, segments, output)
        self.assertFalse(result["needs_review"])
        self.assertEqual(result["_error_updates"][0]["criterion_id"], "PY-ASYNC-01-K2")
        self.assertEqual(result["red_flags"][0]["quote"], answer)

    def test_resolution_uses_segment_id_then_python_restores_legacy_quote_contract(
        self,
    ):
        output = scoring_output(self.segments)
        error_context = {
            "errors": [
                {
                    "error_id": "error-existing",
                    "criterion_id": "PY-ASYNC-01-K3",
                    "status": "open",
                }
            ]
        }
        output["resolutions"] = [
            {
                "error_id": "error-existing",
                "criterion_id": "PY-ASYNC-01-K3",
                "evidence_id": "S005",
                "reason": "Кандидат дал корректное объяснение и решение.",
            }
        ]
        result = check_segmented_output(
            "PY-ASYNC-01", ANSWER, self.segments, output, error_context=error_context
        )
        self.assertEqual(result["_resolutions"][0]["quote"], self.segments[4]["quote"])
        self.assertNotIn("evidence_id", result["_resolutions"][0])

    def test_live_adapter_makes_two_calls_and_returns_evidence_ids_as_exact_quotes(
        self,
    ):
        raw1 = raw_segmentation()
        raw1["segments"][0]["quote"] = raw1["segments"][0]["quote"].lower()
        segments = validate_segments("PY-ASYNC-01", ANSWER, raw1)
        output = scoring_output(segments)
        with (
            patch.dict(
                os.environ,
                {
                    "LLM_API_KEY": "FAKE_TEST_TOKEN",
                    "LLM_MODEL": "gpt-4o-mini",
                    "LLM_BASE_URL": "http://localhost:5005/v1",
                    "LLM_JSON_MODE": "schema",
                    "LLM_MESSAGE_MODE": "system_user",
                    "LLM_PIPELINE_MODE": "two_stage",
                },
                clear=False,
            ),
            patch(
                "urllib.request.urlopen",
                side_effect=[provider_json(raw1), provider_json(output)],
            ) as transport,
        ):
            result = evaluate_live("PY-ASYNC-01", ANSWER)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(result["score"], 10)
        self.assertEqual(len(result["criteria"]["PY-ASYNC-01-K3"]["evidence"]), 3)
        first_payload = json.loads(transport.call_args_list[0].args[0].data)
        second_payload = json.loads(transport.call_args_list[1].args[0].data)
        self.assertEqual(
            first_payload["response_format"]["json_schema"]["name"],
            "backend_semantic_segments_v1",
        )
        self.assertEqual(
            second_payload["response_format"]["json_schema"]["name"],
            "backend_rubric_score_v2",
        )
        self.assertEqual(
            [m["role"] for m in second_payload["messages"]], ["system", "user"]
        )
        self.assertIn("S009", second_payload["messages"][0]["content"])

    def test_first_stage_refusal_stops_before_scoring(self):
        refusal = ProviderResponse(
            b'{"choices":[{"message":{"role":"assistant","refusal":"cannot assess"}}]}'
        )
        with (
            patch.dict(
                os.environ,
                {
                    "LLM_API_KEY": "FAKE_TEST_TOKEN",
                    "LLM_BASE_URL": "http://localhost:5005/v1",
                    "LLM_PIPELINE_MODE": "two_stage",
                },
                clear=False,
            ),
            patch("urllib.request.urlopen", return_value=refusal) as transport,
        ):
            result = evaluate_live("PY-ASYNC-01", ANSWER)
        self.assertTrue(result["refusal"])
        self.assertEqual(transport.call_count, 1)


if __name__ == "__main__":
    unittest.main()
