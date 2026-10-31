"""Unified 25-card RAG: offline checks/demo and optional paid LLM tests."""
from __future__ import annotations
import argparse,json,unittest,sys,os
from pathlib import Path
from v3.engine import (rubrics,cases,validate_data,gold_fixture,TopicSession,redteam_cases)
from v3.llm import evaluate_live


def print_json(value):print(json.dumps(value,ensure_ascii=False,indent=2))

def calls_per_answer():
    return 1 if os.getenv('LLM_PIPELINE_MODE', 'two_stage').strip().casefold() == 'one_stage' else 2

def one_offline(card_id,kind):
    t=next(c for c in cases() if c['card_id']==card_id and c['kind']==kind)
    s=TopicSession(card_id)
    decision=s.add_assessment(t['answer'],gold_fixture(t))
    print(f"{t['case_id']} | SYNTHETIC gold={t['gold_score']}/10 | next={decision['action']} | target={decision['target']}")
    if decision['next_question']:print('Follow-up:',decision['next_question'])
    return decision

def live(card_id,kind):
    t=next(c for c in cases() if c['card_id']==card_id and c['kind']==kind)
    r=evaluate_live(card_id,t['answer'])
    passed=(r['score'] is not None and t['acceptable_score_range'][0]<=r['score']<=t['acceptable_score_range'][1])
    detected={x['id'] for x in r['red_flags']}
    print(f'{t["case_id"]}: score={r["score"]} expected={t["acceptable_score_range"]} in_range={passed}; '
          f'flags expected={t["expected_flags"]}, observed={sorted(detected)}; review={r["needs_review"]}; '
          f'provider_calls={calls_per_answer()}')
    return {'case_id':t['case_id'],'score':r['score'],'range':t['acceptable_score_range'],
            'in_range':passed,'flags_expected':t['expected_flags'],'flags_observed':sorted(detected),
            'review':r['needs_review'],'warnings':r.get('warnings',[])}

def live_case_obj(t):
    r=evaluate_live(t['card_id'],t['answer'])
    passed=(r['score'] is not None and t['acceptable_score_range'][0]<=r['score']<=t['acceptable_score_range'][1])
    detected={x['id'] for x in r['red_flags']}
    print(f'{t["case_id"]}: score={r["score"]}, expected flag={t["expected_flags"]}, '
          f'observed={sorted(detected)}; provider_calls={calls_per_answer()}')
    return {'case_id':t['case_id'],'score':r['score'],'in_range':passed,
      'flags_expected':t['expected_flags'],'flags_observed':sorted(detected),
      'review':r['needs_review'],'warnings':r.get('warnings',[])}

def main():
    p=argparse.ArgumentParser(description='25 rubrics + 150 fixtures / generic RAG evaluator')
    sp=p.add_subparsers(dest='cmd',required=True)
    for cmd in ('check','cards','test','mock-all','serve'):
        sp.add_parser(cmd)
    sp.add_parser('rubric').add_argument('card_id')
    q=sp.add_parser('mock');q.add_argument('card_id');q.add_argument('kind',choices=['bad','medium','excellent','partial','confident_wrong','evasive'])
    q=sp.add_parser('live-one');q.add_argument('card_id');q.add_argument('kind',choices=['bad','medium','excellent','partial','confident_wrong','evasive'])
    q=sp.add_parser('live-six');q.add_argument('card_id')
    q=sp.add_parser('live-redteam');q.add_argument('card_id')
    q=sp.add_parser('live-all');q.add_argument('--confirm-cost',action='store_true')
    q=sp.add_parser('interview');q.add_argument('card_id')
    args=p.parse_args()
    rs=rubrics()
    if args.cmd=='check': print_json(validate_data())
    elif args.cmd=='cards':
        for r in rs.values(): print(r['card_id'],'|',r['competency'],'|',r['topic'],'| 5 criteria, 10 points')
    elif args.cmd=='rubric':print_json(rs[args.card_id])
    elif args.cmd=='mock':one_offline(args.card_id,args.kind)
    elif args.cmd=='mock-all':
        for r in rs.values():
            for kind in ['bad','medium','excellent','partial','confident_wrong','evasive']:
                decision=one_offline(r['card_id'],kind)
                exp=next(c['expected_next_action'] for c in cases() if c['card_id']==r['card_id'] and c['kind']==kind)
                assert decision['action']==exp,(r['card_id'],kind)
        print('OFFLINE OK: 150/150 synthetic fixtures (NOT live model predictions).')
    elif args.cmd=='test':
        suite=unittest.defaultTestLoader.discover('tests')
        result=unittest.TextTestRunner(verbosity=1).run(suite)
        if not result.wasSuccessful():sys.exit(1)
    elif args.cmd=='live-one':live(args.card_id,args.kind)
    elif args.cmd in ('live-six','live-all','live-redteam'):
        if args.cmd=='live-all' and not args.confirm_cost:
            total_calls = len(cases()) * calls_per_answer()
            p.error(f'{total_calls} paid provider calls in {os.getenv("LLM_PIPELINE_MODE", "two_stage")} mode: add --confirm-cost to proceed')
        if args.cmd=='live-redteam':
            examples=[c for c in redteam_cases() if c['card_id']==args.card_id]
            if not examples:raise ValueError('Unknown card_id')
            results=[live_case_obj(c) for c in examples]
        else:
            selected=([(args.card_id,k) for k in ['bad','medium','excellent','partial','confident_wrong','evasive']]
                      if args.cmd=='live-six' else [(c['card_id'],c['kind']) for c in cases()])
            results=[live(*k) for k in selected]
        out=Path('live_eval_v3_results.json')
        # Save only anonymized quality metrics; no candidates' texts
        out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
        print('Quality:',sum(x['in_range'] for x in results),'/',len(results),'in score band. Saved:',out)
    elif args.cmd=='interview':
        s=TopicSession(args.card_id)
        print('Only synthetic candidates. Type exit to stop. Current card:',s.card_id)
        while s.status=='in_progress':
            print('\nINTERVIEWER:',s.pending_question)
            answer=input('CANDIDATE: ').strip()
            if answer.lower() in ('exit','quit'):break
            if not answer: continue
            history=[{'question':x['question'],'answer':x['answer']} for x in s.history[-3:]]
            r=evaluate_live(args.card_id,answer,question=s.pending_question,history=history,
                            error_context=s.evaluation_context(),rubric=s.rubric)
            if r.get('refusal'):
                print('Refusal: needs human review');break
            result=s.add_assessment(answer,r)
            print('Latest score:',result['latest_score'],'/10; cumulative:',result['cumulative_score'],
                  '/10; action:',result['action'])
        print('Topic status:',s.status)
    elif args.cmd=='serve':
        try:import uvicorn
        except ImportError:raise SystemExit('Install: py -m pip install -r requirements.txt')
        uvicorn.run('app.api:app',host='127.0.0.1',port=8000)

if __name__=='__main__':main()
