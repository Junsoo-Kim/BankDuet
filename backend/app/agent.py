"""LangGraph stages and deterministic financial decision rules."""
import json
from app import model_provider
import re
from time import perf_counter
from typing import TypedDict

import httpx
from langgraph.graph import StateGraph, START, END

from app import tools
from app.events import publish
from app.finance import forecast
from app.db import bank_id


class State(TypedDict, total=False):
    session: str
    run: str
    prompt: str
    goal: dict
    memory: dict
    intent: str
    reason: str
    plan: list
    results: dict
    retries: int
    answer: str


def note(s,kind,**payload):
    publish(s["session"],s["run"],kind,payload)


def observed(name, fn):
    def wrapped(s):
        note(s,"stage.enter",stage=name)
        start = perf_counter()
        values = fn(s)
        note(s,"stage.exit",stage=name,ms=round((perf_counter()-start)*1000))
        return values
    return wrapped


def analyze(s):
    prompt = s["prompt"]
    memory = dict(s["memory"])
    if any(w in prompt for w in ("지점","상담할","영업점")):
        intent = "branch"
    elif any(w in prompt for w in ("도움","사용법","안녕","어떻게 써")):
        intent = "help"
    elif any(w in prompt for w in ("계획","저축","목표","달성","모으","납입","같은 조건","기간","개월","언제","부족")):
        intent = "plan"
    elif any(w in prompt for w in ("계좌","잔액","출금","얼마")):
        intent = "account"
    else:
        intent = "clarify"
    match = re.search(r"([가-힣]{2,12})(?:에서| 근처| 주변)", prompt)
    if match:
        memory["region"] = match.group(1)
    if "한도 유지" in prompt or "납입액 유지" in prompt:
        memory["fixed_monthly"] = True
    if "연장 가능" in prompt or "연장 허용" in prompt:
        memory["allow_extend"] = True
    if "연장 불가" in prompt or "기간 고정" in prompt:
        memory["allow_extend"] = False
    if intent=="clarify" and memory.get("await_region") and re.fullmatch(r"[가-힣 ]{2,24}",prompt.strip()):
        memory["region"]=prompt.strip()
        intent="branch"
    memory["await_region"]=intent=="branch" and not memory.get("region")
    if intent=="plan":
        period=re.search(r"(\d{1,3})\s*개월",prompt)
        payment=re.search(r"(?:매월|월(?:\s*납입액)?)\s*(\d[\d,]*)\s*(만)?\s*원",prompt)
        if period and 1<=int(period[1])<=600:
            memory["scenario_months"]=int(period[1])
        if payment:
            amount=int(payment[1].replace(",",""))*(10000 if payment[2] else 1)
            if amount<=10**13:
                memory["scenario_monthly"]=amount
    memory["last_intent"] = intent
    reason = {"branch":"상담 위치 요청","help":"서비스 사용법","plan":"기간·납입 조건 검토",
              "account":"계좌 정보 요청","clarify":"목적 확인 필요"}[intent]
    note(s,"decision",intent=intent,reason=reason,mode="local_rules")
    return {"intent":intent,"reason":reason,"memory":memory,"retries":0}


def choose(s):
    intent = s["intent"]
    if s["memory"].get("previous_audit")=="이상":
        note(s,"decision",mode="local_fallback",reason="직전 실행의 이상 판정에 따라 등록된 로컬 계획으로 재검토")
    wanted = {"branch":["search_branches"],"plan":["list_accounts","read_balance"],
              "account":["list_accounts","read_balance"]}.get(intent,[])
    if intent=="branch" and any(word in s["prompt"] for word in ("잔액","계좌")):
        wanted=["list_accounts","read_balance","search_branches"]
    if intent == "branch" and not s["memory"].get("region"):
        return {"plan":[],"answer":"어느 지역에서 상담할 지점을 찾아볼까요?"}
    if intent == "plan" and not s["goal"]:
        return {"plan":[],"answer":"검토할 공동 목표를 먼저 선택해 주세요."}
    if s["memory"].get("previous_audit")!="이상" and intent in ("clarify","plan","account","branch") and model_provider.configured():
        try:
            began=perf_counter()
            selected=model_provider.request_model("질문에 필요한 첫 조회 Tool을 고르세요.",s["prompt"],tools.CATALOG)
            matched = bool(wanted and selected == wanted[0])
            if intent=="clarify" and selected in ("list_accounts","read_balance"):
                intent,wanted,matched="account",["list_accounts","read_balance"],True
            note(s,"decision",mode="llm",selected=selected,accepted=matched,
                 ms=round((perf_counter()-began)*1000),
                 reason="입력 선행 조건과 고객 요청에 맞는 첫 Tool 검사")
        except (ValueError,httpx.HTTPError,KeyError,IndexError,TypeError):
            note(s,"decision",mode="local_fallback",reason="모델 응답을 확인할 수 없어 로컬 계획 사용")
    note(s,"plan",tools=wanted)
    return {"plan":wanted,"intent":intent}


def execute(s):
    results = {}
    def invoke(name,args):
        note(s,"tool.request",name=name,args=args)
        start = perf_counter()
        result = tools.call(name,args)
        note(s,"tool.result",name=name,result=result,ms=round((perf_counter()-start)*1000))
        return result
    for name in s["plan"]:
        args = {}
        if name == "read_balance":
            listing = results["list_accounts"]
            if not listing["ok"] or not listing["data"]:
                continue
            ids=dict.fromkeys(a["account_id"] for a in listing["data"] if isinstance(a,dict) and isinstance(a.get("account_id"),str))
            balances=[invoke(name,{"account_id":key}) for key in ids]
            valid=[row["data"]["available"] for row in balances if row["ok"]]
            results[name]={"ok":bool(valid),"data":{"available":sum(valid)},"excluded":len(balances)-len(valid)}
            continue
        if name == "search_branches":
            args["region"] = s["memory"]["region"]
        results[name]=invoke(name,args)
    return {"results":results}


def judge(s):
    if s.get("answer"):
        return {}
    if s["intent"] == "help":
        return {"answer":"공동 목표를 만들고 상대 은행에서 초대를 수락하세요. 예상 달성일을 비교한 뒤 양쪽에서 같은 버전을 승인할 수 있어요."}
    if s["intent"] == "clarify":
        return {"answer":"계좌 잔액, 목표 달성일, 상담 지점 중 어떤 내용을 확인할까요?"}
    if s["intent"] == "branch":
        result = s["results"]["search_branches"]
        detail=s["results"].get("read_balance",{})
        prefix=f"모킹 계좌의 출금가능액은 {detail['data']['available']:,}원입니다.\n" if detail.get("ok") else ""
        if result["ok"]:
            return {"answer":prefix+"카카오 로컬 검색 결과\n"+"\n".join(f"{p['name']} · {p['address']} {p['url']}" for p in result["data"])}
        return {"answer":prefix+"지점 검색을 완료하지 못했습니다. "+{"MISSING_KEY":"카카오 REST 키 설정이 필요합니다.",
                "NO_RESULT":"해당 지역에 일치하는 결과가 없습니다."}.get(result["code"],"잠시 후 다시 조회하세요.")}
    balance = s["results"].get("read_balance",{})
    if not balance.get("ok"):
        return {"answer":"잔액을 확인할 수 없어 해당 계좌를 계산에서 보류합니다."}
    if s["intent"] == "account":
        return {"answer":f"모킹 계좌의 출금가능액은 {balance['data']['available']:,}원입니다. 비상금과 예정 지출은 목표별로 반영합니다."}
    g = dict(s["goal"])
    scenario=s["memory"]
    g["months"]=scenario.get("scenario_months",g["months"])
    if "scenario_monthly" in scenario and bank_id in g["shares"]:
        own=dict(g["shares"][bank_id])
        own["monthly"]=scenario["scenario_monthly"]
        g["shares"]={**g["shares"],bank_id:own}
    f = forecast(g)
    if not f:
        return {"answer":"상대 은행의 기여액 공유를 기다리고 있습니다."}
    if not f["gap"]:
        return {"answer":f"합의한 월 납입액 {f['monthly']:,}원 기준 {g['months']}회차 예상액은 {f['projected']:,}원입니다. 예상 달성일은 {f['achieve_date']}입니다."}
    if s["retries"] == 0:
        return {}
    if s["retries"] == 1 and s["memory"].get("allow_extend") and f["needed_months"] and f["needed_months"]<=600:
        return {"answer":f"현재 부족액은 {f['gap']:,}원입니다. 월 한도를 유지하면 {f['needed_months']}회차({f['achieve_date']})에 도달합니다. 기간 연장안을 양쪽 은행에서 검토하세요."}
    if s["retries"] == 1:
        return {}
    if f["extra_monthly"] is None:
        return {"answer":"남은 납입 회차가 없어 기존 기간 내 증액을 계산할 수 없습니다. 새 목표일을 지정해 주세요."}
    return {"answer":f"두 대안을 검토했습니다. 기존 날짜를 지키려면 월 합산 {f['extra_monthly']:,}원이 더 필요합니다. 증액 동의가 없어 자동 변경을 보류합니다. 기간 연장을 허용할까요?"}


def replan(s):
    n = s["retries"] + 1
    note(s,"replan",attempt=n,alternative="월 한도 유지 · 기간 연장" if n==1 else "기존 날짜 유지 · 필요 납입액 역산",
         reused=list(s["results"]))
    return {"retries":n}


def respond(s):
    answer = s["answer"]
    excluded=s.get("results",{}).get("read_balance",{}).get("excluded",0)
    if excluded:
        answer+=f"\n출금가능액을 확인하지 못한 계좌 {excluded}개는 합계에서 제외했습니다."
    if s["intent"] == "plan" and s["goal"]:
        if "scenario_monthly" in s["memory"] or "scenario_months" in s["memory"]:
            answer+="\n상담에서 입력한 조건으로 계산한 모의 결과이며 승인본은 그대로입니다."
        answer += "\n가상 계좌·공유 기여액 기준의 원금 추산입니다. 금융 전문가의 상담을 대신할 수 없습니다."
    return {"answer":answer,"memory":{**s["memory"],"last_answer":answer}}


def build_graph():
    graph = StateGraph(State)
    for name,fn in [("analyze",analyze),("choose",choose),("execute",execute),
                    ("judge",judge),("replan",replan),("respond",respond)]:
        graph.add_node(name,observed(name,fn))
    for a,b in [(START,"analyze"),("analyze","choose"),("choose","execute"),("execute","judge"),
                ("replan","judge"),("respond",END)]:
        graph.add_edge(a,b)
    graph.add_conditional_edges("judge",lambda s:"respond" if s.get("answer") else "replan",
                                ["respond","replan"])
    return graph.compile()


graph = build_graph()
