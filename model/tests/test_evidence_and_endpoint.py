"""Regressions for altered technical evidence and non-local plaintext endpoints."""

from unittest.mock import patch

import pytest

from rag.diagnostics import EvaluationValidationError
from rag.engine import (
    check_output,
    locate_quote_spans,
    quote_matches_answer,
    rubrics,
    validate_segments,
)
from rag.llm import LLMConfigurationError, evaluate_live


CARD_ID = "PY-ASYNC-01"


@pytest.mark.parametrize(
    ("quote", "answer"),
    [
        ("value = 1", "value = -1"),
        ("value = 1", "value != 1"),
        ("value = 1", "value == 1"),
        ("value = 15", "value = 1.5"),
        ("value = 15", "value = 1,5"),
        ("cache key", "cache_key"),
        ("path to file", "path/to/file"),
        ("items1", "items[1]"),
    ],
)
def test_technical_punctuation_is_part_of_the_evidence(quote, answer):
    assert not quote_matches_answer(quote, answer)
    assert locate_quote_spans(quote, answer) == []


def test_case_spacing_and_prose_comma_keep_original_source_offsets():
    answer = "ДВА запроса, одновременно прочитают старый баланс!"
    quote = "два   запроса одновременно\nпрочитают старый баланс"
    assert quote_matches_answer(quote, answer)
    spans = locate_quote_spans(quote, answer)
    assert len(spans) == 1
    start, end = spans[0]
    assert answer[start:end] == "ДВА запроса, одновременно прочитают старый баланс"


def test_changed_number_cannot_earn_points_in_strict_evidence_mode():
    criteria = rubrics()[CARD_ID]["criteria"]
    output = {
        "criteria": {
            criterion["id"]: {
                "points": 2 if index == 0 else 0,
                "quote": "value = 1" if index == 0 else "",
                "reason": "test",
            }
            for index, criterion in enumerate(criteria)
        },
        "red_flags": [],
        "uncertainty": "low",
        "abstained": False,
        "summary": "test",
        "error_updates": [],
        "resolutions": [],
    }
    with pytest.raises(EvaluationValidationError) as error:
        check_output(CARD_ID, "value = -1", output, strict_evidence=True)
    assert error.value.diagnostic.code == "invalid_quote"


def test_changed_number_requires_source_review_in_two_stage_pipeline():
    result = validate_segments(
        CARD_ID,
        "value = -1",
        {
            "segments": [
                {
                    "quote": "value = 1",
                    "claim_type": "example",
                    "criterion_links": [],
                }
            ]
        },
    )
    assert result[0]["source_alignment"] == "unverified"
    assert result[0]["start"] is None and result[0]["end"] is None


@pytest.fixture
def configured_model(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "offline-test-key")
    monkeypatch.setenv("LLM_MODEL", "offline-test-model")
    monkeypatch.setenv("LLM_PIPELINE_MODE", "two_stage")
    monkeypatch.setenv("LLM_MESSAGE_MODE", "system_user")
    monkeypatch.setenv("LLM_JSON_MODE", "schema")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "10")


@pytest.mark.parametrize(
    "base",
    [
        "http://localhost.example.com/v1",
        "http://localhost@provider.example/v1",
        "http://127.0.0.1.example.com/v1",
        "http://provider.example/v1",
        "https://user:password@provider.example/v1",
        "https:///v1",
        "https://provider.example:99999/v1",
        "https://provider.example/v1?token=abc",
        "https://provider.example/v1#other-path",
        "https://provider. example/v1",
    ],
)
def test_invalid_endpoint_is_rejected_before_provider_call(
    configured_model, monkeypatch, base
):
    monkeypatch.setenv("LLM_BASE_URL", base)
    with patch("rag.llm._request_json") as provider:
        with pytest.raises(LLMConfigurationError):
            evaluate_live(CARD_ID, "An offline test answer.")
    provider.assert_not_called()


@pytest.mark.parametrize(
    "base",
    [
        "https://provider.example/v1",
        "http://localhost:5005/v1",
        "http://127.0.0.1:5005/v1",
        "http://[::1]:5005/v1",
    ],
)
def test_https_and_exact_loopback_endpoints_are_supported(
    configured_model, monkeypatch, base
):
    monkeypatch.setenv("LLM_BASE_URL", base)
    with patch("rag.llm._request_json", return_value=(None, True)) as provider:
        result = evaluate_live(CARD_ID, "An offline test answer.")
    assert result["refusal"] is True
    assert provider.call_args.kwargs["base"] == base
