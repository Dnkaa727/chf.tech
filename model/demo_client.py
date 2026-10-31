"""Пример интеграции backend → внутренний RAG API. Нужен запущенный uvicorn."""
import json
import urllib.request

BASE_URL="http://127.0.0.1:8000"

def post(path,payload):
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(BASE_URL+path, data=data, method="POST",
                               headers={"Content-Type":"application/json; charset=utf-8"})
    with urllib.request.urlopen(req,timeout=15) as response:
        return json.load(response)

results=post("/v1/retrieve",{"query":"медленный SQL запрос PostgreSQL", "limit":3})
print("Найденные темы:",json.dumps(results,ensure_ascii=False,indent=2))
if results["results"]:
    card_id=results["results"][0]["id"]
    result=post("/v1/question",{"card_id":card_id,"mode":"template"})
    print("\nВопрос:",result["question"])
    prompt=post("/v1/prepare",{"card_id":card_id,"task":"question"})
    print("\nГотово messages для ML:",json.dumps(prompt["messages"],ensure_ascii=False,indent=2)[:1500],"...")
