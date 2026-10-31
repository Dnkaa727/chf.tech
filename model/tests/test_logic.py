import unittest
from src.core import read_data, retrieve, decide_next, verify_model_output, merge_evidence, CRITERIA_IDS
from main import result_for_mock

class RAGV2Tests(unittest.TestCase):
    def test_six_cases_exist(self):
        cases=read_data("eval_cases.json")
        self.assertEqual(len(cases),6)
        self.assertEqual(len({x["id"] for x in cases}),6)
    def test_mock_labels_in_score_bands(self):
        for case in read_data("eval_cases.json"):
            score=result_for_mock(case)["score"]
            self.assertLessEqual(case["gold_score"][0],score)
            self.assertGreaterEqual(case["gold_score"][1],score)
    def test_retrieval(self):
        self.assertEqual(retrieve("индексы", competency="PostgreSQL")[0]["id"],"pg_slow_query")
        self.assertEqual(retrieve("asyncio")[0]["id"],"py_asyncio")
    def test_6_expected_decisions(self):
        for case in read_data("eval_cases.json"):
            self.assertEqual(decide_next(result_for_mock(case), {"followups_asked":0})["action"],case["expected_next_action"])
    def test_followup_limit(self):
        case=read_data("eval_cases.json")[0]
        self.assertEqual(decide_next(result_for_mock(case), {"followups_asked":2})["action"],"insufficient_evidence")
    def test_refusal(self):
        case=read_data("eval_cases.json")[0]
        mock=result_for_mock(case);mock["refused"]=True
        self.assertEqual(decide_next(mock,{"followups_asked":0})["action"],"next_topic")
    def test_high_uncertainty(self):
        case=read_data("eval_cases.json")[0]
        mock=result_for_mock(case);mock["uncertainty"]="high"
        self.assertEqual(decide_next(mock,{"followups_asked":0})["action"],"needs_review")
    def test_quote_validation(self):
        output={"criteria":{c:{"points":2,"quote":"Существующая цитата"} for c in CRITERIA_IDS},"red_flags":[],"uncertainty":"low"}
        result=verify_model_output(output,"Несуществующий ответ")
        self.assertEqual(result["score"],0)
        self.assertEqual(len(result["warnings"]),5)
    def test_real_quote(self):
        output={"criteria":{c:{"points":0,"quote":""} for c in CRITERIA_IDS},"red_flags":[]}
        output["criteria"]["plan"]={"points":2,"quote":"Seq Scan"}
        self.assertEqual(verify_model_output(output,"Я посмотрю Seq Scan")["score"],2)
    def test_merge(self):
        old={c:{"points":0,"quote":""} for c in CRITERIA_IDS}
        new={c:{"points":0,"quote":""} for c in CRITERIA_IDS}
        old["diagnosis"]={"points":2,"quote":"A"};new["index"]={"points":2,"quote":"B"}
        self.assertEqual(sum(x["points"] for x in merge_evidence(old,new).values()),4)

if __name__=="__main__":
    unittest.main()

class SessionTests(unittest.TestCase):
    def test_session_2_turns(self):
        from src.session import InterviewSession
        cases=read_data("eval_cases.json")
        case=next(x for x in cases if x["id"]=="T04_partial")
        s=InterviewSession()
        action=s.record_answer(case["answer"],result_for_mock(case))
        self.assertEqual(action["target"],"index")
        next_eval=result_for_mock(case)
        next_eval["criteria"]["index"]={"points":2,"quote":"Индекс"}
        next_eval["criteria"]["verification"]={"points":2,"quote":"Время"}
        action=s.record_answer("Индекс и Время",next_eval)
        self.assertEqual(action["action"],"next_topic")
        self.assertEqual(len(s.transcript),2)

    def test_bad_loop_stops(self):
        from src.session import InterviewSession
        case=read_data("eval_cases.json")[0]
        s=InterviewSession()
        actions=[]
        for i in range(3):
            actions.append(s.record_answer(case["answer"], result_for_mock(case))["action"])
        self.assertEqual(actions,["followup","followup","insufficient_evidence"])

class APISchemaTests(unittest.TestCase):
    def test_real_client_payload_with_mock_response(self):
        from unittest.mock import patch
        from src.llm_eval import evaluate
        import json
        output={
            "criteria":{c:{"points":0,"quote":""} for c in CRITERIA_IDS},
            "red_flags":[],"uncertainty":"low","refused":False,
            "abstained":False,"feedback":"ok"
        }
        output["criteria"]["diagnosis"]={"points":2,"quote":"EXPLAIN"}
        class FakeResponse:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,*a):return json.dumps({"choices":[{"message":{"content":json.dumps(output)}}]}).encode()
        with patch('urllib.request.urlopen', return_value=FakeResponse()) as mocked:
            with patch.dict('os.environ',{"OPENAI_API_KEY":"test_local","LLM_MODEL":"gpt-4o-mini"}):
                result=evaluate("Я проверю EXPLAIN")
        self.assertEqual(result["score"],2)
        self.assertEqual(mocked.call_count,1)
        body=json.loads(mocked.call_args.args[0].data)
        self.assertEqual(body["response_format"]["type"],"json_schema")
        self.assertEqual(body["model"],"gpt-4o-mini")

    def test_overcredit_redflag_escalation(self):
        c=read_data("eval_cases.json")[5]
        eval_=result_for_mock(c)
        eval_["score"]=9
        self.assertEqual(decide_next(eval_,{"followups_asked":0})["action"],"needs_review")
