"""Regression coverage for provider failures and strict v3 JSON in both modes."""

import copy
import http.client
import json
import os
import unittest
import urllib.error
from unittest.mock import Mock, patch

from app.v3_api import SESSIONS
from . import test_v3_error_transport as transport_tests
from .test_v3_error_transport import Response
from v3.engine import check_output, rubrics, schema_for


class LLMValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = transport_tests.ErrorTransportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = self.fixture.client
        self.sid = self.fixture.sid
        self.card_id = self.fixture.card_id
        self.ids = self.fixture.ids
        self.timeout = patch.dict(os.environ, {"LLM_TIMEOUT_SECONDS": "75"})
        self.timeout.start()
        self.addCleanup(self.timeout.stop)
        self.fixture.answer(self.fixture.output([2, 2, 2, 0, 0]))
        self.before = copy.deepcopy(SESSIONS[self.sid].__dict__)

    def request(self, response=None, exception=None, path="/v3/session/answer"):
        payload = (
            {"session_id": self.sid}
            if path.endswith("/answer")
            else {"card_id": self.card_id}
        )
        payload["candidate_answer"] = "new explanation; incorrect claim"
        kwargs = (
            {"side_effect": exception}
            if exception is not None
            else {"return_value": response}
        )
        with patch("urllib.request.urlopen", **kwargs) as transport:
            result = self.client.post(path, json=payload)
        return result, transport

    def raw(self, model_json, **choice_fields):
        envelope = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": model_json},
                    **choice_fields,
                }
            ]
        }
        return Response(json.dumps(envelope).encode())

    def assert_failed(self, result):
        self.assertEqual(result.status_code, 502)
        self.assertEqual(set(result.json()), {"detail"})
        self.assertNotIn("score", result.json())
        self.assertEqual(SESSIONS[self.sid].__dict__, self.before)

    def test_http_errors_are_controlled_and_never_read_provider_error_body(self):
        for status in (400, 401, 403, 429, 500, 502, 503):
            with self.subTest(status=status):
                body = Mock()
                body.read.return_value = b"FAKE_SECRET_AND_INTERNAL_PROMPT"
                error = urllib.error.HTTPError(
                    "https://provider.invalid",
                    status,
                    "FAKE_SECRET_AND_INTERNAL_PROMPT",
                    {},
                    body,
                )
                result, _ = self.request(exception=error)
                self.assert_failed(result)
                self.assertNotIn("FAKE_SECRET", result.text)
                body.read.assert_called_once_with(8192)

    def test_timeout_connection_and_incomplete_http_errors_preserve_session(self):
        errors = (
            TimeoutError("private"),
            urllib.error.URLError("private"),
            ConnectionResetError("private"),
            http.client.IncompleteRead(b"private", 20),
            http.client.BadStatusLine("private"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                result, _ = self.request(exception=error)
                self.assert_failed(result)
                self.assertNotIn("private", result.text)

    def test_finish_reason_must_indicate_a_complete_text_response(self):
        output = json.dumps(self.fixture.output([0, 0, 0, 0, 0]))
        for reason in (
            "length",
            "content_filter",
            "tool_calls",
            "function_call",
            "unexpected",
            3,
            False,
            [],
        ):
            with self.subTest(reason=reason):
                result, _ = self.request(self.raw(output, finish_reason=reason))
                self.assert_failed(result)

    def test_unexpected_envelopes_and_refusal_types_are_controlled(self):
        output = json.dumps(self.fixture.output([0, 0, 0, 0, 0]))
        envelopes = [
            None,
            [],
            {"choices": "text"},
            {"choices": [None]},
            {"choices": [{"message": []}]},
            {"choices": [{"message": {"content": {"wrong": "type"}}}]},
            {"choices": [{"message": {"role": "tool", "content": output}}]},
        ]
        for refusal in (True, 7, ["private"], {"reason": "private"}):
            envelopes.append(
                {"choices": [{"message": {"content": output, "refusal": refusal}}]}
            )
        for envelope in envelopes:
            with self.subTest(envelope=envelope):
                result, _ = self.request(Response(json.dumps(envelope).encode()))
                self.assert_failed(result)

    def test_duplicate_keys_are_rejected_in_envelope_and_model_content(self):
        output = json.dumps(self.fixture.output([0, 0, 0, 0, 0]))
        duplicate = output.replace(
            '"summary": "Test."', '"summary": "first", "summary": "Test."'
        )
        result, _ = self.request(self.raw(duplicate))
        self.assert_failed(result)
        valid_choices = json.dumps([{"message": {"content": output}}])
        result, _ = self.request(
            Response(('{"choices":[],"choices":' + valid_choices + "}").encode())
        )
        self.assert_failed(result)

    def test_nonstandard_json_numbers_are_rejected_even_in_unused_envelope_fields(self):
        choices = json.dumps(
            [{"message": {"content": json.dumps(self.fixture.output([0, 0, 0, 0, 0]))}}]
        )
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                body = '{"usage":' + token + ',"choices":' + choices + "}"
                result, _ = self.request(Response(body.encode()))
                self.assert_failed(result)

    def test_current_schema_requires_both_service_arrays_in_both_modes(self):
        for mode in ("schema", "object"):
            for missing in ("error_updates", "resolutions"):
                with (
                    self.subTest(mode=mode, missing=missing),
                    patch.dict(os.environ, {"LLM_JSON_MODE": mode}),
                ):
                    output = self.fixture.output([0, 0, 0, 0, 0])
                    del output[missing]
                    with self.assertRaises(ValueError):
                        check_output(self.card_id, "new explanation", output)
                    result, _ = self.request(self.raw(json.dumps(output)))
                    self.assert_failed(result)

    def test_nested_types_enums_and_extra_fields_are_checked_in_both_modes(self):
        for mode in ("schema", "object"):
            mutations = (
                lambda x: x.update(error_updates=None),
                lambda x: x.update(resolutions={}),
                lambda x: x.update(uncertainty="certain"),
                lambda x: x.update(abstained="false"),
                lambda x: x.update(extra="private"),
                lambda x: x["criteria"][self.ids[0]].update(points=True),
                lambda x: x["criteria"][self.ids[0]].update(points=2.0),
                lambda x: x["criteria"][self.ids[0]].update(points=3),
                lambda x: x["criteria"][self.ids[0]].update(reason=None),
                lambda x: x["criteria"][self.ids[0]].update(extra="private"),
                lambda x: x["criteria"].update(
                    OTHER_CARD={"points": 0, "quote": "", "reason": ""}
                ),
            )
            for index, mutate in enumerate(mutations):
                with (
                    self.subTest(mode=mode, mutation=index),
                    patch.dict(os.environ, {"LLM_JSON_MODE": mode}),
                ):
                    output = self.fixture.output([0, 0, 0, 0, 0])
                    mutate(output)
                    result, _ = self.request(self.raw(json.dumps(output)))
                    self.assert_failed(result)

    def test_service_metadata_is_validated_even_if_an_evidence_quote_is_invalid(self):
        output = self.fixture.output([2, 0, 0, 0, 0])
        output["criteria"][self.ids[0]]["quote"] = "not in answer"
        output["error_updates"] = {"incorrect": "array type"}
        with self.assertRaises(ValueError):
            check_output(self.card_id, "new explanation", output)

    def test_local_validation_uses_the_generated_schema(self):
        schema = copy.deepcopy(schema_for(self.card_id))
        schema["properties"]["summary"]["enum"] = ["approved"]
        with patch("v3.engine.schema_for", return_value=schema):
            with self.assertRaises(ValueError):
                check_output(
                    self.card_id,
                    "new explanation",
                    self.fixture.output([0, 0, 0, 0, 0]),
                )

    def test_invalid_evidence_is_not_committed_as_a_session_turn(self):
        output = self.fixture.output([2, 0, 0, 0, 0])
        output["criteria"][self.ids[0]]["quote"] = "fabricated quotation"
        result, _ = self.request(self.raw(json.dumps(output)))
        self.assert_failed(result)

    def test_refusal_preserves_the_pending_question_and_all_session_state(self):
        refusal = Response(b'{"choices":[{"message":{"refusal":"private refusal"}}]}')
        result, _ = self.request(refusal)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            set(result.json()), {"session_id", "status", "human_review_required"}
        )
        self.assertEqual(result.json()["status"], "needs_review")
        self.assertEqual(SESSIONS[self.sid].__dict__, self.before)
        retry, _ = self.request(
            self.fixture.provider(self.fixture.output([0, 0, 0, 2, 0]))
        )
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["cumulative_score"], 8)

    def test_model_abstention_is_not_a_completed_turn_or_zero_knowledge_score(self):
        output = self.fixture.output([0, 0, 0, 0, 0])
        output["abstained"] = True
        result, _ = self.request(self.fixture.provider(output))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "needs_review")
        self.assertEqual(SESSIONS[self.sid].__dict__, self.before)
        result, _ = self.request(self.fixture.provider(output), path="/v3/evaluate")
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()["score"])
        self.assertTrue(result.json()["needs_review"])

    def test_exception_text_is_never_echoed_by_evaluation_routes(self):
        marker = "FAKE_API_KEY_AND_INTERNAL_PROMPT"
        for path in ("/v3/evaluate", "/v3/session/answer"):
            with (
                self.subTest(path=path),
                patch("app.v3_api.evaluate_live", side_effect=RuntimeError(marker)),
            ):
                payload = {"candidate_answer": "new explanation"}
                payload.update(
                    {"session_id": self.sid}
                    if path.endswith("/answer")
                    else {"card_id": self.card_id}
                )
                result = self.client.post(path, json=payload)
                self.assert_failed(result)
                self.assertNotIn(marker, result.text)

    def test_whitespace_answers_are_request_errors_without_a_provider_call(self):
        for path in ("/v3/prepare", "/v3/evaluate", "/v3/session/answer"):
            with self.subTest(path=path), patch("urllib.request.urlopen") as transport:
                payload = {"candidate_answer": " \t\n "}
                payload.update(
                    {"session_id": self.sid}
                    if path.endswith("/answer")
                    else {"card_id": self.card_id}
                )
                result = self.client.post(path, json=payload)
                self.assertEqual(result.status_code, 422)
                transport.assert_not_called()
                self.assertEqual(SESSIONS[self.sid].__dict__, self.before)

    def test_invalid_provider_settings_fail_before_network_access(self):
        settings = (
            {"LLM_JSON_MODE": "typo"},
            {"LLM_MESSAGE_MODE": "typo"},
            {"LLM_PIPELINE_MODE": "typo"},
            {"LLM_TIMEOUT_SECONDS": "private"},
            {"LLM_TIMEOUT_SECONDS": "0"},
            {"LLM_TIMEOUT_SECONDS": "-1"},
        )
        for setting in settings:
            with self.subTest(setting=setting), patch.dict(os.environ, setting):
                result, transport = self.request(
                    self.fixture.provider(self.fixture.output([0, 0, 0, 0, 0]))
                )
                self.assert_failed(result)
                transport.assert_not_called()

    def test_mode_normalization_and_system_user_messages(self):
        for mode in ("schema", "object", " SCHEMA ", " OBJECT "):
            with (
                self.subTest(mode=mode),
                patch.dict(
                    os.environ,
                    {"LLM_JSON_MODE": mode, "LLM_MESSAGE_MODE": "system_user"},
                ),
            ):
                result, transport = self.request(
                    self.fixture.provider(self.fixture.output([0, 0, 0, 0, 0])),
                    path="/v3/evaluate",
                )
                self.assertEqual(result.status_code, 200)
                payload = json.loads(transport.call_args.args[0].data)
                self.assertEqual(
                    [m["role"] for m in payload["messages"]], ["system", "user"]
                )
                self.assertEqual(
                    payload["response_format"]["type"],
                    "json_object"
                    if mode.strip().lower() == "object"
                    else "json_schema",
                )
                self.assertIn('"resolutions"', payload["messages"][0]["content"])

    def test_successful_responses_for_all_25_cards_in_both_modes(self):
        for mode in ("schema", "object"):
            for cid, rubric in rubrics().items():
                with (
                    self.subTest(mode=mode, card_id=cid),
                    patch.dict(os.environ, {"LLM_JSON_MODE": mode}),
                ):
                    output = self.fixture.output([0, 0, 0, 0, 0])
                    output["criteria"] = {
                        c["id"]: {"points": 0, "quote": "", "reason": "Not covered."}
                        for c in rubric["criteria"]
                    }
                    with patch(
                        "urllib.request.urlopen",
                        return_value=self.raw(json.dumps(output)),
                    ):
                        result = self.client.post(
                            "/v3/evaluate",
                            json={"card_id": cid, "candidate_answer": "I do not know."},
                        )
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json()["score"], 0)
                    self.assertFalse(result.json()["needs_review"])

    def test_criterion_correction_protocol_remains_valid_in_both_modes(self):
        for mode in ("schema", "object"):
            with (
                self.subTest(mode=mode),
                patch.dict(os.environ, {"LLM_JSON_MODE": mode}),
            ):
                sid = self.client.post(
                    "/v3/session/start", json={"card_id": self.card_id}
                ).json()["session_id"]
                self.addCleanup(SESSIONS.pop, sid, None)

                def send(output):
                    with patch(
                        "urllib.request.urlopen",
                        return_value=self.fixture.provider(output),
                    ):
                        return self.client.post(
                            "/v3/session/answer",
                            json={
                                "session_id": sid,
                                "candidate_answer": "new explanation; incorrect claim",
                            },
                        )

                self.assertEqual(
                    send(self.fixture.output([2, 2, 2, 0, 0])).status_code, 200
                )
                bad = self.fixture.output([0, 0, 0, 0, 0], wrong=True)
                bad["error_updates"] = [
                    {
                        "flag_index": 0,
                        "error_id": None,
                        "criterion_id": self.ids[1],
                        "reason": "Only this criterion is contradicted.",
                    }
                ]
                self.assertEqual(send(bad).json()["cumulative_score"], 4)
                error_id = SESSIONS[sid].unresolved_errors[0]["error_id"]
                corrected = self.fixture.output([0, 1, 0, 2, 1])
                corrected["resolutions"] = [
                    {
                        "error_id": error_id,
                        "criterion_id": self.ids[1],
                        "quote": "new explanation",
                        "reason": "The claim is explicitly corrected.",
                    }
                ]
                result = send(corrected)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["cumulative_score"], 8)
                self.assertEqual(result.json()["action"], "next_topic")


if __name__ == "__main__":
    unittest.main()
