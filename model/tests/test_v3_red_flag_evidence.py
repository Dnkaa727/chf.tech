"""Regression tests for preserving source evidence on detected red flags.

Run from the project root:
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_v3_red_flag_evidence.py -q
"""

from v3.engine import check_segmented_output, rubrics, scoring_messages_for

CARD_ID = "PY-ASYNC-01"


def _segments(rows):
    return [
        {
            "segment_id": f"S{i:03d}",
            "quote": quote,
            "claim_type": claim_type,
            "criterion_links": [
                {"criterion_id": criterion_id, "reason": "Связь с критерием."}
                for criterion_id in criterion_ids
            ],
            "start": 0,
            "end": len(quote),
        }
        for i, (quote, claim_type, criterion_ids) in enumerate(rows, start=1)
    ]


def _output(segments, *, relations=None, points=None, detected_flags=None, error_updates=None):
    rubric = rubrics()[CARD_ID]
    relations = relations or {}
    points = points or {}
    linked_ids = {criterion["id"]: [] for criterion in rubric["criteria"]}
    for segment in segments:
        for link in segment["criterion_links"]:
            linked_ids[link["criterion_id"]].append(segment["segment_id"])

    criteria = {}
    for criterion in rubric["criteria"]:
        criterion_id = criterion["id"]
        criteria[criterion_id] = {
            "points": points.get(criterion_id, 0),
            "segment_assessments": [
                {"segment_id": segment_id,
                 "relation": relations.get((criterion_id, segment_id), "neutral")}
                for segment_id in linked_ids[criterion_id]
            ],
            "reason": "Тестовое объяснение оценки.",
        }

    red_flag_checks = {
        flag["id"]: {
            "detected": False,
            "evidence_ids": [],
            "reason": "Доказательства этого флага отсутствуют.",
        }
        for flag in rubric["red_flag_definitions"]
    }
    for flag_id, evidence_ids in (detected_flags or {}).items():
        red_flag_checks[flag_id] = {
            "detected": True,
            "evidence_ids": list(evidence_ids),
            "reason": "Фрагменты ответа подтверждают этот red flag.",
        }

    return {
        "reviewed_segment_ids": {segment["segment_id"]: True for segment in segments},
        "criteria": criteria,
        "red_flag_checks": red_flag_checks,
        "uncertainty": "medium",
        "abstained": False,
        "summary": "Тестовый ответ.",
        "error_updates": list(error_updates or []),
        "resolutions": [],
    }


def test_self_contradiction_preserves_both_source_segments():
    segments = _segments([
        ("time.sleep(2) блокирует поток event loop.", "effect", ["PY-ASYNC-01-K1"]),
        ("Другие корутины не смогут выполняться.", "effect", ["PY-ASYNC-01-K1"]),
        ("Во время time.sleep event loop продолжит переключать корутины.", "mechanism", ["PY-ASYNC-01-K1"]),
        ("Для неблокирующего ожидания использую asyncio.sleep(2).", "solution", ["PY-ASYNC-01-K2"]),
    ])
    answer = " ".join(segment["quote"] for segment in segments)
    output = _output(
        segments,
        relations={
            ("PY-ASYNC-01-K1", "S001"): "supports",
            ("PY-ASYNC-01-K1", "S002"): "supports",
            ("PY-ASYNC-01-K1", "S003"): "contradicts",
            ("PY-ASYNC-01-K2", "S004"): "supports",
        },
        points={"PY-ASYNC-01-K1": 1, "PY-ASYNC-01-K2": 2},
        detected_flags={"technical_contradiction": ["S001", "S003"]},
    )

    result = check_segmented_output(CARD_ID, answer, segments, output)
    flag = result["red_flags"][0]

    # Existing consumers keep getting the old single-quote field.
    assert flag["quote"] == segments[0]["quote"]
    # New evidence field preserves both sides of the contradiction.
    assert flag["evidence"] == [
        {"segment_id": "S001", "quote": segments[0]["quote"]},
        {"segment_id": "S003", "quote": segments[2]["quote"]},
    ]


def test_confidently_incorrect_uses_the_false_claim_not_the_correct_premise():
    segments = _segments([
        ("time.sleep(2) блокирует поток event loop.", "effect", ["PY-ASYNC-01-K1"]),
        ("Но time.sleep автоматически отдаёт управление event loop.", "mechanism", ["PY-ASYNC-01-K1"]),
    ])
    answer = " ".join(segment["quote"] for segment in segments)
    output = _output(
        segments,
        relations={
            ("PY-ASYNC-01-K1", "S001"): "supports",
            ("PY-ASYNC-01-K1", "S002"): "contradicts",
        },
        points={"PY-ASYNC-01-K1": 1},
        detected_flags={"confidently_incorrect": ["S002"]},
        error_updates=[{
            "flag_id": "confidently_incorrect",
            "error_id": None,
            "criterion_id": "PY-ASYNC-01-K1",
            "reason": "Ложное утверждение относится к механизму блокировки.",
        }],
    )

    result = check_segmented_output(CARD_ID, answer, segments, output)
    flag = result["red_flags"][0]

    assert flag["id"] == "confidently_incorrect"
    assert flag["quote"] == segments[1]["quote"]
    assert flag["evidence"] == [
        {"segment_id": "S002", "quote": segments[1]["quote"]}
    ]
    assert result["_error_updates"][0]["flag_index"] == 0


def test_scoring_prompt_requires_complete_evidence_for_a_self_contradiction():
    segments = _segments([
        ("time.sleep блокирует event loop.", "effect", ["PY-ASYNC-01-K1"]),
        ("event loop переключает корутины во время time.sleep.", "mechanism", ["PY-ASYNC-01-K1"]),
    ])
    prompt = "\n".join(
        message["content"]
        for message in scoring_messages_for(CARD_ID, "Тестовый ответ.", segments)
    ).lower()

    assert "обе" in prompt
    assert "противоречащие части" in prompt
    assert "именно сегмент с ложным утверждением" in prompt
    assert "evidence_ids" in prompt


def test_confidently_incorrect_filters_correct_premise_but_contradiction_keeps_both_sides():
    """A false claim gets its own proof; a self-contradiction keeps both claims."""
    segments = _segments([
        ("time.sleep(2) блокирует поток event loop.", "mechanism", ["PY-ASYNC-01-K1"]),
        ("Другие корутины не смогут выполняться.", "effect", ["PY-ASYNC-01-K1"]),
        ("Но event loop продолжит переключать корутины во время time.sleep.", "mechanism", ["PY-ASYNC-01-K1"]),
    ])
    answer = " ".join(segment["quote"] for segment in segments)
    output = _output(
        segments,
        relations={
            ("PY-ASYNC-01-K1", "S001"): "supports",
            ("PY-ASYNC-01-K1", "S002"): "supports",
            ("PY-ASYNC-01-K1", "S003"): "contradicts",
        },
        points={"PY-ASYNC-01-K1": 1},
        detected_flags={
            # Simulate the provider's over-inclusive evidence selection.
            "confidently_incorrect": ["S001", "S003"],
            "technical_contradiction": ["S001", "S003"],
        },
    )

    result = check_segmented_output(CARD_ID, answer, segments, output)
    flags = {flag["id"]: flag for flag in result["red_flags"]}

    assert flags["confidently_incorrect"]["quote"] == segments[2]["quote"]
    assert flags["confidently_incorrect"]["evidence"] == [
        {"segment_id": "S003", "quote": segments[2]["quote"]}
    ]
    assert flags["technical_contradiction"]["quote"] == segments[0]["quote"]
    assert flags["technical_contradiction"]["evidence"] == [
        {"segment_id": "S001", "quote": segments[0]["quote"]},
        {"segment_id": "S003", "quote": segments[2]["quote"]},
    ]


def test_scoring_prompt_uses_contradiction_relations_to_select_false_claim_evidence():
    segments = _segments([
        ("time.sleep блокирует event loop.", "mechanism", ["PY-ASYNC-01-K1"]),
        ("event loop переключает корутины во время time.sleep.", "mechanism", ["PY-ASYNC-01-K1"]),
    ])
    prompt = "\n".join(
        message["content"]
        for message in scoring_messages_for(CARD_ID, "Тестовый ответ.", segments)
    ).lower()

    assert "segment_assessments" in prompt
    assert "только эти ошибочные сегменты" in prompt
    assert "не включай supports" in prompt
