"""Консольная демо-программа (stdlib). Запуск: py cli.py list|search|question|prepare|evaluate"""
from __future__ import annotations
import argparse,json
from app.kb import load_kb,get_card,public_metadata
from app.retrieval import retrieve
from app.interview import choose_question,evaluate_answer,prepare_messages


def output(result):
    print(json.dumps(result,ensure_ascii=False,indent=2))

def main():
    p=argparse.ArgumentParser(description="RAG: локальный поиск, подготовка контекста, опциональный вызов LLM")
    subs=p.add_subparsers(dest="command",required=True)
    subs.add_parser("list",help="Все карточки")
    sr=subs.add_parser("search",help="Поиск по смысловым тегам (без embeddings)")
    sr.add_argument("query",nargs="?",default="")
    sr.add_argument("--competency",default=None)
    sr.add_argument("--limit",type=int,default=3)
    for cmd in ("question","prepare","evaluate"):
        s=subs.add_parser(cmd)
        s.add_argument("--card-id",required=True)
        s.add_argument("--answer",default=None)
        if cmd=="question":s.add_argument("--mode",choices=["template","llm"],default="template")
        if cmd=="prepare":s.add_argument("--task",choices=["question","evaluate"],default="question")
    args=p.parse_args();cards=load_kb()
    if args.command=="list":
        return output([public_metadata(c) for c in cards])
    if args.command=="search":
        return output(retrieve(cards,args.query,args.competency,args.limit))
    card=get_card(cards,args.card_id)
    if card is None:p.error("Неизвестный card-id. Сначала вызови `list`.")
    if args.command=="question":
        return output(choose_question(card,args.answer,args.mode))
    if args.command=="prepare":
        return output({"card_id":card["id"],"messages":prepare_messages(card,args.answer,task=args.task)})
    if args.command=="evaluate":
        if not args.answer:p.error("Для evaluate необходимо --answer; также требуется LLM API")
        return output(evaluate_answer(card,args.answer))

if __name__=="__main__":main()
