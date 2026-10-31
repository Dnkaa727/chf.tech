"""Запуск: python main.py --list | --mock | --prepare T02_medium | --live [id] | --search '...'."""
import argparse
import json
from src.core import read_data, retrieve, decide_next, CRITERIA_IDS
from src.llm_eval import build_messages, evaluate


def result_for_mock(case):
    """НЕ модель! Подставляет золотую ручную разметку для проверки state machine."""
    return {
        "criteria": {c: {"points":case["gold_criteria"][c], "quote":""} for c in CRITERIA_IDS},
        "score": sum(case["gold_criteria"].values()),
        "red_flags":case["expected_flags"],
        "uncertainty":"low", "abstained":False, "refused":False
    }


def main():
    parser=argparse.ArgumentParser(description="RAG v2: эталонные ответы, evaluation и уточнения")
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--mock", action="store_true")
    mode.add_argument("--prepare", metavar="CASE_ID")
    mode.add_argument("--live", nargs="?", const="all", metavar="CASE_ID")
    mode.add_argument("--search", metavar="QUERY")
    args=parser.parse_args()
    cases=read_data("eval_cases.json")
    if args.list:
        print("Тестовые кейсы:")
        for c in cases:
            print(f'{c["id"]}: {c["category"]} — ожидаем {c["gold_score"][0]}..{c["gold_score"][1]}/10')
    elif args.mock:
        print("OFFLINE: ручная эталонная разметка; это НЕ проверка качества LLM!\n")
        for case in cases:
            result=result_for_mock(case)
            action=decide_next(result, {"followups_asked":0})
            assert action["action"] == case["expected_next_action"]
            print(f'{case["id"]}: gold={result["score"]}/10, action={action["action"]}, focus={action.get("target", "-")}')
    elif args.prepare:
        case=next((c for c in cases if c["id"] == args.prepare), None)
        if not case:
            parser.error("unknown CASE_ID")
        print(json.dumps(build_messages(case["answer"]), ensure_ascii=False, indent=2))
    elif args.search:
        print(json.dumps(retrieve(args.search), ensure_ascii=False, indent=2))
    elif args.live:
        chosen=cases if args.live == "all" else [c for c in cases if c["id"] == args.live]
        if not chosen:
            parser.error("unknown CASE_ID")
        matched=0
        results=[]
        for case in chosen:
            result=evaluate(case["answer"])
            if result.get("needs_review"):
                print(f'{case["id"]}: needs_review: refusal')
                results.append({"case_id":case["id"], "result":result})
                continue
            within=case["gold_score"][0] <= result["score"] <= case["gold_score"][1]
            matched+=int(within)
            action=decide_next(result, {"followups_asked":0})
            print(f'{case["id"]}: {result["score"]}/10, expected={case["gold_score"]}, in_range={within}, next={action["action"]}, flags={result["red_flags"]}')
            results.append({"case_id":case["id"], "result":result, "next":action, "in_range":within})
        from pathlib import Path
        dest=Path("live_eval_results.json")
        dest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWithin expected range: {matched}/{len(chosen)}; results: {dest}")


if __name__ == "__main__":
    main()
