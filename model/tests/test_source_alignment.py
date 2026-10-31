import pytest

from rag.diagnostics import EvaluationValidationError
from rag.engine import (
    check_segmented_output,
    scoring_messages_for,
    scoring_schema_for,
    validate_segments,
    public_assessment,
    _error_protocol,
)
from rag.json_validation import validate_schema


CARD_ID = "PG-TX-01"
CRITERION_IDS = [f"{CARD_ID}-K{i}" for i in range(1, 6)]


def _rubric():
    return {
        "card_id": CARD_ID,
        "topic": "PostgreSQL transactions",
        "question": "Как обеспечить корректность конкурентных списаний?",
        "version": "test",
        "status": "draft_needs_expert_review",
        "criteria": [
            {
                "id": cid,
                "name": f"Criterion {i}",
                "max_points": 2,
                "anchors": {"0": "none", "1": "partial", "2": "full"},
                "followup_question": "Почему?",
            }
            for i, cid in enumerate(CRITERION_IDS, start=1)
        ],
        "red_flag_definitions": [
            {
                "id": "confidently_incorrect",
                "definition": "Уверенное технически ложное утверждение",
            },
            {
                "id": "technical_contradiction",
                "definition": "Внутреннее техническое противоречие",
            },
        ],
        "evaluation_guidance": "Evaluate reasoning and evidence.",
    }


def _stage1(quote, links=None):
    return {
        "segments": [
            {
                "quote": quote,
                "claim_type": "mechanism",
                "criterion_links": links
                or [{"criterion_id": CRITERION_IDS[1], "reason": "Concurrent reads"}],
            }
        ]
    }


def _stage2_output(segments, rubric, *, points=2, relation="supports", red_flags=None):
    links = {cid: {} for cid in CRITERION_IDS}
    for segment in segments:
        for link in segment["criterion_links"]:
            links[link["criterion_id"]][segment["segment_id"]] = relation

    criteria = {}
    for index, cid in enumerate(CRITERION_IDS):
        assessments = links[cid] or {"__no_evidence__": "not_applicable"}
        criteria[cid] = {
            "points": points if cid == CRITERION_IDS[1] else 0,
            "segment_assessments": assessments,
            "reason": "Evidence evaluated against the criterion anchors.",
        }

    red_flag_checks = {}
    red_flags = red_flags or {}
    for definition in rubric["red_flag_definitions"]:
        flag_id = definition["id"]
        evidence_ids = red_flags.get(flag_id, [])
        red_flag_checks[flag_id] = {
            "detected": bool(evidence_ids),
            "evidence_ids": evidence_ids,
            "reason": "Concrete evidence found."
            if evidence_ids
            else "No evidence found.",
        }

    return {
        "reviewed_segment_ids": {segment["segment_id"]: True for segment in segments},
        "criteria": criteria,
        "red_flag_checks": red_flag_checks,
        "uncertainty": "low",
        "abstained": False,
        "summary": "Assessment complete.",
        "error_updates": [],
        "resolutions": [],
    }


def test_nonmatching_nonempty_quote_is_kept_as_unverified_not_fatal():
    rubric = _rubric()
    answer = "Два запроса одновременно прочитают одно и то же значение баланса."
    segments = validate_segments(
        CARD_ID,
        answer,
        _stage1("два запроса могут увидеть одинаковый остаток"),
        rubric=rubric,
    )

    assert segments == [
        {
            "segment_id": "S001",
            "quote": "два запроса могут увидеть одинаковый остаток",
            "source_alignment": "unverified",
            "start": None,
            "end": None,
            "claim_type": "mechanism",
            "criterion_links": [
                {"criterion_id": CRITERION_IDS[1], "reason": "Concurrent reads"}
            ],
        }
    ]


def test_exact_and_normalized_quote_matches_are_marked_matched():
    rubric = _rubric()
    answer = "ДВА запроса, одновременно прочитают старый баланс!"
    raw = _stage1("два запроса одновременно прочитают старый баланс")
    segments = validate_segments(CARD_ID, answer, raw, rubric=rubric)

    assert segments[0]["source_alignment"] == "matched"
    assert segments[0]["quote"] == "ДВА запроса, одновременно прочитают старый баланс"
    assert answer[segments[0]["start"] : segments[0]["end"]] == segments[0]["quote"]


def test_repeated_fragment_rows_reuse_a_found_source_span_instead_of_becoming_unverified():
    rubric = _rubric()
    raw = {
        "segments": [
            {
                "quote": "два запроса",
                "claim_type": "test",
                "criterion_links": [],
            },
            {
                "quote": "два запроса",
                "claim_type": "other",
                "criterion_links": [],
            },
            {
                "quote": "два запроса",
                "claim_type": "example",
                "criterion_links": [],
            },
        ]
    }
    answer = "Два запроса"
    segments = validate_segments(CARD_ID, answer, raw, rubric=rubric)
    assert [s["source_alignment"] for s in segments] == [
        "matched",
        "matched",
        "matched",
    ]
    assert [(s["start"], s["end"]) for s in segments] == [(0, 11)] * 3
    assert all(answer[s["start"] : s["end"]] == s["quote"] for s in segments)


def test_repeated_unlinked_fragments_do_not_force_human_review_or_hide_score():
    rubric = _rubric()
    answer = "Два запроса"
    raw = {
        "segments": [
            {"quote": "два запроса", "claim_type": kind, "criterion_links": []}
            for kind in ("test", "other", "example")
        ]
    }
    segments = validate_segments(CARD_ID, answer, raw, rubric=rubric)
    output = _stage2_output(segments, rubric, points=0)
    result = check_segmented_output(
        CARD_ID,
        answer,
        segments,
        output,
        rubric=rubric,
        output_schema=scoring_schema_for(CARD_ID, segments, rubric=rubric),
    )

    assert result["unverified_segment_ids"] == []
    assert result["source_alignment_review_required"] is False
    assert result["needs_review"] is False
    assert result["score"] == 0
    assert [row["source_alignment"] for row in result["segment_alignment"]] == [
        "matched",
        "matched",
        "matched",
    ]


def test_stage2_schema_uses_fixed_key_objects_and_empty_criterion_sentinel():
    rubric = _rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "два запроса",
            "source_alignment": "matched",
            "start": 0,
            "end": 11,
            "claim_type": "mechanism",
            "criterion_links": [
                {"criterion_id": CRITERION_IDS[1], "reason": "Concurrent reads"}
            ],
        }
    ]
    schema = scoring_schema_for(CARD_ID, segments, rubric=rubric)
    criteria_schema = schema["properties"]["criteria"]["properties"]
    linked = criteria_schema[CRITERION_IDS[1]]["properties"]["segment_assessments"]
    empty = criteria_schema[CRITERION_IDS[4]]["properties"]["segment_assessments"]

    assert linked["type"] == "object"
    assert linked["required"] == ["S001"]
    assert linked["properties"]["S001"]["enum"] == [
        "supports",
        "partially_supports",
        "contradicts",
        "neutral",
    ]
    assert empty["required"] == ["__no_evidence__"]
    validate_schema({"__no_evidence__": "not_applicable"}, empty)


def test_stage2_object_contract_rejects_unrouted_or_missing_segment_ids():
    rubric = _rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "два запроса",
            "source_alignment": "matched",
            "start": 0,
            "end": 11,
            "claim_type": "mechanism",
            "criterion_links": [
                {"criterion_id": CRITERION_IDS[1], "reason": "Concurrent reads"}
            ],
        }
    ]
    schema = scoring_schema_for(CARD_ID, segments, rubric=rubric)
    criteria_schema = schema["properties"]["criteria"]["properties"]
    linked_schema = criteria_schema[CRITERION_IDS[1]]["properties"][
        "segment_assessments"
    ]
    empty_schema = criteria_schema[CRITERION_IDS[4]]["properties"][
        "segment_assessments"
    ]

    with pytest.raises(EvaluationValidationError):
        validate_schema({}, linked_schema)
    with pytest.raises(EvaluationValidationError):
        validate_schema({"S001": "neutral"}, empty_schema)


def test_unverified_segment_flows_through_stage2_and_is_exposed_for_human_review():
    rubric = _rubric()
    answer = "Два запроса одновременно прочитают одно и то же значение баланса."
    segments = validate_segments(
        CARD_ID,
        answer,
        _stage1("два запроса могут увидеть одинаковый остаток"),
        rubric=rubric,
    )
    output = _stage2_output(segments, rubric)
    result = check_segmented_output(
        CARD_ID,
        answer,
        segments,
        output,
        rubric=rubric,
        output_schema=scoring_schema_for(CARD_ID, segments, rubric=rubric),
    )

    evidence = result["criteria"][CRITERION_IDS[1]]["evidence"][0]
    assert result["score"] == 2
    assert result["needs_review"] is True
    assert result["source_alignment_review_required"] is True
    assert result["unverified_segment_ids"] == ["S001"]
    assert result["segment_alignment"][0]["text"] == segments[0]["quote"]
    assert result["segment_alignment"][0]["source_alignment"] == "unverified"
    assert evidence["source_alignment"] == "unverified"
    assert evidence["start"] is None and evidence["end"] is None
    assert result["warnings"] == []
    public = public_assessment(result)
    assert public["score"] is None
    assert public["source_alignment_review_required"] is True


def test_unverified_segment_can_be_used_as_red_flag_evidence_without_quote_failure():
    rubric = _rubric()
    answer = "SQL гарантирует правильное списание даже без условий."
    segments = validate_segments(
        CARD_ID,
        answer,
        _stage1("SQL гарантирует корректное списание без каких-либо условий"),
        rubric=rubric,
    )
    output = _stage2_output(
        segments,
        rubric,
        points=0,
        red_flags={"confidently_incorrect": ["S001"]},
    )
    # This also checks that a detected segmented flag with an unverified
    # paraphrase does not fail the legacy quote-string checks in _error_protocol.
    output["error_updates"] = [
        {
            "flag_id": "confidently_incorrect",
            "error_id": None,
            "criterion_id": CRITERION_IDS[1],
            "reason": "The claim gives a false guarantee.",
        }
    ]
    result = check_segmented_output(
        CARD_ID,
        answer,
        segments,
        output,
        rubric=rubric,
        output_schema=scoring_schema_for(CARD_ID, segments, rubric=rubric),
    )
    assert result["red_flags"][0]["source_alignment"] == "unverified"
    assert result["_error_updates"][0]["flag_index"] == 0


def test_empty_stage1_quote_remains_a_malformed_record():
    with pytest.raises(EvaluationValidationError) as exc:
        validate_segments(CARD_ID, "any answer", _stage1("   "), rubric=_rubric())
    assert exc.value.diagnostic.code == "schema_mismatch"
    assert exc.value.diagnostic.field == "quote"


def test_stage2_prompt_matches_object_schema_contract():
    rubric = _rubric()
    segments = [
        {
            "segment_id": "S001",
            "quote": "two requests",
            "source_alignment": "matched",
            "start": 0,
            "end": 12,
            "claim_type": "mechanism",
            "criterion_links": [
                {"criterion_id": CRITERION_IDS[1], "reason": "Concurrent reads"}
            ],
        }
    ]
    messages = scoring_messages_for(CARD_ID, "two requests", segments, rubric=rubric)
    text = "\n".join(message["content"] for message in messages)
    assert "объект segment_assessments" in text
    assert "__no_evidence__" in text
    assert "массивы для segment_assessments" in text


def test_unverified_segment_can_resolve_known_error_after_segment_id_validation():
    rubric = _rubric()
    answer = "Два запроса одновременно прочитают одно и то же значение баланса."
    segments = validate_segments(
        CARD_ID,
        answer,
        _stage1("два запроса могут увидеть одинаковый остаток"),
        rubric=rubric,
    )
    output = _stage2_output(segments, rubric)
    error_context = {
        "errors": [
            {
                "error_id": "ERR-1",
                "status": "open",
                "criterion_id": CRITERION_IDS[1],
            }
        ]
    }
    output["resolutions"] = [
        {
            "error_id": "ERR-1",
            "criterion_id": CRITERION_IDS[1],
            "evidence_id": "S001",
            "reason": "The current answer corrects the previously recorded issue.",
        }
    ]
    result = check_segmented_output(
        CARD_ID,
        answer,
        segments,
        output,
        error_context=error_context,
        rubric=rubric,
        output_schema=scoring_schema_for(CARD_ID, segments, rubric=rubric),
    )
    assert result["_resolutions"][0]["error_id"] == "ERR-1"
    assert result["_resolutions"][0]["quote"] == segments[0]["quote"]


def test_legacy_one_stage_error_protocol_still_requires_verbatim_quotes():
    answer = "Два запроса одновременно прочитают одно и то же значение баланса."
    criteria = {
        CRITERION_IDS[1]: {
            "points": 1,
            "quote": "два запроса могут увидеть одинаковый остаток",
            "reason": "Partial evidence",
        }
    }
    flags = [
        {
            "id": "confidently_incorrect",
            "quote": "два запроса могут увидеть одинаковый остаток",
            "reason": "Incorrect claim",
        }
    ]
    updates = [
        {
            "flag_index": 0,
            "error_id": None,
            "criterion_id": CRITERION_IDS[1],
            "reason": "Affects this criterion.",
        }
    ]
    with pytest.raises(ValueError):
        _error_protocol(answer, criteria, flags, updates, [], error_context=None)
