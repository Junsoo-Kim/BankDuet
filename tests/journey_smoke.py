"""Separate Compose environment. Creates only synthetic test data on loopback."""
import argparse
import json
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import requests


def exercise(port, evidence_dir):
    base = f"http://127.0.0.1:{port}"
    client = requests.Session()
    client.trust_env = False
    cases = []
    started = monotonic()

    def call(bank,method,path,body=None,expected=200):
        resp = client.request(method,f"{base}/{bank}/api/{path}",json=body,timeout=9)
        if resp.status_code != expected:
            raise AssertionError(f"{method} {path}: {resp.status_code} {resp.text[:350]}")
        return resp.json()

    def check(label, condition, actual):
        if not condition:
            raise AssertionError(f"{label}: {actual}")
        cases.append({"case":label,"actual":actual,"passed":True})

    def wait_for(fn):
        end = monotonic()+18
        while monotonic()<end:
            value = fn()
            if value:
                return value
            sleep(.12)
        raise AssertionError("조건 대기 시간 초과")

    for bank in ("kb","b"):
        call(bank,"POST","session")
    p = call("kb","POST","plans",{"mode":"auto","title":"통합 시험 "+uuid4().hex[:5]},201)
    gid = p["id"]
    path = "plans/"+gid
    def plan(bank):
        return call(bank,"GET",path)
    def until(bank,predicate):
        return wait_for(lambda: next((x for x in call(bank,"GET","plans") if x["id"]==gid and predicate(x)),None))
    until("b",lambda x:x["status"]=="invited")
    call("b","POST",path+"/consent",{"mode":"auto"})
    p = until("kb",lambda x:x["forecast"] is not None)
    version = p["version"]
    check("V01 initial",p["forecast"]["projected"]==10**9,p["forecast"])
    ledger=p["private"]["savings_history"]
    check("mock savings baseline",sum(x["amount"] for x in ledger)//len(ledger)==p["private"]["monthly"],ledger)
    points=call("kb","GET",path+"/trajectory")["forecast"]["milestones"]
    check("monthly trajectory",len(points)==121 and points[-1]["progress_pct"]==100,points[-1])
    until("b",lambda x:x["version"]==version)
    def decision(bank,v,choice,status=200):
        return call(bank,"POST",f"{path}/versions/{v}/decisions",{"choice":choice},status)
    decision("kb",version,"approve")
    check("V07 single approval",plan("kb")["confirmed"] is None, plan("kb")["votes"])
    decision("b",version,"approve")
    until("kb",lambda x:x["status"]=="confirmed")
    until("b",lambda x:x["status"]=="confirmed")
    item = {"id":str(uuid4()),"amount":10000000,"note":"개인 지출 사유"}
    call("b","POST",path+"/expenses",item)
    call("b","POST",path+"/expenses",item)
    p = until("kb",lambda x:x["forecast"]["gap"]==10000000)
    check("V06 expense and privacy",p["forecast"]["needed_months"]==122 and item["note"] not in json.dumps(p,ensure_ascii=False),p["forecast"])
    call("b","POST",path+"/expenses/"+item["id"]+"/post")
    check("V06b reconciled",plan("b")["private"]["balance"]==195000000 and plan("kb")["forecast"]["gap"]==10000000,plan("b")["private"]["balance"])
    decision("kb",version,"approve",409)
    sid = str(uuid4())
    def ask(prompt):
        t = monotonic()
        r = call("kb","POST","chat/runs",{"session_id":sid,"plan_id":gid,"message":prompt},202)
        receipt = round((monotonic()-t)*1000)
        done = wait_for(lambda: next((x for x in call("kb","GET","chat/sessions/"+sid) if x["id"]==r["id"] and x["state"]!="running"),None))
        if done["state"]!="complete":
            raise AssertionError(done)
        logs = [x for x in call("kb","GET","logs/"+sid) if str(x["run_id"])==r["id"]]
        timings.append({"prompt":prompt,"accepted_ms":receipt,"complete_ms":round((monotonic()-t)*1000),
            "tool_ms":sum(e["payload"]["ms"] for e in logs if e["kind"]=="tool.result"),
            "llm_calls":sum(e["payload"].get("mode")=="llm" for e in logs)})
        return done["answer"],logs,round((monotonic()-t)*1000)
    timings=[]
    a,events,elapsed = ask("월 한도 유지, 기간 연장 허용하면 언제 달성해?")
    check("V02 replan", "122" in a and sum(x["kind"]=="replan" for x in events)==1,{"answer":a,"ms":elapsed})
    representative = events
    a,events,elapsed = ask("같은 조건에서 기간 고정")
    check("V03 limit",sum(x["kind"]=="replan" for x in events)==2,{"answer":a,"ms":elapsed})
    a,events,elapsed = ask("사용법")
    check("V05 no tools",not any(x["kind"]=="tool.request" for x in events),{"answer":a,"ms":elapsed})
    a,events,elapsed = ask("영통에서 상담할 지점")
    check("V04 branch response",any(x["kind"]=="tool.result" for x in events),{"answer":a,"ms":elapsed})
    a,events,elapsed = ask("내 계좌 잔액")
    check("account detail","205,000,000" in a,a)
    v = until("b",lambda x:x["forecast"]["gap"]==10000000)["version"]
    decision("b",v,"extend")
    s = until("kb",lambda x:x["months"]==122)
    until("b",lambda x:x["version"]==s["version"])
    decision("b",s["version"],"approve")
    until("kb",lambda x:"b" in x["votes"])
    decision("kb",s["version"],"approve")
    until("b",lambda x:x["status"]=="confirmed")
    check("V07 new confirmed version",plan("b")["confirmed"]["months"]==122,plan("b")["version"])
    call("b","POST",path+"/consent",{"mode":"once"})
    p=until("kb",lambda x:x["version"]>s["version"])
    call("b","POST",path+"/expenses",{"id":str(uuid4()),"amount":100,"note":"1회 동의"})
    sleep(1.3)
    check("V06 one-time consent",plan("kb")["version"]==p["version"],plan("kb")["version"])
    call("b","POST",path+"/consent",{"mode":"revoked"})
    until("kb",lambda x:"b" not in x["shares"])
    decision("kb",p["version"],"approve",409)
    ap = {"title":"상담 준비","starts_at":"2030-04-01T09:00:00+09:00","ends_at":"2030-04-01T10:00:00+09:00"}
    one = call("kb","POST","appointments",ap,201)["appointment"]["id"]
    two = call("kb","POST","appointments",ap,201)
    check("V08 conflicting appointment",any(x["id"]==one for x in two["conflicts"]),len(two["conflicts"]))
    call("kb","PUT","appointments/"+one,{**ap,"title":"수정한 상담"})
    call("kb","GET","appointments/"+one)
    for item_id in [one,two["appointment"]["id"]]:
        call("kb","DELETE","appointments/"+item_id)
    check("V08 session isolation",not call("b","GET","logs/"+sid),[])
    evaluation = call("kb","GET",f"logs/{sid}/evaluation")
    check("normal trace",all(r["status"]=="정상" for r in evaluation["runs"]),evaluation)
    call("kb","DELETE","logs/"+sid)
    check("V08 log deletion",not call("kb","GET","logs/"+sid),[])
    call("b","POST",path+"/consent",{"mode":"auto"})
    until("kb",lambda x:"b" in x["shares"])
    call("kb","PUT",path+"/budget",{"reserve":5000000,"monthly":3000000})
    call("kb","POST",path+"/missed",{"month":1})
    posted=call("kb","POST",path+"/deposits",{"month":1,"amount":2500000})
    again=call("kb","POST",path+"/deposits",{"month":1,"amount":2500000})
    check("deposit replay and missed correction",posted["private"]["balance"]==again["private"]["balance"]==207500000 and not again["private"]["missed"],again["private"]["deposits"])
    call("kb","POST",path+"/missed",{"month":1},409)
    check("prior approvals retained",len(again["history"])==2,[x["months"] for x in again["history"]])
    call("kb","DELETE",path)
    wait_for(lambda: all(x["id"]!=gid for x in call("b","GET","plans")))
    result = {"cases":cases,"timings":timings,"total_ms":round((monotonic()-started)*1000),"representative_replan":representative}
    if evidence_dir:
        evidence_dir.mkdir(exist_ok=True,parents=True)
        (evidence_dir/"openapi.json").write_text(json.dumps(call("kb","GET","openapi.json"),ensure_ascii=False,indent=2),encoding="utf-8")
        (evidence_dir/"journey-smoke.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"PASS {len(cases)} checks / {result['total_ms']}ms")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=18474)
    parser.add_argument("--evidence-dir",type=Path)
    args=parser.parse_args()
    exercise(args.port,args.evidence_dir)
