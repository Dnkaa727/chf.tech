
import json
import pytest

from v3.engine import (
    split_answer_into_source_segments,
    segmentation_schema_for,
    segmentation_messages_for,
    validate_segments,
    scoring_schema_for,
    check_segmented_output,
)
from v3.json_validation import validate_schema
from v3.diagnostics import EvaluationValidationError


def rubric():
    return {
        "card_id": "PG-TX-01",
        "topic": "PostgreSQL transactions",
        "question": "Concurrent debit",
        "status": "draft_needs_expert_review",
        "version": "test",
        "criteria": [
            {"id": f"PG-TX-01-K{i}", "name": f"K{i}", "anchors": {"0": "0", "1": "1", "2": "2"},
             "followup_question": "Why?"}
            for i in range(1, 6)
        ],
        "red_flag_definitions": [
            {"id": "technical_contradiction", "definition": "Contradiction"},
            {"id": "confidently_incorrect", "definition": "Confident false technical claim"},
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


def test_source_segments_are_exact_and_stable():
    rows = split_answer_into_source_segments(ANSWER)
    assert [x["segment_id"] for x in rows] == [f"S{i:03d}" for i in range(1, 6)]
    cursor = 0
    for row in rows:
        assert not ANSWER[cursor:row["start"]].strip()
        assert ANSWER[row["start"]:row["end"]] == row["quote"]
        cursor = row["end"]
    assert not ANSWER[cursor:].strip()


def test_source_split_does_not_split_common_abbreviations_or_decimal():
    text = "Используем т.е. атомарную операцию. Значение 2.5 секунды допустимо; проверим."
    rows = split_answer_into_source_segments(text)
    assert len(rows) == 3
    assert rows[0]["quote"] == "Используем т.е. атомарную операцию."
    assert rows[1]["quote"] == "Значение 2.5 секунды допустимо;"
    assert rows[2]["quote"] == "проверим."


def test_stage1_schema_requires_fixed_source_ids_and_no_quote_field():
    rows = split_answer_into_source_segments(ANSWER)
    schema = segmentation_schema_for("PG-TX-01", rows, rubric=rubric())
    props = schema["properties"]["segments"]["properties"]
    assert list(props) == [x["segment_id"] for x in rows]
    assert schema["properties"]["segments"]["required"] == list(props)
    assert "quote" not in props["S001"]["properties"]


def test_stage1_validation_reconstructs_source_quotes_without_model_quotes():
    r = rubric()
    source = split_answer_into_source_segments(ANSWER)
    raw = {"segments": {
        row["segment_id"]: {
            "claim_type": "other",
            "criterion_links": (
                [{"criterion_id": "PG-TX-01-K1", "reason": "mentions transaction"}]
                if row["segment_id"] == "S001" else []
            ),
        }
        for row in source
    }}
    result = validate_segments("PG-TX-01", ANSWER, raw, rubric=r, source_segments=source)
    assert [x["quote"] for x in result] == [x["quote"] for x in source]
    assert result[0]["criterion_links"][0]["criterion_id"] == "PG-TX-01-K1"


def test_stage1_missing_source_id_is_rejected():
    r = rubric()
    source = split_answer_into_source_segments(ANSWER)
    raw = {"segments": {
        row["segment_id"]: {"claim_type": "other", "criterion_links": []}
        for row in source[:-1]
    }}
    with pytest.raises(EvaluationValidationError):
        validate_segments("PG-TX-01", ANSWER, raw, rubric=r, source_segments=source)


def test_scoring_schema_requires_exact_ids_for_routed_criterion():
    r = rubric()
    segments = [
        {"segment_id": "S001", "quote": "q1", "claim_type": "mechanism",
         "criterion_links": [{"criterion_id": "PG-TX-01-K1", "reason": "topic"}]},
        {"segment_id": "S002", "quote": "q2", "claim_type": "test",
         "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}]},
    ]
    schema = scoring_schema_for("PG-TX-01", segments, rubric=r)
    k1 = schema["properties"]["criteria"]["properties"]["PG-TX-01-K1"]["properties"]["segment_assessments"]
    assert k1["type"] == "object"
    assert k1["required"] == ["S001"]
    assert k1["properties"]["S001"]["enum"] == [
        "supports", "partially_supports", "contradicts", "neutral"
    ]


def test_scoring_schema_uses_nonempty_sentinel_when_no_segments_routed():
    r = rubric()
    segments = [{"segment_id": "S001", "quote": "q1", "claim_type": "other",
                 "criterion_links": []}]
    schema = scoring_schema_for("PG-TX-01", segments, rubric=r)
    k5 = schema["properties"]["criteria"]["properties"]["PG-TX-01-K5"]["properties"]["segment_assessments"]
    assert k5["type"] == "object"
    assert k5["required"] == ["__no_evidence__"]
    assert k5["properties"]["__no_evidence__"]["enum"] == ["not_applicable"]
    validate_schema(
        {"__no_evidence__": "not_applicable"},
        k5,
    )


def test_scoring_schema_rejects_omitted_linked_segment_before_semantic_check():
    r = rubric()
    segments = [{"segment_id": "S001", "quote": "q1", "claim_type": "other",
                 "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}]}]
    schema = scoring_schema_for("PG-TX-01", segments, rubric=r)
    k5 = schema["properties"]["criteria"]["properties"]["PG-TX-01-K5"]["properties"]["segment_assessments"]
    with pytest.raises(EvaluationValidationError):
        validate_schema({}, k5)


def test_stage1_messages_never_ask_model_to_copy_quotes():
    messages = segmentation_messages_for(
        "PG-TX-01", ANSWER, rubric=rubric(),
        source_segments=split_answer_into_source_segments(ANSWER),
    )
    full = "\n".join(x["content"] for x in messages)
    assert "не создавай" in full.lower()
    assert "source_segments" in full
    assert "quote" not in json.loads(messages[-1]["content"])["source_segments"][0]




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
        {"segment_id": "S001", "quote": "transaction", "start": 0, "end": 11,
         "claim_type": "mechanism",
         "criterion_links": [{"criterion_id": "PG-TX-01-K1", "reason": "transaction"}]},
    ]
    output = _valid_stage2_output(segments, r)
    result = check_segmented_output(
        "PG-TX-01", "transaction", segments, output, rubric=r,
        output_schema=scoring_schema_for("PG-TX-01", segments, rubric=r),
    )
    assert result["score"] == 0
    assert result["criteria"]["PG-TX-01-K1"]["evidence"][0]["segment_id"] == "S001"
    assert result["criteria"]["PG-TX-01-K5"]["evidence"] == []


def test_stage2_output_cannot_assign_unrouted_segment_to_empty_criterion():
    r = rubric()
    segments = [
        {"segment_id": "S001", "quote": "transaction", "start": 0, "end": 11,
         "claim_type": "mechanism",
         "criterion_links": [{"criterion_id": "PG-TX-01-K1", "reason": "transaction"}]},
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
        {"segment_id": "S001", "quote": "one", "start": 0, "end": 3, "claim_type": "other",
         "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}]},
        {"segment_id": "S002", "quote": "two", "start": 4, "end": 7, "claim_type": "other",
         "criterion_links": [{"criterion_id": "PG-TX-01-K5", "reason": "test"}]},
    ]
    output = _valid_stage2_output(segments, r)
    output["criteria"]["PG-TX-01-K5"]["segment_assessments"].pop("S002")
    with pytest.raises(EvaluationValidationError):
        validate_schema(output, scoring_schema_for("PG-TX-01", segments, rubric=r))


def test_source_split_handles_newlines_as_boundaries():
    text = "Первое утверждение.\r\nВторое утверждение."
    rows = split_answer_into_source_segments(text)
    assert [row["quote"] for row in rows] == [
        "Первое утверждение.", "Второе утверждение."
    ]


def test_legacy_stage1_fixture_still_supported_for_offline_tests():
    r = rubric()
    raw = {"segments": [{
        "quote": "Связанные изменения лучше выполнять в одной транзакции.",
        "claim_type": "mechanism",
        "criterion_links": [
            {"criterion_id": "PG-TX-01-K1", "reason": "transaction boundary"}
        ],
    }]}
    result = validate_segments("PG-TX-01", ANSWER, raw, rubric=r)
    assert result[0]["quote"] == raw["segments"][0]["quote"]


def test_legacy_stage2_array_fixture_is_normalized_to_fixed_object():
    r = rubric()
    segments = [
        {"segment_id": "S001", "quote": "transaction", "start": 0, "end": 11,
         "claim_type": "mechanism",
         "criterion_links": [{"criterion_id": "PG-TX-01-K1", "reason": "transaction"}]},
    ]
    output = _valid_stage2_output(segments, r)
    for cid, row in output["criteria"].items():
        linked = cid == "PG-TX-01-K1"
        row["segment_assessments"] = (
            [{"segment_id": "S001", "relation": "neutral"}] if linked else []
        )
    result = check_segmented_output(
        "PG-TX-01", "transaction", segments, output, rubric=r,
        output_schema=scoring_schema_for("PG-TX-01", segments, rubric=r),
    )
    assert result["score"] == 0


def test_live_two_stage_pipeline_uses_source_ids_and_exact_assessment_contract(monkeypatch):
    import v3.llm as llm

    r = rubric()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_JSON_MODE", "schema")
    monkeypatch.setenv("LLM_MESSAGE_MODE", "system_user")
    monkeypatch.setenv("LLM_PIPELINE_MODE", "two_stage")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "10")

    calls = []

    def fake_request(messages, schema, schema_name, **kwargs):
        calls.append((schema_name, schema, messages))
        if schema_name == "backend_semantic_segments_v1":
            source_ids = list(schema["properties"]["segments"]["properties"])
            return {
                "segments": {
                    sid: {
                        "claim_type": "other",
                        "criterion_links": [{
                            "criterion_id": f"PG-TX-01-K{i}",
                            "reason": "test routing",
                        }],
                    }
                    for i, sid in enumerate(source_ids, start=1)
                }
            }, False

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
                sid: True for sid in schema["properties"]["reviewed_segment_ids"]["properties"]
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
        "backend_semantic_segments_v1", "backend_rubric_score_v2"
    ]
    stage1_output = calls[0][1]["properties"]["segments"]
    assert stage1_output["type"] == "object"
    assert "quote" not in stage1_output["properties"]["S001"]["properties"]
    stage2_k5 = calls[1][1]["properties"]["criteria"]["properties"]["PG-TX-01-K5"]
    assert stage2_k5["properties"]["segment_assessments"]["type"] == "object"


def test_provider_response_schema_failure_keeps_stage_in_diagnostics(monkeypatch):
    import v3.llm as llm

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "{\"unexpected\":true}"},
                }]
            }).encode("utf-8")

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(llm.LLMResponseError) as exc:
        llm._request_json(
            [{"role": "user", "content": "test"}],
            {"type": "object", "properties": {"required_value": {"type": "string"}},
             "required": ["required_value"], "additionalProperties": False},
            "test_schema",
            model="test-model", base="https://provider.example/v1", api_key="x",
            timeout=3, json_mode="schema", message_mode="developer", stage="scoring",
        )
    assert exc.value.diagnostic.stage == "scoring"
    assert exc.value.diagnostic.code == "schema_mismatch"
