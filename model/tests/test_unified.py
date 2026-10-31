import unittest
from unittest.mock import patch
from app.kb import load_kb, get_card
from src.core import read_data
from src.session import InterviewSession
from main import result_for_mock


class UnifiedTests(unittest.TestCase):
    def test_v1_rubric_mapping_is_explicit(self):
        card = get_card(load_kb(), 'PG-QUERY-01')
        rubric = read_data('rubric_postgresql.json')
        self.assertIsNotNone(card)
        self.assertEqual(card['competency'], rubric['competency'])
        self.assertEqual(rubric['topic_id'], 'pg_slow_query')

    def test_offline_session_uses_v2_gold_not_llm(self):
        partial = next(c for c in read_data('eval_cases.json') if c['id'] == 'T04_partial')
        s = InterviewSession()
        action = s.record_answer(partial['answer'], result_for_mock(partial))
        self.assertEqual(action['action'], 'followup')
        self.assertEqual(action['target'], 'index')

    def test_rest_api_v2_with_mock_llm(self):
        try:
            from fastapi.testclient import TestClient
            from app.api import app
        except ImportError:
            self.skipTest('Optional FastAPI/httpx packages not installed')
        from src.core import CRITERIA_IDS
        def mock_evaluate(answer, question=None, history=None):
            return {
                'criteria':{c:{'points':0,'quote':''} for c in CRITERIA_IDS},
                'score':0,'red_flags':[],'uncertainty':'low',
                'abstained':False,'refused':False,'warnings':[],
            }
        with patch('app.v2_api.run_eval',side_effect=mock_evaluate):
            client=TestClient(app)
            info=client.get('/v2/info')
            self.assertEqual(info.status_code,200)
            self.assertEqual(info.json()['knowledge_cards'],25)
            self.assertEqual(info.json()['scoring_supported_card_ids'],['PG-QUERY-01'])
            unsupported=client.post('/v2/evaluate',json={
                'card_id':'PY-ASYNC-01','candidate_answer':'hello'})
            self.assertEqual(unsupported.status_code,400)
            started=client.post('/v2/session/start')
            self.assertEqual(started.status_code,200)
            data=started.json()
            self.assertEqual(data['card_id'],'PG-QUERY-01')
            sid=data['session_id']
            first=client.post('/v2/session/answer',json={
                'session_id':sid,'candidate_answer':'Пример ответа'})
            self.assertEqual(first.status_code,200)
            self.assertEqual(first.json()['decision']['action'],'followup')
            self.assertTrue(first.json()['next_question'])

if __name__=='__main__':unittest.main()
