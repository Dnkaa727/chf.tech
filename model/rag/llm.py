"""OpenAI-compatible evaluator: semantic segmentation + rubric scoring (two calls by default)."""

from __future__ import annotations
import json
import os
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from http.client import HTTPException

from .engine import (
    messages_for,
    schema_for,
    check_output,
    segmentation_messages_for,
    segmentation_schema_for,
    validate_segments,
    scoring_messages_for,
    scoring_schema_for,
    check_segmented_output,
)
from .json_validation import strict_json_loads, validate_schema
from .registry import get_registry
from .diagnostics import FailureDetail, EvaluationValidationError, safe_provider_token


class LLMError(RuntimeError):
    """Safe server-side error; never includes provider bodies or prompts."""

    default_code = "unexpected_error"

    def __init__(
        self,
        message,
        *,
        code=None,
        criterion_id=None,
        field=None,
        provider_status=None,
        stage=None,
        provider_error_code=None,
        provider_error_type=None,
        provider_param=None,
        provider_request_id=None,
    ):
        super().__init__(message)
        self.diagnostic = FailureDetail(
            code or self.default_code,
            criterion_id,
            field,
            provider_status,
            stage,
            safe_provider_token(provider_error_code),
            safe_provider_token(provider_error_type),
            safe_provider_token(provider_param),
            safe_provider_token(provider_request_id),
        )


class LLMConfigurationError(LLMError):
    default_code = "invalid_configuration"


class LLMProviderError(LLMError):
    default_code = "provider_unavailable"


class LLMResponseError(LLMError):
    default_code = "unexpected_response"


def _provider_messages(messages, message_mode):
    if message_mode == "system_user" and len(messages) >= 3:
        return [
            {
                "role": "system",
                "content": messages[0]["content"] + "\n" + messages[1]["content"],
            },
            messages[-1],
        ]
    return messages


def _provider_error_metadata(error):
    """Extract only safe allowlisted provider fields; never keep provider message/body."""
    try:
        payload = strict_json_loads(error.read(8192))
    except Exception:
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return {}
    detail = payload["error"]
    metadata = {}
    for source, target in (
        ("code", "provider_error_code"),
        ("type", "provider_error_type"),
        ("param", "provider_param"),
    ):
        token = safe_provider_token(detail.get(source))
        if token:
            metadata[target] = token
    try:
        request_id = error.headers.get("x-request-id") if error.headers else None
    except Exception:
        request_id = None
    if request_id:
        metadata["provider_request_id"] = safe_provider_token(request_id)
    return metadata


def _request_json(
    messages,
    schema,
    schema_name,
    *,
    model,
    base,
    api_key,
    timeout,
    json_mode,
    message_mode,
    stage=None,
):
    """Perform one provider request and return (parsed JSON object, refusal)."""
    provider_messages = _provider_messages(messages, message_mode)
    data = {
        "model": model,
        "messages": provider_messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
    }
    if json_mode == "object":
        data["response_format"] = {"type": "json_object"}
    try:
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(data, ensure_ascii=False).encode("utf8"),
            method="POST",
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
        )
    except (ValueError, TypeError):
        raise LLMConfigurationError("Invalid LLM request configuration") from None

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = strict_json_loads(response.read())
    except urllib.error.HTTPError as error:
        status = error.code if type(error.code) is int else None
        # Keep only provider error code/type/param/request-id; never expose its free-text message.
        metadata = _provider_error_metadata(error)
        raise LLMProviderError(
            "LLM provider HTTP error",
            code="provider_http_error",
            provider_status=status,
            stage=stage,
            **metadata,
        ) from None
    except TimeoutError:
        raise LLMProviderError(
            "LLM provider timeout", code="provider_timeout", stage=stage
        ) from None
    except urllib.error.URLError as error:
        code = (
            "provider_timeout"
            if isinstance(error.reason, TimeoutError)
            else "provider_unavailable"
        )
        raise LLMProviderError(
            "LLM provider unavailable", code=code, stage=stage
        ) from None
    except (OSError, HTTPException, OverflowError):
        raise LLMProviderError(
            "LLM provider unavailable or response interrupted", stage=stage
        ) from None
    except (ValueError, TypeError, RecursionError):
        raise LLMResponseError(
            "LLM provider returned invalid JSON",
            code="invalid_json",
            field="response_envelope",
            stage=stage,
        ) from None

    try:
        if not isinstance(body, dict) or body.get("error") is not None:
            raise ValueError("Invalid response envelope")
        choices = body.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise ValueError("Expected a nonempty choices array")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish not in (None, "stop", "content_filter"):
            raise LLMResponseError(
                "Incomplete or unsupported completion", code="incomplete_response"
            )
        msg = choice["message"]
        if not isinstance(msg, dict):
            raise ValueError("Expected a message object")
        if msg.get("role", "assistant") != "assistant":
            raise ValueError("Unexpected message role")
        refusal = msg.get("refusal")
        if refusal is not None and not isinstance(refusal, str):
            raise ValueError("Invalid refusal type")
        if refusal and refusal.strip():
            return None, True
        if finish == "content_filter":
            raise LLMResponseError(
                "No assessable completion", code="incomplete_response"
            )
        content = msg["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Expected JSON text")
        try:
            output = strict_json_loads(content)
        except ValueError:
            raise LLMResponseError(
                "Invalid completion JSON", code="invalid_json", field="message_content"
            ) from None
        try:
            validate_schema(output, schema)
        except EvaluationValidationError as error:
            detail = error.diagnostic
            raise LLMResponseError(
                "LLM response schema validation failed",
                code=detail.code,
                criterion_id=detail.criterion_id,
                field=detail.field,
                stage=stage,
            ) from None
        return output, False
    except LLMError:
        raise
    except (ValueError, KeyError, TypeError, IndexError, RecursionError):
        raise LLMResponseError(
            "LLM provider returned an unexpected response envelope", stage=stage
        ) from None


def _refusal_result(card_id):
    return {
        "card_id": card_id,
        "needs_review": True,
        "refusal": True,
        "human_review_required": True,
        "score": None,
        "criteria": {},
        "red_flags": [],
        "warnings": ["Model refused"],
    }


def _validate_base_url(base):
    """Only exact loopback hosts may use HTTP; credentials belong in headers."""
    parts = urlsplit(base)
    # Accessing port validates both syntax and range.
    port = parts.port
    if (
        not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or any(char.isspace() for char in base)
        or (port is not None and port == 0)
    ):
        raise ValueError("Invalid endpoint")
    if parts.scheme == "https":
        return
    if parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1"):
        return
    raise ValueError("Invalid endpoint")


def evaluate_live(
    card_id, answer, question=None, history=None, error_context=None, *, rubric=None
):
    try:
        api_key = (
            os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        ).strip()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
        base = (
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        )
        json_mode = os.getenv("LLM_JSON_MODE", "schema").strip().casefold()
        message_mode = (
            os.getenv("LLM_MESSAGE_MODE", "system_user").strip().casefold()
            or "developer"
        )
        pipeline_mode = (
            os.getenv("LLM_PIPELINE_MODE", "two_stage").strip().casefold()
            or "two_stage"
        )
        timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "75"))
        if (
            not api_key
            or not model
            or not 0 < timeout <= 2**31 - 1
            or json_mode not in ("schema", "object")
            or message_mode not in ("developer", "system_user")
            or pipeline_mode not in ("two_stage", "one_stage")
        ):
            raise ValueError("Invalid configuration")
        _validate_base_url(base)
    except (ValueError, TypeError, OverflowError):
        raise LLMConfigurationError("Invalid LLM configuration") from None

    selected = rubric if rubric is not None else get_registry().get(card_id).rubric

    if pipeline_mode == "one_stage":
        schema = schema_for(card_id, rubric=selected)
        messages = messages_for(
            card_id,
            answer,
            question,
            history,
            error_context=error_context,
            rubric=selected,
            output_schema=schema,
        )
        output, refused = _request_json(
            messages,
            schema,
            "backend_eval_v3",
            model=model,
            base=base,
            api_key=api_key,
            timeout=timeout,
            json_mode=json_mode,
            message_mode=message_mode,
            stage="evaluation",
        )
        if refused:
            return _refusal_result(card_id)
        try:
            result = check_output(
                card_id,
                answer,
                output,
                error_context=error_context,
                rubric=selected,
                output_schema=schema,
                strict_evidence=True,
            )
        except EvaluationValidationError as error:
            detail = error.diagnostic
            raise LLMResponseError(
                "LLM response validation failed",
                code=detail.code,
                criterion_id=detail.criterion_id,
                field=detail.field,
                stage="evaluation",
            ) from None
        if result["warnings"]:
            raise LLMResponseError(
                "Evidence validation failed", code="invalid_quote", stage="evaluation"
            )
        return result

    # Stage 1: LLM performs semantic segmentation + routing. Python assigns IDs and
    # records whether each LLM fragment could be aligned to the source text.
    segmentation_schema = segmentation_schema_for(card_id, rubric=selected)
    segmentation_messages = segmentation_messages_for(
        card_id,
        answer,
        question,
        history,
        rubric=selected,
    )
    raw_segments, refused = _request_json(
        segmentation_messages,
        segmentation_schema,
        "backend_semantic_segments_v1",
        model=model,
        base=base,
        api_key=api_key,
        timeout=timeout,
        json_mode=json_mode,
        message_mode=message_mode,
        stage="segmentation",
    )
    if refused:
        return _refusal_result(card_id)
    try:
        segments = validate_segments(card_id, answer, raw_segments, rubric=selected)
    except EvaluationValidationError as error:
        detail = error.diagnostic
        raise LLMResponseError(
            "Semantic segmentation validation failed",
            code=detail.code,
            criterion_id=detail.criterion_id,
            field=detail.field,
            stage="segmentation",
        ) from None

    # Stage 2: score every routed segment. The model returns fixed segment-ID keys,
    # never free-form quotes or arrays that can omit/duplicate an ID.
    scoring_schema = scoring_schema_for(card_id, segments, rubric=selected)
    scoring_messages = scoring_messages_for(
        card_id,
        answer,
        segments,
        question,
        history,
        error_context,
        rubric=selected,
        output_schema=scoring_schema,
    )
    raw_score, refused = _request_json(
        scoring_messages,
        scoring_schema,
        "backend_rubric_score_v2",
        model=model,
        base=base,
        api_key=api_key,
        timeout=timeout,
        json_mode=json_mode,
        message_mode=message_mode,
        stage="scoring",
    )
    if refused:
        return _refusal_result(card_id)
    try:
        return check_segmented_output(
            card_id,
            answer,
            segments,
            raw_score,
            error_context=error_context,
            rubric=selected,
            output_schema=scoring_schema,
        )
    except EvaluationValidationError as error:
        detail = error.diagnostic
        raise LLMResponseError(
            "Segmented evaluation validation failed",
            code=detail.code,
            criterion_id=detail.criterion_id,
            field=detail.field,
            stage="scoring",
        ) from None
