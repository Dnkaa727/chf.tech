"""Regression tests for the Stage-2 red-flag checklist.

Run from the project root with:
    python -m pytest tests/test_v3_red_flag_checklist.py -q
"""
from io import BytesIO
import json
from unittest.mock import patch

import pytest

from v3.engine import (
    check_segmented_output,
    validate_segments,
    rubrics,
    scoring_messages_for,
    scoring_schema_for,
)
from v3.diagnostics import EvaluationValidationError
from v3.llm import evaluate_live


CARD_ID = "PY-ASYNC-01"


def _segments(rows):
    """Build validated-shaped segments; Python-assigned IDs are explicit."""
    return [
        {
            "segment_id": f"S{i:03d}",
            "quote": quote,
            "claim_type": claim_type,
            "criterion_links": [
                {"criterion_id": cid, "reason": "Фрагмент тематически относится к критерию."}
                for cid in criteria
            ],
            "start": 0,
            "end": len(quote),
        }
        for i, (quote, claim_type, criteria) in enumerate(rows, 1)
    ]


def _output(segments, *, relations=None, detected_flags=None):
    rubric = rubrics()[CARD_ID]
    criterion_rows = {}
    for criterion in rubric["criteria"]:
        cid = criterion["id"]
        linked_ids = [
            segment["segment_id"]
            for segment in segments
            if any(link["criterion_id"] == cid for link in segment["criterion_links"])
        ]
        criterion_rows[cid] = {
            "points": 0,
            "segment_assessments": ({
                sid: (relations or {}).get((cid, sid), "neutral") for sid in linked_ids
            } if linked_ids else {"__no_evidence__": "not_applicable"}),
            "reason": "Оценка основана на всех связанных фрагментах.",
        }

    checks = {
        flag["id"]: {
            "detected": False,
            "evidence_ids": [],
            "reason": "В ответе нет достаточного подтверждения этого флага.",
        }
        for flag in rubric["red_flag_definitions"]
    }
    for flag_id, evidence_ids in (detected_flags or {}).items():
        checks[flag_id] = {
            "detected": True,
            "evidence_ids": list(evidence_ids),
            "reason": "Конкретное утверждение из ответа соответствует определению флага.",
        }

    return {
        "reviewed_segment_ids": {segment["segment_id"]: True for segment in segments},
        "criteria": criterion_rows,
        "red_flag_checks": checks,
        "uncertainty": "medium",
        "abstained": False,
        "summary": "Тестовая оценка.",
        "error_updates": [],
        "resolutions": [],
    }


class _ProviderResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _provider_json(value):
    body = {
        "choices": [{
            "message": {"role": "assistant", "content": json.dumps(value, ensure_ascii=False)},
            "finish_reason": "stop",
        }]
    }
    return _ProviderResponse(json.dumps(body, ensure_ascii=False).encode("utf-8"))


def test_stage_two_schema_requires_exactly_one_check_for_each_rubric_flag():
    schema = scoring_schema_for(CARD_ID, [])
    properties = schema["properties"]
    flag_ids = [flag["id"] for flag in rubrics()[CARD_ID]["red_flag_definitions"]]

    assert "red_flag_checks" in schema["required"]
    assert "red_flags" not in properties
    assert properties["red_flag_checks"]["required"] == flag_ids
    assert set(properties["red_flag_checks"]["properties"]) == set(flag_ids)


def test_stage_two_prompt_explains_complete_flag_review_and_stable_ids():
    segments = _segments([("time.sleep блокирует поток.", "effect", ["PY-ASYNC-01-K1"])])
    messages = scoring_messages_for(CARD_ID, "time.sleep блокирует поток.", segments)
    full_prompt = "\n".join(message["content"] for message in messages)

    assert "каждое" in full_prompt.lower()
    assert "red_flag_checks" in full_prompt
    assert "flag_id" in full_prompt
    assert "technical_contradiction" in full_prompt


def test_contradictory_claims_are_built_into_final_red_flags_by_python():
    segments = _segments([
        ("time.sleep(2) блокирует поток event loop.", "effect", ["PY-ASYNC-01-K1"]),
        ("Другие корутины не смогут выполняться.", "effect", ["PY-ASYNC-01-K1"]),
        ("Во время time.sleep event loop продолжит переключать корутины.", "cause", ["PY-ASYNC-01-K1"]),
        ("asyncio.sleep(2) позволяет другим задачам выполняться.", "solution", ["PY-ASYNC-01-K2"]),
    ])
    output = _output(
        segments,
        relations={
            ("PY-ASYNC-01-K1", "S001"): "supports",
            ("PY-ASYNC-01-K1", "S002"): "supports",
            ("PY-ASYNC-01-K1", "S003"): "contradicts",
            ("PY-ASYNC-01-K2", "S004"): "supports",
        },
        detected_flags={"technical_contradiction": ["S001", "S003"]},
    )

    result = check_segmented_output(CARD_ID, " ".join(s["quote"] for s in segments), segments, output)

    assert [flag["id"] for flag in result["red_flags"]] == ["technical_contradiction"]
    assert result["red_flags"][0]["quote"] == segments[0]["quote"]
    assert result["red_flags"][0]["reason"]
    assert result["needs_review"] is False  # significant flags use the existing session protocol


def test_unsupported_absolute_inference_maps_to_existing_confidently_incorrect_flag():
    # The rubric has no separate `unsupported_claims` flag. This answer makes a
    # confident, technically false inference, so the existing flag applies.
    segments = _segments([
        ("event loop никогда не блокируется.", "mechanism", ["PY-ASYNC-01-K1"]),
        ("все запросы к серверу всегда выполняются параллельно.", "effect", ["PY-ASYNC-01-K3"]),
        ("программа запустилась и завершилась без ошибок.", "test", ["PY-ASYNC-01-K5"]),
        ("успешный запуск доказывает, что блокировок нет.", "cause", ["PY-ASYNC-01-K5"]),
    ])
    output = _output(
        segments,
        relations={
            ("PY-ASYNC-01-K1", "S001"): "contradicts",
            ("PY-ASYNC-01-K3", "S002"): "contradicts",
            ("PY-ASYNC-01-K5", "S004"): "contradicts",
        },
        detected_flags={"confidently_incorrect": ["S001", "S002", "S004"]},
    )

    result = check_segmented_output(CARD_ID, " ".join(s["quote"] for s in segments), segments, output)

    assert [flag["id"] for flag in result["red_flags"]] == ["confidently_incorrect"]
    assert result["red_flags"][0]["quote"] == segments[0]["quote"]
    assert result["_error_updates"][0]["flag_index"] == 0


def test_detected_flag_without_evidence_fails_closed():
    segments = _segments([("time.sleep блокирует поток.", "effect", ["PY-ASYNC-01-K1"])])
    output = _output(segments)
    output["red_flag_checks"]["technical_contradiction"] = {
        "detected": True,
        "evidence_ids": [],
        "reason": "Есть противоречие, но цитата не указана.",
    }

    with pytest.raises(EvaluationValidationError):
        check_segmented_output(CARD_ID, segments[0]["quote"], segments, output)


def test_false_flag_cannot_carry_evidence_ids():
    segments = _segments([("time.sleep блокирует поток.", "effect", ["PY-ASYNC-01-K1"])])
    output = _output(segments)
    output["red_flag_checks"]["technical_contradiction"]["evidence_ids"] = ["S001"]

    with pytest.raises(EvaluationValidationError):
        check_segmented_output(CARD_ID, segments[0]["quote"], segments, output)


def test_missing_flag_check_fails_schema_validation():
    segments = _segments([("time.sleep блокирует поток.", "effect", ["PY-ASYNC-01-K1"])])
    output = _output(segments)
    del output["red_flag_checks"]["technical_contradiction"]

    with pytest.raises(EvaluationValidationError):
        check_segmented_output(CARD_ID, segments[0]["quote"], segments, output)


def test_error_update_uses_flag_id_not_model_generated_array_index():
    segments = _segments([("time.sleep(2) якобы не блокирует event loop.", "solution", ["PY-ASYNC-01-K1"])])
    output = _output(
        segments,
        relations={("PY-ASYNC-01-K1", "S001"): "contradicts"},
        detected_flags={"confidently_incorrect": ["S001"]},
    )
    output["error_updates"] = [{
        "flag_id": "confidently_incorrect",
        "error_id": None,
        "criterion_id": "PY-ASYNC-01-K1",
        "reason": "Ложное утверждение относится к блокировке event loop.",
    }]

    result = check_segmented_output(CARD_ID, segments[0]["quote"], segments, output)

    assert result["_error_updates"][0]["flag_index"] == 0
    assert result["_error_updates"][0]["criterion_id"] == "PY-ASYNC-01-K1"


def test_error_update_cannot_reference_a_flag_marked_not_detected():
    segments = _segments([("time.sleep блокирует поток.", "effect", ["PY-ASYNC-01-K1"])])
    output = _output(segments)
    output["error_updates"] = [{
        "flag_id": "technical_contradiction",
        "error_id": None,
        "criterion_id": "PY-ASYNC-01-K1",
        "reason": "Не должно быть применено без сработавшего флага.",
    }]

    with pytest.raises(EvaluationValidationError):
        check_segmented_output(CARD_ID, segments[0]["quote"], segments, output)


def test_live_two_stage_adapter_sends_checklist_schema_and_reconstructs_flags():
    answer = "time.sleep(2) блокирует поток event loop. Во время time.sleep event loop продолжит переключать корутины."
    raw_segmentation = {
        "segments": [
            {
                "quote": "time.sleep(2) блокирует поток event loop.",
                "claim_type": "effect",
                "criterion_links": [{"criterion_id": "PY-ASYNC-01-K1", "reason": "Утверждение о блокировке."}],
            },
            {
                "quote": "Во время time.sleep event loop продолжит переключать корутины.",
                "claim_type": "cause",
                "criterion_links": [{"criterion_id": "PY-ASYNC-01-K1", "reason": "Утверждение о поведении цикла."}],
            },
        ]
    }
    segments = validate_segments(CARD_ID, answer, raw_segmentation)
    raw_scoring = _output(
        segments,
        relations={
            ("PY-ASYNC-01-K1", "S001"): "supports",
            ("PY-ASYNC-01-K1", "S002"): "contradicts",
        },
        detected_flags={"technical_contradiction": ["S001", "S002"]},
    )

    with patch.dict("os.environ", {
        "LLM_API_KEY": "FAKE_TEST_TOKEN",
        "LLM_MODEL": "gpt-4o-mini",
        "LLM_BASE_URL": "http://localhost:5005/v1",
        "LLM_JSON_MODE": "schema",
        "LLM_MESSAGE_MODE": "system_user",
        "LLM_PIPELINE_MODE": "two_stage",
    }, clear=False), patch(
        "urllib.request.urlopen",
        side_effect=[_provider_json(raw_segmentation), _provider_json(raw_scoring)],
    ) as transport:
        result = evaluate_live(CARD_ID, answer)

    assert transport.call_count == 2
    assert [flag["id"] for flag in result["red_flags"]] == ["technical_contradiction"]
    second_request = json.loads(transport.call_args_list[1].args[0].data)
    second_schema = second_request["response_format"]["json_schema"]["schema"]
    assert "red_flag_checks" in second_schema["required"]
    assert "red_flags" not in second_schema["properties"]
