import json
from urllib.parse import quote

import httpx

from backend.diagnose_tts import PAYLOAD, probe, redact


def test_diagnostic_preserves_actual_error_and_masks_keys():
    key = 'private key/with+symbols'
    def handler(request):
        assert str(request.url) == 'https://api.gen-api.ru/api/v1/networks/silero-tts'
        assert json.loads(request.content) == PAYLOAD
        assert request.headers['authorization'] == 'Bearer ' + key
        return httpx.Response(422,json={
            'message':'The sample_rate field must be a string.',
            'data':{'api_key':key, 'detail':f'Bad token: {key}', 'encoded':quote(key,safe='')},
            'authorization':'Bearer different-secret',
        })
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = probe(key,client)
    text = json.dumps(report)
    assert report['http_status'] == 422
    assert 'must be a string' in text
    assert key not in text and quote(key,safe='') not in text and 'different-secret' not in text


def test_diagnostic_success_does_not_expose_asset_urls_or_poll():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'request_id':42,'status':'starting','output':'https://example.com/signed?token=private'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe('test-key',client) == {'http_status':200,'result':{'request_id':42,'status':'starting'}}
    assert len(calls) == 1


def test_diagnostic_non_json_and_transport_failure_are_safe():
    key='test-key'
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(422,text=f'Error: {key} Bearer another-secret'))) as client:
        result=probe(key,client)
    assert key not in str(result) and 'another-secret' not in str(result)
    def fail(request):
        raise httpx.ConnectError('private proxy details')
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        assert probe(key,client) == {'transport_error':'ConnectError'}


def test_diagnostic_without_key_never_calls_provider():
    def handler(request):
        raise AssertionError('must not call provider')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert 'missing' in probe('',client)['error']


def test_redaction_masks_even_dictionary_keys_and_nested_credentials():
    text=json.dumps(redact({'private-key': {'access_token':'another-token'},'error':'Bearer another-token'},'private-key'))
    assert 'private-key' not in text and 'another-token' not in text
