"""Safe failure codes and correlated server logs, with no real provider calls."""

import copy
import json
import os
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from app.routes import SESSIONS
import test_error_transport as fixtures


class DiagnosticTests(unittest.TestCase):
    marker = "FAKE_SECRET_PROMPT_OR_CANDIDATE_TEXT"

    def setUp(self):
        self.fixture = fixtures.ErrorTransportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.answer(self.fixture.output([2, 2, 2, 0, 0]))
        self.sid = self.fixture.sid
        self.before = copy.deepcopy(SESSIONS[self.sid].__dict__)

    def request(
        self,
        *,
        output=None,
        raw=None,
        error=None,
        path="/api/session/answer",
        headers=None,
    ):
        if raw is not None:
            response = fixtures.Response(raw)
        else:
            response = self.fixture.provider(
                output or self.fixture.output([0, 0, 0, 0, 0])
            )
        kwargs = (
            {"side_effect": error} if error is not None else {"return_value": response}
        )
        payload = {
            "candidate_answer": "new explanation; incorrect claim; " + self.marker
        }
        payload.update(
            {"session_id": self.sid}
            if path.endswith("/answer")
            else {"card_id": self.fixture.card_id}
        )
        with patch("urllib.request.urlopen", **kwargs) as provider:
            result = self.fixture.client.post(path, json=payload, headers=headers or {})
        return result, provider

    def check_failure(self, expected, **kwargs):
        with self.assertLogs("rag.llm", level="WARNING") as captured:
            result, provider = self.request(**kwargs)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(
            result.json(),
            {"detail": "LLM evaluation failed. Retry or request human review."},
        )
        self.assertEqual(result.headers["x-llm-error-code"], expected)
        request_id = result.headers["x-request-id"]
        self.assertEqual(UUID(request_id).hex, request_id)
        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        record = json.loads(message.split("llm_evaluation_failed ", 1)[1])
        self.assertEqual(record["request_id"], request_id)
        self.assertEqual(record["code"], expected)
        self.assertEqual(
            set(record),
            {
                "request_id",
                "code",
                "card_id",
                "criterion_id",
                "field",
                "provider_status",
                "stage",
                "provider_error_code",
                "provider_error_type",
                "provider_param",
                "provider_request_id",
            },
        )
        self.assertIn(record["stage"], (None, "evaluation", "segmentation", "scoring"))
        self.assertNotIn(self.marker, message + result.text + str(result.headers))
        self.assertIsNone(captured.records[0].exc_info)
        self.assertEqual(SESSIONS[self.sid].__dict__, self.before)
        return result, provider, record

    def test_bad_quote_is_identified_without_logging_quote_or_answer(self):
        output = self.fixture.output([2, 0, 0, 0, 0])
        output["criteria"][self.fixture.ids[0]]["quote"] = (
            self.marker + " invented quote"
        )
        result, _, record = self.check_failure("invalid_quote", output=output)
        self.assertEqual(record["criterion_id"], self.fixture.ids[0])
        self.assertNotIn(self.fixture.ids[0], result.text + str(result.headers))

    def test_missing_service_field_is_identified_in_the_server_log(self):
        output = self.fixture.output([0, 0, 0, 0, 0])
        del output["resolutions"]
        _, _, record = self.check_failure("schema_mismatch", output=output)
        self.assertEqual(record["field"], "resolutions")

    def test_invalid_json_and_unexpected_envelope_have_distinct_codes(self):
        self.check_failure("invalid_json", raw=self.marker.encode())
        self.check_failure("unexpected_response", raw=b'{"choices":[]}')
        raw = json.dumps({"choices": [{"message": {"content": self.marker}}]}).encode()
        self.check_failure("invalid_json", raw=raw)

    def test_timeout_and_other_connection_failures_have_distinct_codes(self):
        self.check_failure("provider_timeout", error=TimeoutError(self.marker))
        self.check_failure(
            "provider_timeout", error=urllib.error.URLError(TimeoutError(self.marker))
        )
        self.check_failure(
            "provider_unavailable", error=ConnectionResetError(self.marker)
        )

    def test_http_error_body_read_is_bounded_and_never_logged(self):
        body = Mock()
        body.read.return_value = self.marker.encode()
        error = urllib.error.HTTPError(
            "https://invalid/" + self.marker, 429, self.marker, {}, body
        )
        result, _, record = self.check_failure("provider_http_error", error=error)
        self.assertEqual(result.headers["x-llm-provider-status"], "429")
        self.assertEqual(record["provider_status"], 429)
        self.assertEqual(record["stage"], "evaluation")
        body.read.assert_called_once_with(8192)
        for field in (
            "provider_error_code",
            "provider_error_type",
            "provider_param",
            "provider_request_id",
        ):
            self.assertIsNone(record[field])

    def test_structured_provider_metadata_is_kept_without_free_text(self):
        body = Mock()
        body.read.return_value = json.dumps(
            {
                "error": {
                    "code": "rate_limit_exceeded",
                    "type": "requests",
                    "param": "messages",
                    "message": self.marker,
                }
            }
        ).encode()
        error = urllib.error.HTTPError(
            "https://invalid", 429, self.marker, {"x-request-id": "req_test_123"}, body
        )
        result, _, record = self.check_failure("provider_http_error", error=error)
        self.assertEqual(record["provider_error_code"], "rate_limit_exceeded")
        self.assertEqual(record["provider_error_type"], "requests")
        self.assertEqual(record["provider_param"], "messages")
        self.assertEqual(record["provider_request_id"], "req_test_123")
        self.assertEqual(result.headers["x-llm-stage"], "evaluation")
        self.assertEqual(result.headers["x-llm-provider-request-id"], "req_test_123")

    def test_incomplete_generation_has_a_specific_code(self):
        raw = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": json.dumps(self.fixture.output([0, 0, 0, 0, 0]))
                        },
                    }
                ]
            }
        ).encode()
        self.check_failure("incomplete_response", raw=raw)

    def test_invalid_error_reference_is_distinct_from_invalid_json(self):
        output = self.fixture.output([0, 0, 0, 0, 0], wrong=True)
        output["error_updates"] = [
            {
                "flag_index": 0,
                "error_id": self.marker,
                "criterion_id": self.fixture.ids[0],
                "reason": self.marker,
            }
        ]
        self.check_failure("invalid_error_link", output=output)

    def test_invalid_configuration_is_identified_without_requesting_the_provider(self):
        with patch.dict(os.environ, {"LLM_JSON_MODE": self.marker}):
            _, provider, _ = self.check_failure("invalid_configuration")
        provider.assert_not_called()

    def test_generic_exceptions_never_expose_their_text_or_untrusted_attributes(self):
        error = RuntimeError(self.marker)
        error.diagnostic = SimpleNamespace(
            code=self.marker,
            criterion_id=self.marker,
            field=self.marker,
            provider_status=self.marker,
        )
        for path in ("/api/evaluate", "/api/session/answer"):
            with (
                self.subTest(path=path),
                patch("app.routes.evaluate_live", side_effect=error),
            ):
                self.check_failure("unexpected_error", path=path)

    def test_incoming_request_id_is_not_reused_or_logged(self):
        result, _, _ = self.check_failure(
            "provider_timeout",
            error=TimeoutError(),
            headers={"X-Request-ID": self.marker},
        )
        self.assertNotEqual(result.headers["x-request-id"], self.marker)

    def test_valid_zero_score_is_not_a_diagnostic_failure(self):
        result, _ = self.request(path="/api/evaluate")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["score"], 0)
        self.assertNotIn("x-llm-error-code", result.headers)


if __name__ == "__main__":
    unittest.main()
