"""Regression tests for empty criterion routing and provider error diagnostics."""
import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from v3.engine import rubrics, scoring_schema_for, check_segmented_output
from v3.llm import _request_json, LLMProviderError
from v3.diagnostics import failure_headers

CARD_ID = 'PG-TX-01'


def _segments_with_unrouted_k5():
    return [
        {'segment_id': 'S001', 'quote': 'Изменение и запись будут в одной транзакции.',
         'claim_type': 'mechanism', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K1', 'reason': 'Атомарность.'}], 'start': 0, 'end': 44},
        {'segment_id': 'S002', 'quote': 'Два запроса могут увидеть один остаток.',
         'claim_type': 'cause', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K2', 'reason': 'Гонка.'}], 'start': 45, 'end': 84},
        {'segment_id': 'S003', 'quote': 'Проверку и изменение нужно защитить.',
         'claim_type': 'solution', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K3', 'reason': 'Защита.'}], 'start': 85, 'end': 122},
        {'segment_id': 'S004', 'quote': 'При конкуренции транзакция может завершиться ошибкой.',
         'claim_type': 'cause', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K4', 'reason': 'Ошибка транзакции.'}], 'start': 123, 'end': 176},
        # No segment is routed to K5: the short answer says it will test concurrency,
        # but does not yet state an invariant or an expected result.
    ]


def test_unrouted_criterion_uses_nonempty_sentinel_object_schema():
    segments = _segments_with_unrouted_k5()
    schema = scoring_schema_for(CARD_ID, segments)
    criteria = schema['properties']['criteria']['properties']
    k5_schema = criteria[f'{CARD_ID}-K5']['properties']['segment_assessments']
    assert k5_schema['type'] == 'object'
    assert k5_schema['required'] == ['__no_evidence__']
    assert k5_schema['properties']['__no_evidence__']['enum'] == ['not_applicable']

    def walk(node):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    assert not any(node.get('type') == 'object' and node.get('properties') == {}
                   for node in walk(schema))


def test_unrouted_criterion_uses_sentinel_and_scores_zero():
    rubric = rubrics()[CARD_ID]
    segments = _segments_with_unrouted_k5()
    criteria = {}
    for criterion in rubric['criteria']:
        cid = criterion['id']
        ids = [s['segment_id'] for s in segments if any(
            link['criterion_id'] == cid for link in s['criterion_links'])]
        criteria[cid] = {
            'points': 1 if ids else 0,
            'segment_assessments': ({sid: 'partially_supports' for sid in ids}
                                    if ids else {'__no_evidence__': 'not_applicable'}),
            'reason': 'Есть частичное объяснение.' if ids else 'Нет связанного фрагмента.',
        }
    output = {
        'reviewed_segment_ids': {s['segment_id']: True for s in segments},
        'criteria': criteria,
        'red_flag_checks': {
            flag['id']: {'detected': False, 'evidence_ids': [], 'reason': 'Нет доказательств.'}
            for flag in rubric['red_flag_definitions']
        },
        'uncertainty': 'low', 'abstained': False, 'summary': 'Частичный ответ.',
        'error_updates': [], 'resolutions': [],
    }
    answer = 'Изменение и запись будут в одной транзакции. Два запроса могут увидеть один остаток. Проверку и изменение нужно защитить. При конкуренции транзакция может завершиться ошибкой.'
    result = check_segmented_output(CARD_ID, answer, segments, output)
    assert result['score'] == 4
    assert result['criteria'][f'{CARD_ID}-K5']['points'] == 0
    assert result['criteria'][f'{CARD_ID}-K5']['evidence'] == []


def test_provider_http_error_exposes_only_safe_provider_code_and_stage():
    from urllib.request import Request
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
              'required': ['ok'], 'additionalProperties': False}
    body = json.dumps({'error': {
        'message': 'Sensitive diagnostic text must not be returned.',
        'type': 'invalid_request_error',
        'code': 'invalid_json_schema',
        'param': 'response_format.json_schema.schema',
    }}).encode()
    error = urllib.error.HTTPError(
        'https://gateway.invalid/v1/chat/completions', 400, 'Bad Request',
        {'x-request-id': 'req_abc123'}, BytesIO(body),
    )
    with patch('v3.llm.urllib.request.urlopen', side_effect=error):
        with pytest.raises(LLMProviderError) as caught:
            _request_json(
                [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'input'}],
                schema, 'test_schema', model='test', base='https://gateway.invalid/v1',
                api_key='secret-that-must-not-leak', timeout=5, json_mode='schema',
                message_mode='developer', stage='scoring',
            )
    detail = caught.value.diagnostic
    assert detail.provider_status == 400
    assert detail.provider_error_code == 'invalid_json_schema'
    assert detail.provider_error_type == 'invalid_request_error'
    assert detail.provider_param == 'response_format.json_schema.schema'
    headers = failure_headers(caught.value, card_id=CARD_ID,
                              criterion_ids=[f'{CARD_ID}-K1', f'{CARD_ID}-K2', f'{CARD_ID}-K3', f'{CARD_ID}-K4', f'{CARD_ID}-K5'])
    assert headers['X-LLM-Stage'] == 'scoring'
    assert headers['X-LLM-Provider-Code'] == 'invalid_json_schema'
    assert headers['X-LLM-Provider-Param'] == 'response_format.json_schema.schema'
    assert 'Sensitive diagnostic text' not in json.dumps(headers)
    assert 'secret-that-must-not-leak' not in json.dumps(headers)

class _ProviderResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _provider_json(value):
    return _ProviderResponse(json.dumps({
        'choices': [{'message': {'role': 'assistant',
                                 'content': json.dumps(value, ensure_ascii=False)},
                     'finish_reason': 'stop'}]
    }, ensure_ascii=False).encode('utf-8'))


def test_partial_pg_tx_answer_completes_without_any_empty_object_schema():
    from v3.llm import evaluate_live
    answer = (
        'Связанные изменения лучше выполнять в одной транзакции. '
        'Два запроса могут одновременно работать с одним балансом, поэтому один из результатов может оказаться некорректным. '
        'Проверку остатка и само изменение нужно защитить от одновременного выполнения. '
        'При конкуренции транзакция может завершиться ошибкой. '
        'Проверю ситуацию, когда два списания запускаются одновременно.'
    )
    rubric = rubrics()[CARD_ID]
    raw_segments = {'segments': [
        {'quote': 'Связанные изменения лучше выполнять в одной транзакции.',
         'claim_type': 'mechanism', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K1', 'reason': 'Связано с атомарностью.'}]},
        {'quote': 'Два запроса могут одновременно работать с одним балансом, поэтому один из результатов может оказаться некорректным.',
         'claim_type': 'cause', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K2', 'reason': 'Описывает гонку.'}]},
        {'quote': 'Проверку остатка и само изменение нужно защитить от одновременного выполнения.',
         'claim_type': 'solution', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K3', 'reason': 'Описывает защиту.'}]},
        {'quote': 'При конкуренции транзакция может завершиться ошибкой.',
         'claim_type': 'cause', 'criterion_links': [
             {'criterion_id': f'{CARD_ID}-K4', 'reason': 'Указывает на ошибку конкурирующих транзакций.'}]},
        {'quote': 'Проверю ситуацию, когда два списания запускаются одновременно.',
         'claim_type': 'test', 'criterion_links': []},
    ]}
    # LLM returns semantic fragments; Python records matched/unverified alignment.
    from v3.engine import validate_segments
    segments = validate_segments(CARD_ID, answer, raw_segments, rubric=rubric)
    criteria = {}
    for criterion in rubric['criteria']:
        cid = criterion['id']
        ids = [s['segment_id'] for s in segments if any(
            link['criterion_id'] == cid for link in s['criterion_links'])]
        criteria[cid] = {
            'points': 1 if ids else 0,
            'segment_assessments': ({sid: 'partially_supports' for sid in ids}
                                    if ids else {'__no_evidence__': 'not_applicable'}),
            'reason': 'Частичное раскрытие критерия.' if ids else 'Нет достаточного раскрытия критерия.',
        }
    scoring = {
        'reviewed_segment_ids': {s['segment_id']: True for s in segments},
        'criteria': criteria,
        'red_flag_checks': {
            flag['id']: {'detected': False, 'evidence_ids': [], 'reason': 'Нет доказательств.'}
            for flag in rubric['red_flag_definitions']
        },
        'uncertainty': 'low', 'abstained': False, 'summary': 'Частичный ответ.',
        'error_updates': [], 'resolutions': [],
    }
    env = {
        'LLM_API_KEY': 'TEST_ONLY', 'LLM_MODEL': 'gpt-4o-mini',
        'LLM_BASE_URL': 'http://localhost:5005/v1', 'LLM_JSON_MODE': 'schema',
        'LLM_MESSAGE_MODE': 'system_user', 'LLM_PIPELINE_MODE': 'two_stage',
    }
    with patch('v3.llm.os.environ', {**__import__('os').environ, **env}), \
         patch('v3.llm.urllib.request.urlopen', side_effect=[
             _provider_json(raw_segments), _provider_json(scoring)
         ]) as transport:
        result = evaluate_live(CARD_ID, answer, rubric=rubric)
    assert result['score'] == 4
    assert result['criteria'][f'{CARD_ID}-K5']['points'] == 0
    assert transport.call_count == 2
    sent_schema = json.loads(transport.call_args_list[1].args[0].data)['response_format']['json_schema']['schema']
    k5_schema = sent_schema['properties']['criteria']['properties'][f'{CARD_ID}-K5']['properties']['segment_assessments']
    assert k5_schema['type'] == 'object'
    assert k5_schema['required'] == ['__no_evidence__']
