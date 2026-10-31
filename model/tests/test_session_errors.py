"""Criterion-level revisions with synthetic assessments and no model calls."""

import copy
import json
import unittest

from rag.engine import (
    TopicSession,
    cases,
    check_output,
    messages_for,
    rubrics,
    schema_for,
)


class SessionErrorTests(unittest.TestCase):
    card_id = "PY-ASYNC-01"
    explanations = (
        "time.sleep blocks the thread running the event loop.",
        "await asyncio.sleep yields control while waiting.",
        "Synchronous requests blocks too; use an async client or a thread.",
        "CPU-bound work needs a process rather than an extra await.",
        "Concurrent latency and loop lag measurements expose blocking.",
    )
    error_quote = "time.sleep never blocks the event loop."
    response_keys = {
        "session_id",
        "card_id",
        "action",
        "next_question",
        "target",
        "latest_score",
        "cumulative_score",
        "followups_asked",
        "status",
        "human_review_required",
    }

    def setUp(self):
        self.ids = [c["id"] for c in rubrics()[self.card_id]["criteria"]]

    def output(self, points, flags=(), updates=None, resolutions=(), error_quote=None):
        quote = error_quote or self.error_quote
        answer = (
            " ".join(
                [t for t, p in zip(self.explanations, points) if p]
                + ([quote] if flags else [])
            )
            or "I do not know yet."
        )
        data = {
            "criteria": {
                cid: {
                    "points": p,
                    "quote": text if p else "",
                    "reason": "Synthetic semantic assessment.",
                }
                for cid, p, text in zip(self.ids, points, self.explanations)
            },
            "red_flags": [
                {"id": f, "quote": quote, "reason": "Incorrect technical claim."}
                for f in flags
            ],
            "uncertainty": "low",
            "abstained": False,
            "summary": "Test.",
            "error_updates": updates or [],
            "resolutions": list(resolutions),
        }
        return answer, data

    def link(self, index=0, criterion=1, error_id=None):
        return {
            "flag_index": index,
            "error_id": error_id,
            "criterion_id": self.ids[criterion] if criterion is not None else None,
            "reason": "The quoted incorrect claim affects this aspect of the rubric.",
        }

    def resolution(self, error_id, criterion=1):
        return {
            "error_id": error_id,
            "criterion_id": self.ids[criterion],
            "quote": self.explanations[criterion],
            "reason": "The new explanation replaces the earlier incorrect claim.",
        }

    def record(self, session, points, **kwargs):
        answer, data = self.output(points, **kwargs)
        assessment = check_output(
            self.card_id, answer, data, error_context=session.evaluation_context()
        )
        return session.add_assessment(answer, assessment)

    def open_known_error(self, session):
        self.record(session, [2, 2, 2, 0, 0])
        result = self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link()],
        )
        return result, session.unresolved_errors[0]["error_id"]

    def test_known_error_revises_only_the_affected_criterion(self):
        session = TopicSession(self.card_id)
        result, _ = self.open_known_error(session)
        self.assertEqual(result["cumulative_score"], 4)
        self.assertEqual(
            [v["points"] for v in session.criterion_evidence.values()], [2, 0, 2, 0, 0]
        )
        self.assertEqual(result["target"], self.ids[1])
        self.assertTrue(session.criterion_evidence[self.ids[1]]["disputed_by"])

    def test_unknown_error_preserves_points_and_stays_provisional(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0])
        result = self.record(
            session, [0, 0, 0, 0, 0], flags=["technical_contradiction"]
        )
        self.assertEqual(result["cumulative_score"], 6)
        self.assertEqual(session.assessment_status, "provisional")
        self.assertIsNone(session.unresolved_errors[0]["criterion_id"])

    def test_unknown_error_is_not_lost_when_score_reaches_eight(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0], flags=["technical_contradiction"])
        result = self.record(session, [0, 0, 0, 2, 0])
        self.assertEqual(result["cumulative_score"], 8)
        self.assertEqual(result["action"], "followup")
        result = self.record(session, [0, 0, 0, 0, 0])
        self.assertEqual(result["action"], "needs_review")
        self.assertEqual(result["cumulative_score"], 8)

    def test_known_error_can_be_fixed_with_one_point_and_finish_at_eight(self):
        session = TopicSession(self.card_id)
        _, error_id = self.open_known_error(session)
        result = self.record(
            session, [0, 1, 0, 2, 1], resolutions=[self.resolution(error_id)]
        )
        self.assertEqual(result["action"], "next_topic")
        self.assertEqual(result["cumulative_score"], 8)
        self.assertEqual(session.criterion_evidence[self.ids[1]]["points"], 1)
        self.assertFalse(session.unresolved_errors)
        self.assertEqual(session.assessment_status, "confirmed")
        self.assertEqual(set(result), self.response_keys)

    def test_high_score_and_absence_of_flags_do_not_resolve_an_error(self):
        session = TopicSession(self.card_id)
        self.record(
            session,
            [2, 0, 2, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link()],
        )
        result = self.record(session, [2, 2, 2, 2, 2])
        self.assertEqual(result["cumulative_score"], 8)
        self.assertEqual(result["action"], "followup")
        self.assertTrue(session.unresolved_errors)
        self.assertEqual(session.criterion_evidence[self.ids[1]]["points"], 0)

    def test_known_unresolved_error_requires_review_after_two_followups(self):
        session = TopicSession(self.card_id)
        self.open_known_error(session)
        result = self.record(session, [0, 0, 0, 2, 2])
        self.assertEqual(result["action"], "needs_review")
        self.assertEqual(result["followups_asked"], 2)

    def test_duplicate_flags_and_repeated_claim_share_one_error(self):
        session = TopicSession(self.card_id)
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction", "confidently_incorrect"],
            updates=[self.link(0), self.link(1)],
        )
        self.assertEqual(len(session.errors), 1)
        error_id = session.errors[0]["error_id"]
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link()],
        )
        self.assertEqual(len(session.errors), 1)
        self.assertEqual(session.errors[0]["error_id"], error_id)

    def test_semantically_repeated_claim_reuses_error_id(self):
        session = TopicSession(self.card_id)
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link()],
        )
        error_id = session.errors[0]["error_id"]
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["confidently_incorrect"],
            error_quote="Sleeping synchronously cannot delay any async request.",
            updates=[self.link(error_id=error_id)],
        )
        self.assertEqual(len(session.errors), 1)
        self.assertEqual(session.errors[0]["error_id"], error_id)

    def test_unknown_error_can_be_scoped_when_it_is_repeated(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0], flags=["technical_contradiction"])
        error_id = session.errors[0]["error_id"]
        result = self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link(error_id=error_id)],
        )
        self.assertEqual(len(session.errors), 1)
        self.assertEqual(result["cumulative_score"], 4)
        self.assertEqual(session.errors[0]["criterion_id"], self.ids[1])

    def test_unknown_error_can_be_scoped_and_explicitly_corrected(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0], flags=["technical_contradiction"])
        error_id = session.errors[0]["error_id"]
        result = self.record(
            session, [0, 1, 0, 2, 1], resolutions=[self.resolution(error_id)]
        )
        self.assertEqual(result["cumulative_score"], 8)
        self.assertEqual(result["action"], "next_topic")
        self.assertEqual(session.errors[0]["criterion_id"], self.ids[1])

    def test_unknown_error_can_expand_to_two_related_criteria(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0], flags=["technical_contradiction"])
        error_id = session.errors[0]["error_id"]
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[
                self.link(criterion=1, error_id=error_id),
                self.link(criterion=3, error_id=error_id),
            ],
        )
        self.assertEqual(len(session.errors), 2)
        self.assertEqual(
            {e["criterion_id"] for e in session.errors}, {self.ids[1], self.ids[3]}
        )
        self.assertEqual(len({e["group_id"] for e in session.errors}), 1)
        self.assertIn(error_id, {e["error_id"] for e in session.errors})

    def test_each_significant_flag_can_lower_only_its_criterion_to_one(self):
        for flag in (
            "technical_contradiction",
            "confidently_incorrect",
            "unsupported_remedy",
        ):
            with self.subTest(flag=flag):
                session = TopicSession(self.card_id)
                self.record(session, [2, 2, 2, 0, 0])
                result = self.record(
                    session, [0, 1, 0, 0, 0], flags=[flag], updates=[self.link()]
                )
                self.assertEqual(result["cumulative_score"], 5)
                self.assertEqual(
                    [v["points"] for v in session.criterion_evidence.values()],
                    [2, 1, 2, 0, 0],
                )

    def test_partial_correction_does_not_close_other_affected_criteria(self):
        session = TopicSession(self.card_id)
        self.record(
            session,
            [2, 0, 2, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link(criterion=1), self.link(criterion=3)],
        )
        errors = {e["criterion_id"]: e for e in session.errors}
        self.assertEqual(len({e["group_id"] for e in session.errors}), 1)
        result = self.record(
            session,
            [0, 1, 0, 0, 0],
            resolutions=[self.resolution(errors[self.ids[1]]["error_id"])],
        )
        self.assertEqual(result["action"], "followup")
        self.assertEqual(
            [e["criterion_id"] for e in session.unresolved_errors], [self.ids[3]]
        )
        self.assertEqual(result["target"], self.ids[3])

    def test_distinct_errors_on_one_criterion_must_be_resolved_individually(self):
        session = TopicSession(self.card_id)
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link()],
        )
        first_id = session.errors[0]["error_id"]
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            error_quote="An async sleep occupies the CPU for the whole delay.",
            updates=[self.link()],
        )
        self.assertEqual(len(session.errors), 2)
        result = self.record(
            session, [2, 2, 2, 2, 2], resolutions=[self.resolution(first_id)]
        )
        self.assertEqual(result["action"], "needs_review")
        self.assertEqual(len(session.unresolved_errors), 1)

    def test_error_can_reopen_without_creating_a_new_independent_record(self):
        session = TopicSession(self.card_id)
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link()],
        )
        error_id = session.errors[0]["error_id"]
        self.record(session, [0, 1, 0, 0, 0], resolutions=[self.resolution(error_id)])
        result = self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link(error_id=error_id)],
        )
        self.assertEqual(len(session.errors), 1)
        self.assertEqual(result["action"], "needs_review")
        self.assertEqual(session.criterion_evidence[self.ids[1]]["points"], 0)

    def test_revision_keeps_old_evidence_and_does_not_mutate_assessments(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0])
        original = copy.deepcopy(session.history[0]["assessment"])
        self.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.link()],
        )
        evidence = session.criterion_evidence[self.ids[1]]
        self.assertEqual(session.history[0]["assessment"], original)
        self.assertTrue(evidence["revisions"])
        self.assertTrue(any(e["points"] == 2 for e in evidence["evidence"]))

    def test_no_error_keeps_normal_accumulation_and_threshold_eight(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0])
        result = self.record(session, [0, 0, 0, 2, 0])
        self.assertEqual(result["action"], "next_topic")
        self.assertEqual(result["cumulative_score"], 8)

    def test_no_error_still_ends_as_insufficient_evidence(self):
        session = TopicSession(self.card_id)
        results = [self.record(session, [0, 0, 0, 0, 0]) for _ in range(3)]
        self.assertEqual(
            [r["action"] for r in results],
            ["followup", "followup", "insufficient_evidence"],
        )

    def test_invalid_internal_update_cannot_mutate_session(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0])
        before = copy.deepcopy(session.__dict__)
        answer, data = self.output([0, 0, 0, 0, 0], flags=["technical_contradiction"])
        assessment = check_output(self.card_id, answer, data)
        assessment["_error_updates"] = [self.link(error_id="not-a-real-error")]
        with self.assertRaises(ValueError):
            session.add_assessment(answer, assessment)
        self.assertEqual(session.__dict__, before)

    def test_untrusted_result_does_not_replace_candidate_knowledge_with_zero(self):
        session = TopicSession(self.card_id)
        self.record(session, [2, 2, 2, 0, 0])
        answer, data = self.output([0, 0, 0, 0, 0])
        data["uncertainty"] = "high"
        result = session.add_assessment(
            answer, check_output(self.card_id, answer, data)
        )
        self.assertEqual(result["cumulative_score"], 6)
        self.assertIsNone(result["latest_score"])
        self.assertEqual(result["action"], "needs_review")

    def test_unknown_legacy_errors_remain_open_even_after_a_full_answer(self):
        session = TopicSession(self.card_id)
        answer, data = self.output([0, 0, 0, 0, 0], flags=["technical_contradiction"])
        del data["error_updates"], data["resolutions"]
        session.add_assessment(
            answer, check_output(self.card_id, answer, data, allow_legacy=True)
        )
        result = self.record(session, [2, 2, 2, 2, 2])
        self.assertEqual(result["cumulative_score"], 10)
        self.assertEqual(result["action"], "followup")
        self.assertTrue(session.unresolved_errors)

    def test_successful_partial_correction_works_for_all_25_cards(self):
        samples = {(c["card_id"], c["kind"]): c for c in cases()}
        for card_id, rubric in rubrics().items():
            with self.subTest(card_id=card_id):
                session = TopicSession(card_id)
                ids = [c["id"] for c in rubric["criteria"]]
                sample = samples[card_id, "excellent"]["answer"]

                def assessment(points, flags=(), updates=(), resolutions=()):
                    data = {
                        "criteria": {
                            cid: {
                                "points": p,
                                "quote": sample if p else "",
                                "reason": "Synthetic semantic assessment.",
                            }
                            for cid, p in zip(ids, points)
                        },
                        "red_flags": list(flags),
                        "uncertainty": "low",
                        "abstained": False,
                        "summary": "Test.",
                        "error_updates": list(updates),
                        "resolutions": list(resolutions),
                    }
                    return check_output(
                        card_id,
                        sample,
                        data,
                        error_context=session.evaluation_context(),
                    )

                session.add_assessment(sample, assessment([2, 2, 2, 0, 0]))
                session.add_assessment(
                    sample,
                    assessment(
                        [0, 0, 0, 0, 0],
                        [
                            {
                                "id": "technical_contradiction",
                                "quote": sample,
                                "reason": "Test error.",
                            }
                        ],
                        [
                            {
                                "flag_index": 0,
                                "error_id": None,
                                "criterion_id": ids[1],
                                "reason": "This criterion is affected.",
                            }
                        ],
                    ),
                )
                error_id = session.errors[0]["error_id"]
                result = session.add_assessment(
                    sample,
                    assessment(
                        [0, 1, 0, 2, 1],
                        resolutions=[
                            {
                                "error_id": error_id,
                                "criterion_id": ids[1],
                                "quote": sample,
                                "reason": "The error is corrected; the aspect is partially covered.",
                            }
                        ],
                    ),
                )
                self.assertEqual(result["action"], "next_topic")
                self.assertEqual(result["cumulative_score"], 8)
                self.assertEqual(set(result), self.response_keys)


class ErrorValidationTests(unittest.TestCase):
    def setUp(self):
        self.helper = SessionErrorTests()
        self.helper.setUp()
        self.card_id = self.helper.card_id

    def test_schema_and_prompt_describe_error_links_and_explicit_resolutions(self):
        schema = schema_for(self.card_id)
        self.assertIn("error_updates", schema["required"])
        self.assertIn("resolutions", schema["required"])
        session = TopicSession(self.card_id)
        self.helper.record(session, [0, 0, 0, 0, 0], flags=["technical_contradiction"])
        error_id = session.errors[0]["error_id"]
        messages = messages_for(
            self.card_id, "New answer.", error_context=session.evaluation_context()
        )
        self.assertIn(error_id, messages[1]["content"])
        self.assertIn("resolutions", messages[1]["content"])
        self.assertIn("не даёт баллов", messages[0]["content"])
        self.assertNotIn("error_updates", json.loads(messages[2]["content"]))

    def test_invalid_scope_or_missing_justification_is_rejected(self):
        for changes in (
            {"criterion_id": "OTHER-CARD-K1"},
            {"reason": ""},
            {"flag_index": 8},
            {"error_id": "unknown"},
            {"flag_index": True},
        ):
            with self.subTest(changes=changes):
                update = self.helper.link()
                update.update(changes)
                answer, data = self.helper.output(
                    [0, 0, 0, 0, 0], flags=["technical_contradiction"], updates=[update]
                )
                with self.assertRaises(ValueError):
                    check_output(self.card_id, answer, data)

    def test_resolution_needs_existing_id_quote_explanation_and_current_evidence(self):
        session = TopicSession(self.card_id)
        self.helper.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.helper.link()],
        )
        error_id = session.errors[0]["error_id"]
        for changes in (
            {"error_id": "unknown"},
            {"quote": "invented"},
            {"quote": ""},
            {"reason": ""},
            {"criterion_id": self.helper.ids[4]},
        ):
            with self.subTest(changes=changes):
                resolution = self.helper.resolution(error_id)
                resolution.update(changes)
                answer, data = self.helper.output(
                    [0, 1, 0, 0, 0], resolutions=[resolution]
                )
                with self.assertRaises(ValueError):
                    check_output(
                        self.card_id,
                        answer,
                        data,
                        error_context=session.evaluation_context(),
                    )
        answer, data = self.helper.output(
            [0, 0, 0, 0, 0], resolutions=[self.helper.resolution(error_id)]
        )
        with self.assertRaises(ValueError):
            check_output(
                self.card_id, answer, data, error_context=session.evaluation_context()
            )

    def test_resolution_cannot_coexist_with_a_new_error_on_same_criterion(self):
        session = TopicSession(self.card_id)
        self.helper.record(
            session,
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.helper.link()],
        )
        error_id = session.errors[0]["error_id"]
        answer, data = self.helper.output(
            [0, 1, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.helper.link(error_id=error_id)],
            resolutions=[self.helper.resolution(error_id)],
        )
        with self.assertRaises(ValueError):
            check_output(
                self.card_id, answer, data, error_context=session.evaluation_context()
            )

    def test_one_flag_cannot_have_both_unknown_and_known_scope(self):
        answer, data = self.helper.output(
            [0, 0, 0, 0, 0],
            flags=["technical_contradiction"],
            updates=[self.helper.link(criterion=None), self.helper.link(criterion=1)],
        )
        with self.assertRaises(ValueError):
            check_output(self.card_id, answer, data)


if __name__ == "__main__":
    unittest.main()
