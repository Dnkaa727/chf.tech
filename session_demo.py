"""Демо памяти и ветвления БЕЗ вызова LLM."""
from main import result_for_mock
from src.core import read_data
from src.session import InterviewSession


def run_demo():
    s=InterviewSession()
    cases=read_data("eval_cases.json")
    case=next(c for c in cases if c["id"] == "T04_partial")
    print("Тема:",s.topic_id)
    print("Q1:",s.pending_question)
    d=s.record_answer(case["answer"],result_for_mock(case))
    print("A1 (сокр.):",case["answer"][:100]+"...")
    print("Действие:",d["action"],"->",d.get("target"))
    print("Q2:",s.pending_question)
    # Следующий ответ синтетический: добавляет доказанные навыки index и verification.
    followup="Если фильтр избирателен, проверю B-Tree индекс по полям WHERE и учту место и цену записи. Потом сравню реальные планы и latency до/после при типичной нагрузке."
    mock=result_for_mock(case)
    mock["criteria"]["index"]={"points":2,"quote":"Если фильтр избирателен"}
    mock["criteria"]["verification"]={"points":2,"quote":"сравню реальные планы и latency до/после"}
    mock["score"]=4
    d=s.record_answer(followup,mock)
    print("A2:",followup)
    print("Итоговые баллы:",sum(x["points"] for x in s.criterion_evidence.values()))
    print("Решение:",d["action"], "| история ответов:",len(s.transcript))
    print("ВАЖНО: баллы тут ручные, это тестирование логики, не LLM.")


if __name__=="__main__":
    run_demo()
