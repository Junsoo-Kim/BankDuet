import os
import unittest
from datetime import timedelta
from unittest.mock import patch, Mock

import httpx
from fastapi import HTTPException
from app import agent, chat, events, finance, journeys, tools


class Rules(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ,{"GMS_KEY":"","LLM_API_KEY":"","KAKAO_REST_API_KEY":""}))
        self.p=finance.new_private()
        finance.renew(self.p)
        share=finance.contribution(self.p)
        self.goal={"title":"주택","start":"2026-01-31","months":120,"version":2,"votes":{},
                   "target":10**9,"shares":{"kb":share.copy(),"b":share.copy()},"status":"review","deleted":False}

    def test_actual_and_missed_installments(self):
        self.p["deposits"]={"1":2_000_000}
        self.p["balance"]+=2_000_000
        self.p["missed"]={"2":2_500_000}
        self.goal["shares"]["kb"]=finance.contribution(self.p)
        f=finance.forecast(self.goal)
        self.assertEqual((f["gap"],f["remaining_cycles"],f["extra_monthly"]),(3_000_000,118,25424))
        self.assertEqual(finance.date_after("2024-01-31",1),"2024-02-29")

    def test_no_monthly_and_goal_already_met(self):
        for s in self.goal["shares"].values(): s["monthly"]=0
        self.assertIsNone(finance.forecast(self.goal)["needed_months"])
        self.goal["target"]=1
        self.assertEqual(finance.forecast(self.goal)["needed_months"],0)

    def test_expired_snapshot_and_rejection(self):
        self.goal["shares"]["b"]["expires"]=(finance.now()-timedelta(seconds=1)).isoformat()
        with self.assertRaises(HTTPException): journeys.apply_decision(self.goal,2,"kb","approve")
        self.goal["shares"]["b"]["expires"]=self.p["expires"]
        journeys.apply_decision(self.goal,2,"kb","reject")
        self.assertEqual(self.goal["status"],"rejected")

    def test_malformed_and_failed_account(self):
        for data in ({},{"available_amt":"-1"},{"available_amt":"１２３"}):
            with patch.object(tools,"read_balance",return_value=data):
                self.assertEqual(tools.call("read_balance",{"account_id":"k"})["code"],"MISSING_AMOUNT")
        with patch.object(tools,"read_balance",side_effect=TimeoutError):
            self.assertEqual(tools.call("read_balance",{"account_id":"k"})["code"],"UPSTREAM_ERROR")

    def test_partial_success_and_followup(self):
        with patch.dict(os.environ,{"LLM_API_KEY":"","KAKAO_REST_API_KEY":""}),patch.object(agent,"note"):
            g=lambda prompt,mem: agent.graph.invoke({"session":"s","run":"r","goal":self.goal,"prompt":prompt,"memory":mem})
            self.assertIn("어느 지역",g("상담할 지점",{})["answer"])
            self.assertIn("키",g("영통",{"await_region":True})["answer"])
            both=g("내 잔액과 영통에서 상담할 지점",{})["answer"]
            self.assertTrue("205,000,000" in both and "키" in both)
            prev=g("월 300만원 납입 목표",{})
            self.assertIn("5,500,000",g("같은 조건 121개월",prev["memory"])["answer"])

    def test_logger_unavailable(self):
        with patch.object(events,"subscribers",[Mock(side_effect=RuntimeError)]),patch.object(events,"engine"),patch.object(events,"emit"):
            result=agent.graph.invoke({"session":"s","run":"r","goal":{},"prompt":"사용법","memory":{}})
            self.assertIn("승인",result["answer"])

    def test_partial_balance_and_duplicate_candidate(self):
        from app.mock_accounts import registered_id
        candidates={"rsp_code":"A0000","res_list":[{"account_id":k} for k in (registered_id,"missing",registered_id)]}
        with patch.dict(os.environ,{"LLM_API_KEY":""}),patch.object(tools,"list_accounts",return_value=candidates),patch.object(agent,"note"):
            result=agent.graph.invoke({"session":"s","run":"r","goal":{},"prompt":"내 계좌 잔액","memory":{}})
            self.assertIn("205,000,000",result["answer"])
            self.assertIn("1개는 합계에서 제외",result["answer"])

    def test_model_selects_account_tool_for_ambiguous_prompt(self):
        cfg={"LLM_CHAT_URL":"https://test.invalid","LLM_MODEL":"mock","LLM_API_KEY":"test"}
        with patch.dict(os.environ,cfg),patch.object(agent,"note"),patch.object(agent.httpx,"post") as provider:
            provider.return_value.json.return_value={"choices":[{"message":{"tool_calls":[{"function":{"name":"list_accounts"}}]}}]}
            result=agent.graph.invoke({"session":"s","run":"r","goal":{},"prompt":"지금 인출 가능한 돈","memory":{}})
            self.assertIn("205,000,000",result["answer"])
            self.assertEqual(provider.call_args.kwargs["json"]["tool_choice"],"auto")
            provider.reset_mock()
            agent.graph.invoke({"session":"s","run":"r","goal":{},"prompt":"내 계좌 잔액","memory":{"previous_audit":"이상"}})
            provider.assert_not_called()

    def test_gms_responses(self):
        from app import model_provider
        with patch.dict(os.environ,{"GMS_KEY":"fixture"}),patch.object(model_provider.httpx,"post") as post:
            post.return_value.json.return_value={"output":[{"type":"function_call","name":"search_branches"}]}
            self.assertEqual(model_provider.request_model("도구 선택","영통 지점",tools.CATALOG),"search_branches")
            body=post.call_args.kwargs["json"]
            self.assertEqual((body["model"],body["input"]),("gpt-6.1-sol","영통 지점"))
            self.assertIn("name",body["tools"][0])
            self.assertTrue(post.call_args.args[0].endswith("/v1/responses"))
            post.return_value.json.return_value={"output":[{"type":"message","content":[{"type":"output_text","text":"진단 결과"}]}]}
            self.assertEqual(model_provider.request_model("진단","경고"),"진단 결과")

    def test_places_provider_contract(self):
        with patch.dict(os.environ,{"KAKAO_REST_API_KEY":"test"}),patch.object(tools.httpx,"get") as provider:
            provider.return_value.json.return_value={"documents":[]}
            self.assertEqual(tools.call("search_branches",{"region":"영통"})["code"],"NO_RESULT")
            provider.return_value.json.return_value={"documents":[{"place_name":"KB국민은행 합성 지점","address_name":"가상 주소","place_url":"https://example.invalid/place"}]}
            result=tools.call("search_branches",{"region":"영통"})
            self.assertEqual(result["data"][0]["address"],"가상 주소")
            self.assertEqual(provider.call_args.kwargs["params"]["category_group_code"],"BK9")

    def test_anomaly_diagnosis(self):
        def row(kind,**payload):return {"run_id":"r","kind":kind,"payload":payload}
        self.assertEqual(chat.evaluate([row("stage.enter")])[0]["status"],"판정 보류")
        bad=chat.evaluate([row("plan",tools=[]),*[row("replan")]*3,*[row("tool.request",name="x",args={})]*2])[0]
        self.assertEqual(len(bad["warnings"]),3)
        with patch.dict(os.environ,{"LLM_CHAT_URL":"https://test.invalid","LLM_MODEL":"mock","LLM_API_KEY":"test"}),patch.object(chat.httpx,"post",side_effect=httpx.ConnectError("offline")) as call:
            self.assertEqual(chat.diagnose({"status":"정상"})["state"],"skipped")
            call.assert_not_called()
            self.assertEqual(chat.diagnose(bad)["state"],"unavailable")
            self.assertEqual(bad["status"],"이상")
            call.side_effect=None
            call.return_value.json.return_value={"choices":[{"message":{"content":"반복된 요청을 확인하세요."}}]}
            self.assertEqual(chat.diagnose(bad)["state"],"complete")
