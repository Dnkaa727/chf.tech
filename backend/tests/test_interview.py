from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import main

client = TestClient(main.app)

def test_queue_and_followup():
    cards = client.get('/api/cards').json()['cards']
    ids = [c['card_id'] for c in cards[:2]]
    s = client.post('/api/conferences', json={'name':'Tester','card_ids':ids}).json()
    url = '/api/conferences/' + s['conferenceId']
    room = main.rooms[s['conferenceId']]
    def followup(*args):
        room.session.pending_question = 'Уточните ответ'
        return {'action':'followup','next_question':'Уточните ответ'}
    with patch.object(main, 'evaluate_live', return_value={}), patch.object(main.TopicSession, 'add_assessment', side_effect=followup):
        result = client.post(url+'/messages', json={'text':'Ответ'}).json()
    assert result['messages'][-1]['text'] == 'Уточните ответ'
    assert result['state']['queue'] == ids
    assert not result['interviewerTyping']
    with patch.object(main, 'evaluate_live', return_value={}), patch.object(main.TopicSession, 'add_assessment', return_value={'action':'next_topic','next_question':None,'cumulative_score':8}):
        first = client.post(url+'/messages', json={'text':'Ответ'}).json()
        assert first['session']['cardId'] == ids[1]
        assert first['state']['status'] == 'live'
        final = client.post(url+'/messages', json={'text':'Ответ'}).json()
    assert final['state']['status'] == 'ended'
    assert len(final['state']['results']) == 2
    assert client.post(url+'/messages', json={'text':'Ответ'}).status_code == 409
    main.rooms.pop(s['conferenceId'])

def test_invalid_answer_keeps_question_and_clears_processing():
    s = client.post('/api/conferences', json={'name':'Tester'}).json()
    url = '/api/conferences/' + s['conferenceId']
    assert client.post(url+'/messages', json={'text':'   '}).status_code == 422
    with patch.object(main, 'evaluate_live', side_effect=ValueError('Invalid assessment')):
        assert client.post(url+'/messages', json={'text':'Ответ'}).status_code == 422
    result = client.get(url).json()
    assert result['session']['pendingQuestion'] == s['session']['pendingQuestion']
    assert not result['interviewerTyping']
    main.rooms.pop(s['conferenceId'])


def test_feedback_does_not_announce_nonexistent_next_topic():
    assessment = {'summary': 'Ты верно объяснил, почему вызов блокирует цикл.'}
    assert main.interviewer_feedback(assessment, {'action': 'next_topic'}) == assessment['summary']
    assert main.interviewer_feedback({}, {'action': 'needs_review'}) == 'Здесь нужна дополнительная проверка — пока оставим оценку открытой.'
    assert main.interviewer_feedback({}, {'action': 'insufficient_evidence'}) == 'Пока мне не хватает деталей, чтобы оценить эту тему.'
