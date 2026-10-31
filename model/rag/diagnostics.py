"""Allowlisted failure metadata. Never log prompts, responses, or provider messages."""

from dataclasses import dataclass
import json
import logging
import re
from uuid import uuid4

ERROR_CODES = frozenset(
    (
        "invalid_configuration",
        "provider_http_error",
        "provider_timeout",
        "provider_unavailable",
        "invalid_json",
        "unexpected_response",
        "incomplete_response",
        "schema_mismatch",
        "schema_definition_error",
        "invalid_quote",
        "invalid_error_link",
        "unexpected_error",
    )
)
SAFE_FIELDS = frozenset(
    (
        "criteria",
        "points",
        "quote",
        "reason",
        "red_flags",
        "id",
        "uncertainty",
        "abstained",
        "summary",
        "error_updates",
        "resolutions",
        "error_id",
        "criterion_id",
        "flag_index",
        "response_envelope",
        "message_content",
        "segments",
        "criterion_links",
        "reviewed_segment_ids",
        "evidence_ids",
        "evidence_id",
        "segment_assessments",
        "red_flag_checks",
    )
)
logger = logging.getLogger("rag.llm")


def safe_provider_token(value):
    """Return a short, header/log-safe provider code; discard arbitrary text."""
    if not isinstance(value, (str, int)):
        return None
    token = re.sub(r"[^A-Za-z0-9_.:-]", "", str(value))[:100]
    return token or None


@dataclass(frozen=True)
class FailureDetail:
    code: str
    criterion_id: str | None = None
    field: str | None = None
    provider_status: int | None = None
    stage: str | None = None
    provider_error_code: str | None = None
    provider_error_type: str | None = None
    provider_param: str | None = None
    provider_request_id: str | None = None


class EvaluationValidationError(ValueError):
    def __init__(self, code, *, criterion_id=None, field=None):
        super().__init__("Evaluation response validation failed")
        self.diagnostic = FailureDetail(code, criterion_id, field)


def failure_headers(error, *, card_id, criterion_ids):
    detail = getattr(error, "diagnostic", None)
    if not isinstance(detail, FailureDetail):
        detail = FailureDetail("unexpected_error")
    code = (
        detail.code
        if isinstance(detail.code, str) and detail.code in ERROR_CODES
        else "unexpected_error"
    )
    criterion_id = (
        detail.criterion_id
        if isinstance(detail.criterion_id, str) and detail.criterion_id in criterion_ids
        else None
    )
    field = (
        detail.field
        if isinstance(detail.field, str) and detail.field in SAFE_FIELDS
        else None
    )
    stage = (
        detail.stage
        if detail.stage in ("evaluation", "segmentation", "scoring")
        else None
    )
    status = detail.provider_status
    status = status if type(status) is int and 100 <= status <= 599 else None
    provider_code = safe_provider_token(detail.provider_error_code)
    provider_type = safe_provider_token(detail.provider_error_type)
    provider_param = safe_provider_token(detail.provider_param)
    provider_request_id = safe_provider_token(detail.provider_request_id)

    request_id = uuid4().hex
    record = {
        "request_id": request_id,
        "code": code,
        "card_id": card_id,
        "criterion_id": criterion_id,
        "field": field,
        "provider_status": status,
        "stage": stage,
        "provider_error_code": provider_code,
        "provider_error_type": provider_type,
        "provider_param": provider_param,
        "provider_request_id": provider_request_id,
    }
    logger.warning("llm_evaluation_failed %s", json.dumps(record, sort_keys=True))

    headers = {"X-Request-ID": request_id, "X-LLM-Error-Code": code}
    if stage is not None:
        headers["X-LLM-Stage"] = stage
    if status is not None:
        headers["X-LLM-Provider-Status"] = str(status)
    if provider_code is not None:
        headers["X-LLM-Provider-Code"] = provider_code
    if provider_type is not None:
        headers["X-LLM-Provider-Type"] = provider_type
    if provider_param is not None:
        headers["X-LLM-Provider-Param"] = provider_param
    if provider_request_id is not None:
        headers["X-LLM-Provider-Request-ID"] = provider_request_id
    return headers
