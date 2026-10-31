"""Необязательный модуль pgvector. Выполнять только при готовом Docker+Postgres и ключе embedding API.

Команды: python vector_store.py --index | --query 'индексы postgresql'
"""
import argparse
import json
import os
import urllib.request
from pathlib import Path
from src.core import read_data

DSN=os.getenv("POSTGRES_DSN","postgresql://rag:local_demo_only@127.0.0.1:5433/interview")
EMBED_MODEL=os.getenv("EMBEDDING_MODEL","text-embedding-3-small")
EMBED_DIM=1536  # Размер по умолчанию для text-embedding-3-small; согласуйте с выбранной моделью


def embedding(text):
    key=os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY required for embedding API")
    req=urllib.request.Request("https://api.openai.com/v1/embeddings",
        data=json.dumps({"model":EMBED_MODEL,"input":text}).encode(),
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req,timeout=60) as res:
        vec=json.load(res)["data"][0]["embedding"]
    if len(vec)!=EMBED_DIM:
        raise ValueError(f"Expected embedding dim {EMBED_DIM}, got {len(vec)}. Change SQL schema accordingly.")
    return "["+",".join(str(x) for x in vec)+"]"


def body(card):
    return f'{card["competency"]}. {card["topic"]}. {"; ".join(card["tags"])}. Вопрос: {card["question"]}'


def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--index",action="store_true")
    group.add_argument("--query")
    a=p.parse_args()
    try:
        import psycopg
    except ImportError as ex:
        raise SystemExit("Install optional requirements: py -m pip install -r requirements-vector.txt") from ex
    with psycopg.connect(DSN) as conn:
        if a.index:
            with conn.cursor() as cur:
                cur.execute((Path(__file__).parent/"sql/schema.sql").read_text(encoding="utf-8"))
                for c in read_data("knowledge_cards.json"):
                    vec=embedding(body(c))
                    cur.execute("""INSERT INTO knowledge_chunks
                        (id, competency, topic, level, body, source_urls, review_status, embedding)
                        VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::vector)
                        ON CONFLICT (id) DO UPDATE SET competency=excluded.competency,
                        topic=excluded.topic, level=excluded.level, body=excluded.body,
                        source_urls=excluded.source_urls, review_status=excluded.review_status,
                        embedding=excluded.embedding""",
                        (c["id"],c["competency"],c["topic"],c["level"],body(c),json.dumps(c["sources"]),c["review_status"],vec))
            print("Indexed",len(read_data("knowledge_cards.json")),"knowledge cards")
        else:
            vec=embedding(a.query)
            with conn.cursor() as cur:
                cur.execute("""SELECT id, competency, topic, 1-(embedding <=> %s::vector) AS similarity
                    FROM knowledge_chunks
                    ORDER BY embedding <=> %s::vector LIMIT 3""",(vec,vec))
                for row in cur.fetchall():
                    print(row)


if __name__=="__main__":
    main()
