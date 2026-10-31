"""Independent rubric probes for 24 cards (synthetic examples, NOT approved HR gold).

Commands:
 python logic_probes_24.py --cards
 python logic_probes_24.py --card PY-ASYNC-01
 python logic_probes_24.py --card PY-ASYNC-01 --case C_plain_reasoning --show-request
 python logic_probes_24.py --card PY-ASYNC-01 --case C_plain_reasoning --live
 python logic_probes_24.py --card PY-ASYNC-01 --all --live --confirm-cost

Without --live, DOES NOT contact a model or issue billable requests.
"""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from v3.engine import segmentation_messages_for,rubrics
from v3.llm import evaluate_live

ROOT=Path(__file__).resolve().parent
TESTS=json.loads((ROOT/'data'/'logic_probes_24.json').read_text(encoding='utf-8'))['cases']
CARDS={c['card_id'] for c in TESTS}
CASES={c['case_id'] for c in TESTS}

def calls_per_answer():
    return 1 if os.getenv('LLM_PIPELINE_MODE', 'two_stage').strip().casefold() == 'one_stage' else 2

def assess(case, result):
    scores={k.rsplit('-',1)[-1]:entry['points'] for k,entry in result['criteria'].items()}
    actual_flags={entry['id'] for entry in result['red_flags']}
    expected=case['expect']; issues=[]
    if result.get('score') is None:
        issues.append('score withheld for review')
    if result.get('score') is not None and 'score_min' in expected and result['score']<expected['score_min']:
        issues.append('score below provisional floor')
    if result.get('score') is not None and 'score_max' in expected and result['score']>expected['score_max']:
        issues.append('score above provisional ceiling')
    for flag in expected.get('flag_absent',[]):
        if flag in actual_flags:issues.append('unexpected '+flag)
    print(f"{case['card_id']} {case['case_id']}: score={result['score']}/10, criteria={scores}, flags={sorted(actual_flags)}, review={result['needs_review']}, status={'REVIEW' if issues else 'provisional checks passed'}")
    for cid,item in result['criteria'].items():
        print(f"  {cid}: {item['points']}/2; цитата={item['quote'][:100]!r}; основание={item['reason'][:180]}")
    if issues:print('  СОМНЕНИЯ:',', '.join(issues))
    return issues

def main():
    p=argparse.ArgumentParser(description='120 reasoning probes for 24 newly revised rubrics')
    p.add_argument('--cards',action='store_true',help='Список карточек и команд')
    p.add_argument('--card',choices=sorted(CARDS))
    p.add_argument('--case',choices=sorted(CASES))
    p.add_argument('--all',action='store_true',help='Все пять сценариев выбранной карточки (или 120 при --confirm-cost и без --card)')
    p.add_argument('--compare',action='store_true',help='Сравнить A, B, C на одной карточке (3 вызова при --live)')
    p.add_argument('--show-request',action='store_true',help='Вывести JSON для Swagger /v3/evaluate без вызова модели')
    p.add_argument('--live',action='store_true',help='Отправить платные запросы в API')
    p.add_argument('--confirm-cost',action='store_true',help='Явно разрешить несколько платных вызовов')
    a=p.parse_args()
    if a.cards or not (a.card or a.all):
        for c in sorted(CARDS):print(c)
        print('Пример: python logic_probes_24.py --card PY-ASYNC-01 --case C_plain_reasoning --show-request')
        return
    if a.case and not a.card:p.error('For --case specify --card')
    if a.compare and (not a.card or a.case or a.all):p.error('--compare requires --card and no --case/--all')
    selected=[c for c in TESTS if (a.card is None or c['card_id']==a.card) and (a.all or c['case_id']==a.case or (a.compare and c['case_id'] in ('A_alternative_reasoning','B_keyword_soup','C_plain_reasoning')))]
    if not selected:
        if a.card and not a.case:
            for c in TESTS:
                if c['card_id']==a.card:print(c['case_id'],'-',c['title'])
        return
    if a.live and len(selected)>1 and not a.confirm_cost:
        p.error(f'Это {len(selected) * calls_per_answer()} платных provider-вызовов в режиме {os.getenv("LLM_PIPELINE_MODE", "two_stage")}; добавь --confirm-cost')
    actual_scores={}
    for c in selected:
        cid=c['card_id']
        # Validate prompt in both offline and online branches
        message=segmentation_messages_for(cid,c['answer'])
        if cid not in message[1]['content'] or 'criterion_links' not in message[1]['content']:
            raise RuntimeError('Semantic routing prompt not assembled for '+cid)
        if a.show_request:
            print(json.dumps({'card_id':cid,'candidate_answer':c['answer']},ensure_ascii=False,indent=2))
        elif not a.live:
            print(f"OFFLINE {cid} {c['case_id']}: semantic segmentation/routing prompt assembled, 5 rubric criteria, no LLM evaluation")
        else:
            try:
                print(f"\nEvaluating live case: {cid} {c.get('name', '')}")
                result = evaluate_live(cid, c["answer"])
            except Exception as exc:
                print("\nLIVE ERROR:", repr(exc))
                print("Exception attributes:", getattr(exc, "__dict__", {}))
                print("code:", getattr(exc, "code", None))
                print("criterion_id:", getattr(exc, "criterion_id", None))
                print("field:", getattr(exc, "field", None))
                raise
            actual_scores[c['case_id']]=result['score']
            assess(c,result)
    if a.live and a.compare:
        a_score=actual_scores['A_alternative_reasoning'];b_score=actual_scores['B_keyword_soup'];c_score=actual_scores['C_plain_reasoning']
        if None in (a_score, b_score, c_score):
            print('RELATIVE CHECK: сравнение невозможно — хотя бы один ответ отправлен на экспертную проверку.')
        else:
            print(f'RELATIVE CHECK: alternative={a_score}, keywords={b_score}, plain={c_score}; A>B={a_score>b_score}, C>B={c_score>b_score}')
            if not (a_score>b_score and c_score>b_score):print('ТРЕБУЕТ РАЗБОРА: модель не различила осмысленный подход и простое перечисление терминов.')
    if a.live:
        print('Оценки предварительные. two_stage делает два вызова LLM на ответ. Проверь результат с техническим экспертом; smoke-тест не доказывает качество модели.')

if __name__=='__main__':main()
