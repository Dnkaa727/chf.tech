"""Regression tests for invalid/missing model resolution references."""

from v3.engine import check_segmented_output, rubrics, scoring_messages_for

CARD_ID = "PY-ASYNC-01"


def _segment(segment_id, quote, criterion_id):
    return {
        "segment_id": segment_id,
        "quote": quote,
        "claim_type": "solution",
        "criterion_links": [{"criterion_id": criterion_id, "reason": "Связь с критерием."}],
        "start": 0,
        "end": len(quote),
    }


def _base_output(segments, *, positive_criterion=None):
    rubric = rubrics()[CARD_ID]
    criteria = {}
    for criterion in rubric["criteria"]:
        cid = criterion["id"]
        linked = [
            segment["segment_id"]
            for segment in segments
            if any(link["criterion_id"] == cid for link in segment["criterion_links"])
        ]
        criteria[cid] = {
            "points": 2 if cid == positive_criterion else 0,
            "segment_assessments": [
                {"segment_id": segment_id,
                 "relation": ("supports" if cid == positive_criterion else "neutral")}
                for segment_id in linked
            ],
            "reason": "Тестовая оценка критерия.",
        }
    checks = {
        flag["id"]: {
            "detected": False,
            "evidence_ids": [],
            "reason": "Флаг не обнаружен.",
        }
        for flag in rubric["red_flag_definitions"]
    }
    return {
        "reviewed_segment_ids": {segment["segment_id"]: True for segment in segments},
        "criteria": criteria,
        "red_flag_checks": checks,
        "uncertainty": "low",
        "abstained": False,
        "summary": "Тест.",
        "error_updates": [],
        "resolutions": [],
    }


def test_empty_unknown_resolution_does_not_discard_valid_assessment():
    cid = f"{CARD_ID}-K1"
    segment = _segment("S001", "Неверное утверждение кандидата.", cid)
    output = _base_output([segment])
    output["red_flag_checks"]["confidently_incorrect"] = {
        "detected": True,
        "evidence_ids": ["S001"],
        "reason": "Конкретное ложное утверждение.",
    }
    output["error_updates"] = [{
        "flag_id": "confidently_incorrect",
        "error_id": None,
        "criterion_id": cid,
        "reason": "Ошибка относится к K1.",
    }]
    # This is the exact provider failure seen in the live request.
    output["resolutions"] = [{
        "error_id": "",
        "criterion_id": f"{CARD_ID}-K2",
        "evidence_id": "S001",
        "reason": "Пустой error_id не может закрывать ошибку.",
    }]

    result = check_segmented_output(CARD_ID, segment["quote"], [segment], output)

    assert result["score"] == 0
    assert [flag["id"] for flag in result["red_flags"]] == ["confidently_incorrect"]
    assert result["_error_updates"]
    assert result["_resolutions"] == []


def test_valid_open_error_resolution_is_still_accepted():
    cid = f"{CARD_ID}-K2"
    segment = _segment("S001", "Для ожидания использую await asyncio.sleep(2).", cid)
    output = _base_output([segment], positive_criterion=cid)
    output["resolutions"] = [{
        "error_id": "error-existing-1",
        "criterion_id": cid,
        "evidence_id": "S001",
        "reason": "Кандидат исправил ранее отмеченное решение.",
    }]
    context = {"errors": [{
        "error_id": "error-existing-1",
        "criterion_id": cid,
        "status": "open",
    }]}

    result = check_segmented_output(CARD_ID, segment["quote"], [segment], output,
                                    error_context=context)

    assert len(result["_resolutions"]) == 1
    assert result["_resolutions"][0]["error_id"] == "error-existing-1"


def test_scoring_prompt_forbids_resolutions_when_no_open_errors_exist():
    cid = f"{CARD_ID}-K1"
    segment = _segment("S001", "time.sleep blocks the event loop.", cid)
    prompt = "\n".join(
        message["content"]
        for message in scoring_messages_for(CARD_ID, segment["quote"], [segment])
    )

    assert "нет открытых ошибок" in prompt.lower()
    assert "пустым массивом" in prompt.lower()
    assert "выдуманным error_id" in prompt.lower()
