"""One entry point for the unified Python Backend RAG demonstration.

All commands except live-one, live-all, interview and serve work with Python's
standard library only and never contact a paid API.
"""
from __future__ import annotations
import argparse
import json
import sys
import unittest
from app.kb import load_kb, get_card
from app.retrieval import retrieve
from src.core import read_data, decide_next
from src.session import InterviewSession
from src.llm_eval import evaluate
from main import result_for_mock


def print_status():
    cards=load_kb()
    cases=read_data('eval_cases.json')
    rubric=read_data('rubric_postgresql.json')
    ids={c['id'] for c in cards}
    assert len(ids)==len(cards), 'Duplicate card ids'
    assert 'PG-QUERY-01' in ids
    assert len(cases)==6
    assert rubric['topic_id']=='pg_slow_query'
    print(f'OK: {len(cards)} knowledge cards, {len({c["competency"] for c in cards})} competencies')
    print(f'OK: {len(cases)} evaluation cases, 1 scoring rubric: PG-QUERY-01')
    print('NOT YET: scoring rubrics for the other 24 knowledge cards')
    print('Live LLM has not been called by this command.')


def demo():
    print('OFFLINE DEMO (gold fixture, NOT a neural network prediction):')
    cards=load_kb()
    card=get_card(cards,'PG-QUERY-01')
    rubric=read_data('rubric_postgresql.json')
    case=next(c for c in read_data('eval_cases.json') if c['id']=='T04_partial')
    matches=retrieve(cards,'медленный SQL запрос PostgreSQL индекс',limit=4)
    assert any(x['id']=='PG-QUERY-01' for x in matches), 'Cannot retrieve PG-QUERY-01'
    print('1. Retrieved:',card['id'],'|',card['topic'])
    print('2. Question:',rubric['question'])
    print('3. Gold test case:',case['id'],case['category'])
    session=InterviewSession()
    first=session.record_answer(case['answer'],result_for_mock(case))
    print('4. Expected score:',sum(case['gold_criteria'].values()),'/10')
    print('5. Action:',first['action'],'| target:',first.get('target'))
    print('6. Follow-up:',first.get('question'))
    print('7. Session saved:',len(session.transcript),'turn; no disk writes')
    print('For a real LLM result use: py run.py live-one T04_partial')


def live(case_ids):
    cases={c['id']:c for c in read_data('eval_cases.json')}
    summaries=[]
    for cid in case_ids:
        if cid not in cases: raise ValueError('Unknown case '+cid)
        case=cases[cid]
        evaluation=evaluate(case['answer'])
        if evaluation.get('needs_review'):
            print(cid,': model refused / human review')
            summaries.append({'case':cid,'needs_review':True})
            continue
        correct=case['gold_score'][0]<=evaluation['score']<=case['gold_score'][1]
        next_=decide_next(evaluation,{'followups_asked':0})
        flags=set(evaluation.get('red_flags',[]))
        print(f'{cid}: MODEL={evaluation["score"]}/10, expected={case["gold_score"]}, in_range={correct}, next={next_["action"]}, flags={sorted(flags)}')
        summaries.append({'case':cid,'predicted_score':evaluation['score'],'expected':case['gold_score'],
                          'in_range':correct,'next_action':next_['action'],'flags':sorted(flags),
                          'expected_flags':case['expected_flags'],'warnings':evaluation['warnings']})
    print('Summary:',sum(x.get('in_range',False) for x in summaries),'/',len(summaries),'within expected range')
    # only synthetic cases, no real candidate data
    from pathlib import Path
    dest=Path('live_eval_results.json')
    dest.write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Results:',dest)


def interview():
    print('EXPERIMENT: this interview supports ONE topic PostgreSQL only.')
    print('Type exit to stop. Do not input real candidate personal data.')
    session=InterviewSession()
    while session.status=='in_progress':
        question=session.pending_question
        print('\nINTERVIEWER:',question)
        answer=input('CANDIDATE: ').strip()
        if answer.casefold() in ('exit','quit'): break
        if not answer:
            print('Enter an answer or exit')
            continue
        history=[(r['question'],r['answer']) for r in session.transcript[-2:]]
        result=evaluate(answer,question=question,history=history)
        if result.get('needs_review'):
            print('Provider refused; manual review required');break
        decision=session.record_answer(answer,result)
        print('MODEL SCORE (draft):',result['score'],'/10', '| NEXT:',decision['action'])
    print('Topic status:',session.status)


def main():
    p=argparse.ArgumentParser(description='One integrated RAG v1 + v2 project')
    sub=p.add_subparsers(dest='command',required=True)
    for c in ('check','demo','test','live-all','interview','serve','list'):
        sub.add_parser(c)
    sub.add_parser('search').add_argument('query')
    sub.add_parser('live-one').add_argument('case_id')
    args=p.parse_args()
    if args.command=='check': print_status()
    elif args.command=='list':
        for card in load_kb():print(card['id'],'|',card['competency'],'|',card['topic'])
    elif args.command=='demo':demo()
    elif args.command=='search':
        found=retrieve(load_kb(),args.query,limit=5)
        for c in found: print(c['id'],'|',c['competency'],'|',c['topic'],'| score',c['score'])
        if not found:print('Nothing found')
    elif args.command=='test':
        suite=unittest.defaultTestLoader.discover('tests')
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():sys.exit(1)
    elif args.command=='live-one':live([args.case_id])
    elif args.command=='live-all':live([c['id'] for c in read_data('eval_cases.json')])
    elif args.command=='interview':interview()
    elif args.command=='serve':
        try: import uvicorn
        except ImportError as exc:raise SystemExit('Install requirements first: py -m pip install -r requirements.txt') from exc
        uvicorn.run('app.api:app',host='127.0.0.1',port=8000)


if __name__=='__main__':main()
