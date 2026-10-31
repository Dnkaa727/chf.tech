"""Public selection contracts, ambiguity and snapshot use by existing v3 routes."""
import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.api import app
from app.v3_api import SESSIONS
from v3.engine import rubrics


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def assert_public(self, card):
        self.assertTrue({'card_id', 'competency', 'topic', 'question', 'target_level', 'source_urls'} <= set(card))
        self.assertFalse({'criteria', 'anchors', 'followup_questions', 'red_flag_definitions',
                          'rubric', 'messages', 'followup_question'} & set(card))

    def test_public_catalog_has_all_25_cards_and_no_hidden_rubric(self):
        result = self.client.get('/v3/cards')
        self.assertEqual(result.status_code, 200)
        cards = result.json()['cards']
        self.assertEqual(len(cards), 25)
        self.assertEqual(len({c['card_id'] for c in cards}), 25)
        for card in cards:
            self.assert_public(card)

    def test_unique_topic_and_alias_filter_select_the_right_rubric(self):
        queries = [({'query': 'индексы PostgreSQL'}, 'PG-QUERY-01'),
                   ({'query': 'asyncio'}, 'PY-ASYNC-01'),
                   ({'query': 'сессии и транзакции', 'competency': 'sqlalchemy'}, 'ORM-SESSION-01'),
                   ({'query': 'PG-QUERY-01'}, 'PG-QUERY-01')]
        for payload, expected in queries:
            with self.subTest(payload=payload):
                result = self.client.post('/v3/cards/select', json=payload)
                self.assertEqual(result.status_code, 200)
                body = result.json()
                self.assertEqual(body['card']['card_id'], expected)
                self.assertEqual(body['rubric_version'], rubrics()[expected]['version'])
                self.assert_public(body['card'])

    def test_generic_or_multitopic_query_never_selects_the_first_card(self):
        for payload in ({'query': 'Python'}, {'competency': 'PostgreSQL'},
                        {'query': 'индексы транзакции', 'competency': 'PostgreSQL'}):
            with self.subTest(payload=payload):
                before = set(SESSIONS)
                result = self.client.post('/v3/cards/select', json=payload)
                self.assertEqual(result.status_code, 409)
                detail = result.json()['detail']
                self.assertEqual(detail['code'], 'ambiguous_card')
                self.assertGreater(len(detail['candidates']), 1)
                self.assertEqual(set(SESSIONS), before)
                for candidate in detail['candidates']:
                    self.assert_public(candidate)

    def test_filter_does_not_turn_an_irrelevant_topic_into_a_match(self):
        for payload in ({'query': 'садовая лопата'},
                        {'query': 'садовая лопата', 'competency': 'PostgreSQL'},
                        {'card_id': 'MISSING-CARD'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/v3/cards/select', json=payload).status_code, 404)
        self.assertEqual(self.client.post('/v3/cards/select', json={}).status_code, 422)

    def test_explicit_choice_after_ambiguity_starts_the_existing_session_api(self):
        ambiguous = self.client.post('/v3/cards/select', json={'query': 'Python'}).json()
        cid = ambiguous['detail']['candidates'][0]['card_id']
        selection = self.client.post('/v3/cards/select', json={'card_id': cid}).json()
        started = self.client.post('/v3/session/start', json={'card_id': selection['card']['card_id']})
        self.assertEqual(started.status_code, 200)
        body = started.json()
        self.addCleanup(SESSIONS.pop, body['session_id'], None)
        self.assertEqual(body['question'], selection['card']['question'])
        self.assertEqual(SESSIONS[body['session_id']].rubric_version, selection['rubric_version'])

    def test_v1_and_v2_are_marked_legacy_without_removing_routes(self):
        paths = self.client.get('/openapi.json').json()['paths']
        for path, operations in paths.items():
            if path.startswith(('/v1/', '/v2/')):
                for operation in operations.values():
                    self.assertTrue(operation.get('deprecated'))
        self.assertEqual(self.client.get('/v1/competencies').status_code, 200)
        self.assertEqual(self.client.get('/v2/info').status_code, 200)

    def test_session_evaluation_never_returns_to_the_current_registry_or_disk(self):
        cid = 'PY-ASYNC-01'
        started = self.client.post('/v3/session/start', json={'card_id': cid}).json()
        sid = started['session_id']
        self.addCleanup(SESSIONS.pop, sid, None)
        session = SESSIONS[sid]
        output = {'criteria': {c['id']: {'points': 0, 'quote': '', 'reason': 'Not covered.'}
                              for c in session.rubric['criteria']},
                  'red_flags': [], 'uncertainty': 'low', 'abstained': False,
                  'summary': 'Test.', 'error_updates': [], 'resolutions': []}
        response = BytesIO(json.dumps({'choices': [{'message': {
            'content': json.dumps(output)}}]}).encode())
        with patch.dict(os.environ, {'LLM_API_KEY': 'FAKE_TEST_TOKEN', 'LLM_JSON_MODE': 'schema',
                                    'LLM_MESSAGE_MODE': 'developer', 'LLM_PIPELINE_MODE': 'one_stage'}), \
             patch('urllib.request.urlopen', return_value=response), \
             patch('v3.engine.get_registry', side_effect=AssertionError('Unpinned rubric')), \
             patch('v3.llm.get_registry', side_effect=AssertionError('Unpinned rubric')), \
             patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected disk read')):
            result = self.client.post('/v3/session/answer', json={
                'session_id': sid, 'candidate_answer': 'I do not know yet.'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['action'], 'followup')


if __name__ == '__main__':
    unittest.main()
