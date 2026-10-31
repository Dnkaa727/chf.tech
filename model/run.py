"""Single entry point for the knowledge-grounded interview service."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from rag.engine import (
    TopicSession,
    cases,
    gold_fixture,
    public_assessment,
    validate_data,
)
from rag.llm import LLMError, evaluate_live
from rag.registry import AmbiguousCardSelection, CardNotFound, get_registry

ROOT = Path(__file__).resolve().parent


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def mock_all():
    samples = cases()
    for sample in samples:
        session = TopicSession(sample["card_id"])
        result = session.add_assessment(sample["answer"], gold_fixture(sample))
        if result["action"] != sample["expected_next_action"]:
            raise RuntimeError(f"Unexpected decision for {sample['case_id']}")
    output({"fixtures_passed": len(samples), "live_model_called": False})


def interview(card_id):
    session = TopicSession(card_id)
    print("Введите exit для выхода. Оценка требует проверки человеком.")
    while session.status == "in_progress":
        print("\nВопрос:", session.pending_question)
        try:
            answer = input("Ответ: ").strip()
        except EOFError:
            break
        if answer.casefold() in ("exit", "quit"):
            break
        if not answer:
            continue
        assessment = evaluate_live(
            card_id,
            answer,
            question=session.pending_question,
            history=[
                {"question": row["question"], "answer": row["answer"]}
                for row in session.history[-3:]
            ],
            error_context=session.evaluation_context(),
            rubric=session.rubric,
        )
        if assessment.get("refusal") or assessment.get("abstained"):
            print("Модель не смогла оценить ответ. Нужна ручная проверка.")
            continue
        output(session.add_assessment(answer, assessment))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="RAG interviewer: search, evaluate and serve"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Validate the knowledge base and rubrics")
    commands.add_parser("test", help="Run the complete offline test suite")
    commands.add_parser("mock", help="Check all synthetic fixtures without an LLM")
    commands.add_parser("cards", help="List the public knowledge catalog")
    search = commands.add_parser(
        "search", help="Select a card by topic; report ambiguity"
    )
    search.add_argument("query")
    search.add_argument("--competency")
    evaluate = commands.add_parser(
        "evaluate", help="Evaluate an answer with the configured LLM"
    )
    evaluate.add_argument("card_id")
    evaluate.add_argument("--answer", required=True)
    interactive = commands.add_parser(
        "interview", help="Start an interactive interview with the LLM"
    )
    interactive.add_argument("card_id")
    serve = commands.add_parser("serve", help="Start the local HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            output(validate_data())
        elif args.command == "test":
            return subprocess.run(
                [sys.executable, "-m", "pytest", "-q"], cwd=ROOT
            ).returncode
        elif args.command == "mock":
            mock_all()
        elif args.command == "cards":
            output(get_registry().public_cards())
        elif args.command == "search":
            entry = get_registry().select(query=args.query, competency=args.competency)
            output({"card_id": entry.card["id"], "question": entry.card["question"]})
        elif args.command == "evaluate":
            output(public_assessment(evaluate_live(args.card_id, args.answer)))
        elif args.command == "interview":
            interview(args.card_id)
        elif args.command == "serve":
            import uvicorn

            uvicorn.run("app.api:app", host=args.host, port=args.port)
    except AmbiguousCardSelection as error:
        output(
            {
                "error": "Уточните тему или выберите card_id",
                "candidates": error.candidates,
            }
        )
        return 2
    except (CardNotFound, LLMError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
