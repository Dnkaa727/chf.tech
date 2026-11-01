import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.tts import GenApiSpeech, SpeechError, SpeechJob, audio_type, audio_url, validate_audio_url

AUDIO = b'OggS' + b'fake-test-audio'


def service(handler):
    return GenApiSpeech(lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))


def test_completed_result_cache_and_no_token_forwarded(monkeypatch):
    monkeypatch.setenv('GENAPI_API_KEY', 'test-only-key')
    calls = []
    def handler(request):
        calls.append(request)
        if request.method == 'POST':
            assert request.url == 'https://api.gen-api.ru/api/v1/networks/silero-tts'
            assert request.headers['authorization'] == 'Bearer test-only-key'
            payload = json.loads(request.content)
            assert payload['is_sync'] is False
            assert payload['lang'] == 'ru' and payload['format'] == 'ogg'
            assert payload['text'] == 'Вопрос интервьюера'
            return httpx.Response(200, json={'status':'success','request_id':42,'output':['https://audio.example.test/42.ogg']})
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=AUDIO, headers={'Content-Type':'audio/ogg'})
    async def run():
        client = service(handler)
        job = SpeechJob()
        with patch('backend.tts.validate_audio_url', new=AsyncMock()):
            first, second = await asyncio.gather(client.get('q', 'Вопрос интервьюера', job), client.get('q', 'Вопрос интервьюера', job))
            assert first == second == (AUDIO,'audio/ogg')
            assert await client.get('q', 'Вопрос интервьюера', job) == first
            assert len(calls) == 2
            # Evicted audio can be downloaded again without another paid submission.
            client.cache.clear(); client.cache_size = 0
            assert await client.get('q', 'Вопрос интервьюера', job) == first
            assert [r.method for r in calls] == ['POST','GET','GET']
    asyncio.run(run())


@pytest.mark.parametrize('status,message', [(401,'ключ'),(403,'ключ'),(402,'средств'),(429,'лимит')])
def test_provider_errors_are_safe_and_allow_explicit_retry(monkeypatch, status, message):
    monkeypatch.setenv('GENAPI_API_KEY', 'test-only-key')
    client = service(lambda r: httpx.Response(status, json={'error':'sensitive provider detail'}))
    job = SpeechJob()
    with pytest.raises(SpeechError, match=message) as caught:
        asyncio.run(client.get('q','Вопрос',job))
    assert 'sensitive' not in str(caught.value)
    assert not job.submitted


def test_ambiguous_submit_failure_is_not_automatically_resubmitted(monkeypatch):
    monkeypatch.setenv('GENAPI_API_KEY', 'test-only-key')
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout')
    async def run():
        client = service(handler); job = SpeechJob()
        with pytest.raises(SpeechError):
            await client.get('q','Вопрос',job)
        with pytest.raises(SpeechError):
            await client.get('q','Вопрос',job)
        assert len(calls) == 1
    asyncio.run(run())


def test_missing_key_does_not_contact_provider(monkeypatch):
    monkeypatch.delenv('GENAPI_API_KEY', raising=False)
    def handler(request):
        pytest.fail('must not contact provider')
    with pytest.raises(SpeechError, match='GENAPI_API_KEY'):
        asyncio.run(service(handler).get('q','Вопрос',SpeechJob()))


def test_output_formats_and_non_audio_response():
    assert audio_url({'audio':'https://example.test/audio.ogg'}) == 'https://example.test/audio.ogg'
    with pytest.raises(SpeechError): audio_url({'unexpected':42})
    with pytest.raises(SpeechError): audio_type(b'<html>error</html>')


def test_download_rejects_private_hosts_and_unsafe_schemes():
    for url in ('file:///etc/passwd','http://example.com/a.ogg','https://user:password@example.com/a.ogg'):
        with pytest.raises(SpeechError): asyncio.run(validate_audio_url(url))
    with patch('backend.tts.socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
        with pytest.raises(SpeechError): asyncio.run(validate_audio_url('https://private.example.test/a.ogg'))


def test_audio_endpoint_only_speaks_existing_interviewer_messages_and_works_after_end():
    client = TestClient(main.app)
    room = client.post('/api/conferences', json={'name':'Tester'}).json()
    room_id = room['conferenceId']; question = room['messages'][0]['id']
    try:
        with patch.object(main.speech,'get',new=AsyncMock(return_value=(AUDIO,'audio/ogg'))) as mocked:
            assert client.post(f'/api/conferences/{room_id}/messages/missing/audio').status_code == 404
            main.rooms[room_id].messages.append(main.make_message('me','Tester','candidate','Private answer'))
            candidate = main.rooms[room_id].messages[-1]['id']
            assert client.post(f'/api/conferences/{room_id}/messages/{candidate}/audio').status_code == 404
            assert mocked.await_count == 0
            main.rooms[room_id].ended = True
            result = client.post(f'/api/conferences/{room_id}/messages/{question}/audio')
            assert result.status_code == 200 and result.content == AUDIO
            assert result.headers['content-type'] == 'audio/ogg'
            assert result.headers['cache-control'] == 'no-store'
            assert mocked.await_args.args[1] == room['messages'][0]['text']
    finally:
        main.rooms.pop(room_id, None)


def test_async_polling_and_retry_resume_same_paid_job(monkeypatch):
    monkeypatch.setenv('GENAPI_API_KEY', 'test-only-key')
    monkeypatch.setattr('backend.tts.POLL_INTERVAL', 0)
    calls = []
    statuses = iter(['processing', 'timeout', 'success'])
    def handler(request):
        calls.append(request)
        if request.method == 'POST':
            return httpx.Response(200,json={'request_id':12345,'status':'starting'})
        if '/request/get/' in request.url.path:
            assert str(request.url) == 'https://api.gen-api.ru/api/v1/request/get/12345'
            assert request.headers['authorization'] == 'Bearer test-only-key'
            status = next(statuses)
            if status == 'timeout': raise httpx.ReadTimeout('timeout while polling')
            return httpx.Response(200,json={'request_id':12345,'status':status,'output':['https://audio.example.test/clip.ogg']})
        assert 'authorization' not in request.headers
        return httpx.Response(200,content=AUDIO)
    async def run():
        client = service(handler); job = SpeechJob()
        with patch('backend.tts.validate_audio_url', new=AsyncMock()):
            with pytest.raises(SpeechError) as err:
                await client.get('q','Вопрос',job)
            assert err.value.status == 504
            assert job.request_id == '12345'
            result = await client.get('q','Вопрос',job)
            assert result == (AUDIO,'audio/ogg')
            assert sum(r.method == 'POST' for r in calls) == 1
    asyncio.run(run())


def test_polling_auth_failure_never_discards_existing_job(monkeypatch):
    monkeypatch.setenv('GENAPI_API_KEY','test-only-key')
    job = SpeechJob(submitted=True, request_id='42')
    def handler(request):
        assert request.method == 'GET'
        return httpx.Response(401)
    with pytest.raises(SpeechError):
        asyncio.run(service(handler).get('q','Вопрос',job))
    assert job.submitted and job.request_id == '42'
