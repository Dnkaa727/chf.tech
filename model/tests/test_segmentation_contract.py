"""Current semantic extraction and fixed-key scoring contract."""

import json
import pytest

from rag.engine import (
    segmentation_schema_for,
    segmentation_messages_for,
    validate_segments,
    scoring_schema_for,
    check_segmented_output,
)
from rag.json_validation import validate_schema
from rag.diagnostics import EvaluationValidationError


def rubric():
    return {
        "card_id": "PG-TX-01",
        "topic": "PostgreSQL transactions",
        "question": "Concurrent debit",
        "status": "draft_needs_expert_review",
        "version": "test",
        "criteria": [
            {
                "id": f"PG-TX-01-K{i}",
                "name": f"K{i}",
                "anchors": {"0": "0", "1": "1", "2": "2"},
                "followup_question": "Why?",
            }
            for i in range(1, 6)
        ],
        "red_flag_definitions": [
            {"id": "technical_contradiction", "definition": "Contradiction"},
            {
                "id": "confidently_incorrect",
                "definition": "Confident false technical claim",
            },
            {"id": "keyword_stuffing", "definition": "Terms without explanation"},
        ],
        "evaluation_guidance": "",
    }


ANSWER = (
    "Связанные изменения лучше выполнять в одной транзакции. "
    "Два запроса могут одновременно работать с одним балансом, поэтому один из результатов "
    "может оказаться некорректным. "
    "Проверку остатка и само изменение нужно защитить от одновременного выполнения. "
    "При конкуренции транзакция может завершиться ошибкой. "
    "Проверю ситуацию, когда два списания запускаются одновременно."
)


def raw_segments(quotes, criterion_id="PG-TX-01-K1"):
    return {
        "segments": [
            {
                "quote": quote,
                "claim_type": "mechanism",
                "criterion_links": [
                    {"criterion_id": criterion_id, "reason": "transaction boundary"}
                ],
            }
            for quote in quotes
        ]
    }


def test_semantic_claims_keep_provider_order_and_exact_source_offsets():
    # Claims need not be entire sentences or be supplied in source order.
    quotes = ["два списания запускаются одновременно", "в одной транзакции"]
    result = validate_segments(
        "PG-TX-01", ANSWER, raw_segments(quotes), rubric=rubric()
    )
    assert [row["segment_id"] for row in result] == ["S001", "S002"]
    assert [row["quote"] for row in result] == quotes
    assert result[0]["start"] > result[1]["start"]
    for row in result:
        assert row["source_alignment"] == "matched"
        assert ANSWER[row["start"] : row["end"]] == row["quote"]


def test_semantic_claim_with_abbreviation_and_decimal_remains_one_fragment():
    quote = (
        "Используем т.е. атомарную операцию. Значение 2.5 секунды допустимо; проверим."
    )
    result = validate_segments(
        "PG-TX-01", quote, raw_segments([quote]), rubric=rubric()
    )
    assert len(result) == 1
    assert result[0]["quote"] == quote
    assert (result[0]["start"], result[0]["end"]) == (0, len(quote))


def test_stage1_schema_requires_quotes_and_rejects_provider_assigned_ids():
    schema = segmentation_schema_for("PG-TX-01", rubric=rubric())
    raw = raw_segments(["в одной транзакции"])
    validate_schema(raw, schema)
    raw["segments"][0]["segment_id"] = "S001"
    with pytest.raises(EvaluationValidationError):
        validate_schema(raw, schema)
    del raw["segments"][0]["segment_id"]
    del raw["segments"][0]["quote"]
    with pytest.raises(EvaluationValidationError):
        validate_schema(raw, schema)


@pytest.mark.parametrize(
    "links",
    [
        [{"criterion_id": "UNKNOWN", "reason": "not in selected rubric"}],
        [
            {"criterion_id": "PG-TX-01-K1", "reason": "first"},
            {"criterion_id": "PG-TX-01-K1", "reason": "duplicate"},
        ],
        [{"criterion_id": "PG-TX-01-K1", "reason": "  "}],
    ],
)
def test_stage1_rejects_invalid_routing_links(links):
    raw = raw_segments(["в одной транзакции"])
    raw["segments"][0]["criterion_links"] = links
    with pytest.raises(EvaluationValidationError):
        validate_segments("PG-TX-01", ANSWER, raw, rubric=rubric())


@pytest.mark.parametrize("count", [0, 81])
def test_stage1_rejects_empty_or_oversized_segment_inventory(count):
    with pytest.raises(EvaluationValidationError):
        validate_segments(
            "PG-TX-01",
            ANSWER,
            raw_segments(["в одной транзакции"] * count),
            rubric=rubric(),
        )


def test_scoring_schema_requires_exact_ids_for_routed_criterion():
    r = rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "q1",
            "claim_type": "mechanism",
            "criterion_links": [{"criterion_id": "PG-TX-01-K1", "reason": "topic"}],
        },
        {
            "segment_id": "S002",
            "quote": "q2",
            "claim_type": "test",
            "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}],
        },
    ]
    schema = scoring_schema_for("PG-TX-01", segments, rubric=r)
    k1 = schema["properties"]["criteria"]["properties"]["PG-TX-01-K1"]["properties"][
        "segment_assessments"
    ]
    assert k1["type"] == "object"
    assert k1["required"] == ["S001"]
    assert k1["properties"]["S001"]["enum"] == [
        "supports",
        "partially_supports",
        "contradicts",
        "neutral",
    ]


def test_scoring_schema_uses_nonempty_sentinel_when_no_segments_routed():
    r = rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "q1",
            "claim_type": "other",
            "criterion_links": [],
        }
    ]
    schema = scoring_schema_for("PG-TX-01", segments, rubric=r)
    k5 = schema["properties"]["criteria"]["properties"]["PG-TX-01-K5"]["properties"][
        "segment_assessments"
    ]
    assert k5["type"] == "object"
    assert k5["required"] == ["__no_evidence__"]
    assert k5["properties"]["__no_evidence__"]["enum"] == ["not_applicable"]
    validate_schema(
        {"__no_evidence__": "not_applicable"},
        k5,
    )


def test_scoring_schema_rejects_omitted_linked_segment_before_semantic_check():
    r = rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "q1",
            "claim_type": "other",
            "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}],
        }
    ]
    schema = scoring_schema_for("PG-TX-01", segments, rubric=r)
    k5 = schema["properties"]["criteria"]["properties"]["PG-TX-01-K5"]["properties"][
        "segment_assessments"
    ]
    with pytest.raises(EvaluationValidationError):
        validate_schema({}, k5)


def test_stage1_prompt_keeps_current_answer_distinct_from_history_and_rubric():
    history = [{"question": "Previous question", "answer": "Previous answer"}]
    messages = segmentation_messages_for(
        "PG-TX-01", ANSWER, history=history, rubric=rubric()
    )
    assert [m["role"] for m in messages] == ["system", "developer", "user"]
    current = json.loads(messages[-1]["content"])
    assert current == {
        "current_question": "Concurrent debit",
        "candidate_answer": ANSWER,
    }
    context = json.loads(messages[1]["content"].split("\n", 1)[1])
    assert context["recent_history"] == history
    assert context["output_schema"] == segmentation_schema_for(
        "PG-TX-01", rubric=rubric()
    )
    assert [c["id"] for c in context["criteria"]] == [
        c["id"] for c in rubric()["criteria"]
    ]


def _valid_stage2_output(segments, r):
    links = {c["id"]: [] for c in r["criteria"]}
    for segment in segments:
        for link in segment["criterion_links"]:
            links[link["criterion_id"]].append(segment["segment_id"])
    criteria = {}
    for cid, ids in links.items():
        if ids:
            relations = {sid: "neutral" for sid in ids}
        else:
            relations = {"__no_evidence__": "not_applicable"}
        criteria[cid] = {
            "points": 0,
            "segment_assessments": relations,
            "reason": "No positively supporting evidence.",
        }
    return {
        "reviewed_segment_ids": {s["segment_id"]: True for s in segments},
        "criteria": criteria,
        "red_flag_checks": {
            f["id"]: {"detected": False, "evidence_ids": [], "reason": "No evidence."}
            for f in r["red_flag_definitions"]
        },
        "uncertainty": "low",
        "abstained": False,
        "summary": "Insufficient supporting detail.",
        "error_updates": [],
        "resolutions": [],
    }


def test_complete_stage2_output_accepts_no_evidence_criterion_and_linked_criterion():
    r = rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "transaction",
            "start": 0,
            "end": 11,
            "claim_type": "mechanism",
            "criterion_links": [
                {"criterion_id": "PG-TX-01-K1", "reason": "transaction"}
            ],
        },
    ]
    output = _valid_stage2_output(segments, r)
    result = check_segmented_output(
        "PG-TX-01",
        "transaction",
        segments,
        output,
        rubric=r,
        output_schema=scoring_schema_for("PG-TX-01", segments, rubric=r),
    )
    assert result["score"] == 0
    assert result["criteria"]["PG-TX-01-K1"]["evidence"][0]["segment_id"] == "S001"
    assert result["criteria"]["PG-TX-01-K5"]["evidence"] == []


def test_stage2_output_cannot_assign_unrouted_segment_to_empty_criterion():
    r = rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "transaction",
            "start": 0,
            "end": 11,
            "claim_type": "mechanism",
            "criterion_links": [
                {"criterion_id": "PG-TX-01-K1", "reason": "transaction"}
            ],
        },
    ]
    output = _valid_stage2_output(segments, r)
    output["criteria"]["PG-TX-01-K5"]["segment_assessments"] = {"S001": "neutral"}
    with pytest.raises(EvaluationValidationError):
        validate_schema(
            output,
            scoring_schema_for("PG-TX-01", segments, rubric=r),
        )


def test_stage2_output_cannot_omit_one_required_linked_segment():
    r = rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "one",
            "start": 0,
            "end": 3,
            "claim_type": "other",
            "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}],
        },
        {
            "segment_id": "S002",
            "quote": "two",
            "start": 4,
            "end": 7,
            "claim_type": "other",
            "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}],
        },
    ]
    output = _valid_stage2_output(segments, r)
    output["criteria"]["PG-TX-01-K5"]["segment_assessments"].pop("S002")
    with pytest.raises(EvaluationValidationError):
        validate_schema(output, scoring_schema_for("PG-TX-01", segments, rubric=r))


def test_semantic_claim_can_span_newline_without_changing_source_offsets():
    answer = "Первая мысль.\r\nВторая мысль."
    quote = "Первая мысль.\r\nВторая мысль."
    rows = validate_segments("PG-TX-01", answer, raw_segments([quote]), rubric=rubric())
    assert len(rows) == 1
    assert answer[rows[0]["start"] : rows[0]["end"]] == quote
    assert rows[0]["quote"] == quote


def test_legacy_stage2_array_fixture_is_normalized_to_fixed_object():
    r = rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "transaction",
            "start": 0,
            "end": 11,
            "claim_type": "mechanism",
            "criterion_links": [
                {"criterion_id": "PG-TX-01-K1", "reason": "transaction"}
            ],
        },
    ]
    output = _valid_stage2_output(segments, r)
    for cid, row in output["criteria"].items():
        linked = cid == "PG-TX-01-K1"
        row["segment_assessments"] = (
            [{"segment_id": "S001", "relation": "neutral"}] if linked else []
        )
    result = check_segmented_output(
        "PG-TX-01",
        "transaction",
        segments,
        output,
        rubric=r,
        output_schema=scoring_schema_for("PG-TX-01", segments, rubric=r),
    )
    assert result["score"] == 0


def test_live_two_stage_pipeline_uses_source_ids_and_exact_assessment_contract(
    monkeypatch,
):
    import rag.llm as llm

    r = rubric()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_JSON_MODE", "schema")
    monkeypatch.setenv("LLM_MESSAGE_MODE", "system_user")
    monkeypatch.setenv("LLM_PIPELINE_MODE", "two_stage")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "10")

    quotes = [
        "Связанные изменения лучше выполнять в одной транзакции.",
        "Два запроса могут одновременно работать с одним балансом",
        "Проверку остатка и само изменение нужно защитить от одновременного выполнения.",
        "При конкуренции транзакция может завершиться ошибкой.",
        "Проверю ситуацию, когда два списания запускаются одновременно.",
    ]
    calls = []

    def fake_request(messages, schema, schema_name, **kwargs):
        calls.append((schema_name, schema, messages))
        if schema_name == "backend_semantic_segments_v1":
            raw = {
                "segments": [
                    {
                        "quote": quote,
                        "claim_type": "other",
                        "criterion_links": [
                            {"criterion_id": f"PG-TX-01-K{i}", "reason": "test routing"}
                        ],
                    }
                    for i, quote in enumerate(quotes, start=1)
                ]
            }
            validate_schema(raw, schema)
            return raw, False

        criterion_schemas = schema["properties"]["criteria"]["properties"]
        criteria = {}
        for cid, row_schema in criterion_schemas.items():
            ass_schema = row_schema["properties"]["segment_assessments"]
            keys = list(ass_schema["properties"])
            if keys == ["__no_evidence__"]:
                assignments = {"__no_evidence__": "not_applicable"}
                points = 0
            else:
                assignments = {sid: "supports" for sid in keys}
                points = 1
            criteria[cid] = {
                "points": points,
                "segment_assessments": assignments,
                "reason": "Evidence was reviewed.",
            }

        red_flag_schema = schema["properties"]["red_flag_checks"]["properties"]
        output = {
            "reviewed_segment_ids": {
                sid: True
                for sid in schema["properties"]["reviewed_segment_ids"]["properties"]
            },
            "criteria": criteria,
            "red_flag_checks": {
                fid: {
                    "detected": False,
                    "evidence_ids": [],
                    "reason": "No evidence for this flag.",
                }
                for fid in red_flag_schema
            },
            "uncertainty": "low",
            "abstained": False,
            "summary": "Test assessment.",
            "error_updates": [],
            "resolutions": [],
        }
        validate_schema(output, schema)
        return output, False

    monkeypatch.setattr(llm, "_request_json", fake_request)
    result = llm.evaluate_live("PG-TX-01", ANSWER, rubric=r)

    assert result["score"] == 5
    assert [row[0] for row in calls] == [
        "backend_semantic_segments_v1",
        "backend_rubric_score_v2",
    ]
    stage1_output = calls[0][1]["properties"]["segments"]
    assert stage1_output["type"] == "array"
    assert "quote" in stage1_output["items"]["required"]
    assert "segment_id" not in stage1_output["items"]["properties"]
    assert result["source_alignment_review_required"] is False
    for i, quote in enumerate(quotes, start=1):
        cid = f"PG-TX-01-K{i}"
        assert result["criteria"][cid]["quote"] == quote
        evidence = result["criteria"][cid]["evidence"][0]
        assert evidence["segment_id"] == f"S{i:03d}"
        assert ANSWER[evidence["start"] : evidence["end"]] == quote
    stage2_k5 = calls[1][1]["properties"]["criteria"]["properties"]["PG-TX-01-K5"]
    assert stage2_k5["properties"]["segment_assessments"]["type"] == "object"


def test_provider_response_schema_failure_keeps_stage_in_diagnostics(monkeypatch):
    import rag.llm as llm

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": '{"unexpected":true}',
                            },
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse()
    )
    with pytest.raises(llm.LLMResponseError) as exc:
        llm._request_json(
            [{"role": "user", "content": "test"}],
            {
                "type": "object",
                "properties": {"required_value": {"type": "string"}},
                "required": ["required_value"],
                "additionalProperties": False,
            },
            "test_schema",
            model="test-model",
            base="https://provider.example/v1",
            api_key="x",
            timeout=3,
            json_mode="schema",
            message_mode="developer",
            stage="scoring",
        )
    assert exc.value.diagnostic.stage == "scoring"
    assert exc.value.diagnostic.code == "schema_mismatch"
