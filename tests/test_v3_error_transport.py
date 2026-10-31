"""Exercise the real v3 adapter and ASGI routes with an in-memory provider."""
import copy
import json
import os
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.api import app
from app.v3_api import SESSIONS
from v3.engine import rubrics


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ErrorTransportTests(unittest.TestCase):
    card_id = 'PY-ASYNC-01'

    def setUp(self):
        self.client = TestClient(app)
        self.ids = [c['id'] for c in rubrics()[self.card_id]['criteria']]
        self.env = patch.dict(os.environ, {
            'LLM_API_KEY': 'FAKE_OFFLINE_TOKEN', 'LLM_MODEL': 'gpt-4o-mini',
            'LLM_BASE_URL': 'http://localhost:5005/v1',
            'LLM_JSON_MODE': 'schema', 'LLM_MESSAGE_MODE': 'developer',
            'LLM_PIPELINE_MODE': 'one_stage',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.sid = self.client.post('/v3/session/start', json={'card_id': self.card_id}).json()['session_id']
        self.addCleanup(SESSIONS.pop, self.sid, None)

    def output(self, points, wrong=False):
        return {
            'criteria': {cid: {'points': p, 'quote': 'new explanation' if p else '',
                               'reason': 'Synthetic semantic assessment.'}
                         for cid, p in zip(self.ids, points)},
            'red_flags': ([{'id': 'technical_contradiction', 'quote': 'incorrect claim',
                            'reason': 'Technical error.'}] if wrong else []),
            'uncertainty': 'low', 'abstained': False, 'summary': 'Test.',
            'error_updates': [], 'resolutions': [],
        }

    def provider(self, output):
        return Response(json.dumps({'choices': [{'message': {
            'content': json.dumps(output)}}]}).encode())

    def answer(self, output):
        with patch('urllib.request.urlopen', return_value=self.provider(output)):
            return self.client.post('/v3/session/answer', json={
                'session_id': self.sid, 'candidate_answer': 'new explanation; incorrect claim'})

    def test_real_adapter_carries_error_context_and_finishes_at_eight(self):
        self.assertEqual(self.answer(self.output([2, 2, 2, 0, 0])).status_code, 200)
        bad = self.output([0, 0, 0, 0, 0], wrong=True)
        bad['error_updates'] = [{'flag_index': 0, 'error_id': None,
                                 'criterion_id': self.ids[1], 'reason': 'This aspect is false.'}]
        self.assertEqual(self.answer(bad).json()['cumulative_score'], 4)
        error_id = SESSIONS[self.sid].unresolved_errors[0]['error_id']
        fixed = self.output([0, 1, 0, 2, 1])
        fixed['resolutions'] = [{'error_id': error_id, 'criterion_id': self.ids[1],
                                 'quote': 'new explanation', 'reason': 'The claim is corrected.'}]
        with patch('urllib.request.urlopen', return_value=self.provider(fixed)) as transport:
            result = self.client.post('/v3/session/answer', json={
                'session_id': self.sid, 'candidate_answer': 'new explanation'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['action'], 'next_topic')
        self.assertEqual(result.json()['cumulative_score'], 8)
        payload = json.loads(transport.call_args.args[0].data)
        self.assertIn(error_id, payload['messages'][1]['content'])
        self.assertNotIn('_resolutions', result.json())

    def test_public_evaluation_hides_internal_protocol_fields(self):
        output = self.output([2, 0, 0, 0, 0], wrong=True)
        output['error_updates'] = [{'flag_index': 0, 'error_id': None,
                                    'criterion_id': None, 'reason': 'Scope is uncertain.'}]
        with patch('urllib.request.urlopen', return_value=self.provider(output)):
            result = self.client.post('/v3/evaluate', json={
                'card_id': self.card_id, 'candidate_answer': 'new explanation; incorrect claim'})
        body = result.json()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(set(body), {'card_id', 'score', 'criteria', 'red_flags',
            'uncertainty', 'abstained', 'summary', 'warnings', 'needs_review',
            'human_review_required', 'review_status'})
        self.assertEqual(body['score'], 2)
        self.assertTrue(body['needs_review'])
        self.assertEqual(set(body['red_flags'][0]), {'id', 'quote', 'reason'})

    def test_provider_errors_leave_session_and_score_unchanged(self):
        self.answer(self.output([2, 2, 2, 0, 0]))
        before = copy.deepcopy(SESSIONS[self.sid].__dict__)
        responses = [b'not-json', b'{}', b'{"choices":[]}',
                     b'{"choices":[{"message":"wrong type"}]}',
                     b'{"choices":[{"message":{"content":"[]"}}]}']
        for body in responses:
            with self.subTest(body=body):
                with patch('urllib.request.urlopen', return_value=Response(body)):
                    result = self.client.post('/v3/session/answer', json={
                        'session_id': self.sid, 'candidate_answer': 'new explanation'})
                self.assertEqual(result.status_code, 502)
                self.assertEqual(SESSIONS[self.sid].__dict__, before)
        with patch('urllib.request.urlopen', side_effect=TimeoutError):
            result = self.client.post('/v3/session/answer', json={
                'session_id': self.sid, 'candidate_answer': 'new explanation'})
        self.assertEqual(result.status_code, 502)
        self.assertEqual(SESSIONS[self.sid].__dict__, before)

    def test_invalid_link_cannot_be_applied_as_a_zero_knowledge_answer(self):
        self.answer(self.output([2, 2, 2, 0, 0]))
        before = copy.deepcopy(SESSIONS[self.sid].__dict__)
        output = self.output([0, 0, 0, 0, 0], wrong=True)
        output['error_updates'] = [{'flag_index': 0, 'error_id': 'invented-id',
                                    'criterion_id': self.ids[1], 'reason': 'Invalid reference.'}]
        result = self.answer(output)
        self.assertEqual(result.status_code, 502)
        self.assertEqual(SESSIONS[self.sid].__dict__, before)

    def test_incomplete_or_wrongly_typed_output_is_not_a_zero_knowledge_answer(self):
        self.answer(self.output([2, 2, 2, 0, 0]))
        before = copy.deepcopy(SESSIONS[self.sid].__dict__)
        for changes in ('missing_flags', 'missing_summary', 'invalid_summary', 'missing_reason'):
            with self.subTest(changes=changes):
                output = self.output([0, 0, 0, 0, 0])
                if changes == 'missing_flags':
                    del output['red_flags']
                elif changes == 'missing_summary':
                    del output['summary']
                elif changes == 'invalid_summary':
                    output['summary'] = None
                else:
                    del output['criteria'][self.ids[0]]['reason']
                result = self.answer(output)
                self.assertEqual(result.status_code, 502)
                self.assertEqual(SESSIONS[self.sid].__dict__, before)

    def test_refusal_does_not_destroy_previously_demonstrated_knowledge(self):
        self.answer(self.output([2, 2, 2, 0, 0]))
        before = copy.deepcopy(SESSIONS[self.sid].__dict__)
        response = Response(b'{"choices":[{"message":{"refusal":"Cannot assess"}}]}')
        with patch('urllib.request.urlopen', return_value=response):
            result = self.client.post('/v3/session/answer', json={
                'session_id': self.sid, 'candidate_answer': 'new explanation'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'needs_review')
        self.assertEqual(SESSIONS[self.sid].__dict__, before)

    def test_invalid_quote_has_no_numeric_public_knowledge_score(self):
        output = self.output([2, 0, 0, 0, 0])
        with patch('urllib.request.urlopen', return_value=self.provider(output)):
            result = self.client.post('/v3/evaluate', json={
                'card_id': self.card_id, 'candidate_answer': 'different answer'})
        self.assertEqual(result.status_code, 502)
        self.assertNotIn('score', result.json())

    def test_json_object_mode_includes_the_internal_schema_in_the_prompt(self):
        with patch.dict(os.environ, {'LLM_JSON_MODE': 'object'}), \
             patch('urllib.request.urlopen', return_value=self.provider(self.output([0, 0, 0, 0, 0]))) as transport:
            result = self.client.post('/v3/evaluate', json={
                'card_id': self.card_id, 'candidate_answer': 'new explanation'})
        self.assertEqual(result.status_code, 200)
        payload = json.loads(transport.call_args.args[0].data)
        self.assertEqual(payload['response_format']['type'], 'json_object')
        self.assertIn('"error_updates"', payload['messages'][1]['content'])
        self.assertIn('"resolutions"', payload['messages'][1]['content'])
