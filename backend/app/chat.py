from time import perf_counter
from app import model_provider
import httpx
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.contracts import RunReceipt, RunRecord, TraceGroup, TraceRecord
from app.agent import graph
from app.db import engine
from app.events import publish
from app.storage import emit, journey, packed
from app.tools import CATALOG

router = APIRouter(prefix="/api")


class Prompt(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1,max_length=1000)
    plan_id: UUID | None = None


def run(cmd, run_id, goal, memory):
    start = perf_counter()
    state = "complete"
    try:
        output = graph.invoke({"session":str(cmd.session_id),"run":str(run_id),"goal":goal,
                               "prompt":cmd.message,"memory":memory})
        answer, memory = output["answer"],output["memory"]
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Agent 실행 실패")
        state,answer = "failed","실행이 중단됐습니다. 조건을 확인하고 다시 시도하세요."
    publish(cmd.session_id,run_id,"run.finish",{"ms":round((perf_counter()-start)*1000),"state":state})
    with engine.begin() as c:
        c.execute(text("UPDATE chat_session SET memory=CAST(:m AS jsonb) WHERE id=:id"),
                  {"m":packed(memory),"id":cmd.session_id})
        c.execute(text("UPDATE chat_run SET state=:s,answer=:a WHERE id=:id"),
                  {"id":run_id,"s":state,"a":answer})
        emit(c,"run.done",{"run_id":str(run_id),"session_id":str(cmd.session_id),"state":state})


@router.get("/tools")
def catalog():
    return CATALOG


@router.post("/chat/runs",status_code=202,response_model=RunReceipt)
def submit(cmd: Prompt, background: BackgroundTasks):
    run_id = uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO chat_session(id) VALUES (:id) ON CONFLICT DO NOTHING"),{"id":cmd.session_id})
        memory = c.execute(text("SELECT memory FROM chat_session WHERE id=:id FOR UPDATE"),{"id":cmd.session_id}).scalar_one()
        running = c.execute(text("SELECT 1 FROM chat_run WHERE session_id=:s AND state='running'"),
                            {"s":cmd.session_id}).first()
        if running:
            raise HTTPException(409,"이전 응답을 기다려 주세요.")
        gid = str(cmd.plan_id) if cmd.plan_id else memory.get("plan_id")
        goal = {}
        if gid:
            candidate,_ = journey(c,gid)
            if not candidate["deleted"]:
                goal = candidate
                if memory.get("plan_id") != gid:
                    memory = {"plan_id":gid}
        prior = c.execute(text("""SELECT kind,payload,run_id FROM trace WHERE run_id=(
            SELECT id FROM chat_run WHERE session_id=:s ORDER BY created_at DESC LIMIT 1)
            ORDER BY seq"""),{"s":cmd.session_id}).mappings().all()
        audit = evaluate(prior)
        memory["previous_audit"] = audit[0]["status"] if audit else None
        c.execute(text("INSERT INTO chat_run(id,session_id,prompt,state) VALUES (:id,:s,:p,'running')"),
                  {"id":run_id,"s":cmd.session_id,"p":cmd.message})
    background.add_task(run,cmd,run_id,goal,memory)
    return {"id":run_id,"state":"running"}


@router.get("/chat/sessions/{session_id}",response_model=list[RunRecord])
def history(session_id: UUID):
    with engine.connect() as c:
        return c.execute(text("SELECT * FROM chat_run WHERE session_id=:s ORDER BY created_at"),
                         {"s":session_id}).mappings().all()


@router.get("/chat/runs/{run_id}",response_model=RunRecord)
def get_run(run_id: UUID):
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM chat_run WHERE id=:r"),{"r":run_id}).mappings().first()
        if not row:
            raise HTTPException(404)
        return row


@router.get("/logs",response_model=list[TraceGroup])
def logs():
    with engine.connect() as c:
        return c.execute(text("""SELECT session_id, count(*) AS events, max(created_at) AS updated
            FROM trace GROUP BY session_id ORDER BY updated DESC""")).mappings().all()


@router.get("/logs/{session_id}",response_model=list[TraceRecord])
def traces(session_id: UUID):
    with engine.connect() as c:
        return c.execute(text("SELECT * FROM trace WHERE session_id=:s ORDER BY seq"),
                         {"s":session_id}).mappings().all()


def evaluate(rows):
    # Each run has its own execution plan and replan budget.
    verdicts = []
    groups = {}
    for row in rows:
        groups.setdefault(str(row["run_id"]),[]).append(row)
    for rid,events in groups.items():
        planned,seen,warnings = set(),set(),set()
        retries = 0
        for row in events:
            k,p = row["kind"],row["payload"]
            if k=="plan":
                planned.update(p["tools"])
            if k=="tool.request":
                sig = (p["name"],packed(p["args"]))
                if sig in seen:
                    warnings.add("동일 입력 반복 호출")
                if p["name"] not in planned:
                    warnings.add("계획 밖 Tool 호출")
                seen.add(sig)
            if k=="replan":
                retries += 1
        if retries>2:
            warnings.add("재계획 상한 초과")
        complete = any(e["kind"]=="run.finish" and e["payload"].get("state")=="complete" for e in events)
        has_decision = any(e["kind"]=="decision" for e in events)
        status = "이상" if warnings else ("정상" if complete and has_decision else "판정 보류")
        verdicts.append({"run_id":rid,"status":status,"warnings":sorted(warnings)})
    return verdicts


@router.get("/logs/{session_id}/evaluation")
def evaluation(session_id: UUID):
    return {"runs":evaluate(traces(session_id))}


def diagnose(verdict):
    if verdict["status"]!="이상":
        return {"state":"skipped"}
    if not model_provider.configured():
        return {"state":"unconfigured"}
    try:
        result=model_provider.request_model("다음 실행 이상 징후의 가능한 원인과 점검 방법을 한국어 두 문장으로 설명하세요.",", ".join(verdict["warnings"]))
        if not isinstance(result,str) or not result.strip():
            raise ValueError()
        return {"state":"complete","text":result[:1000]}
    except (httpx.HTTPError,ValueError,IndexError,KeyError,TypeError):
        return {"state":"unavailable"}


@router.post("/logs/{session_id}/diagnosis")
def diagnosis(session_id: UUID):
    return {"runs":[{**v,"diagnosis":diagnose(v)} for v in evaluate(traces(session_id))]}


@router.delete("/logs/{session_id}")
def delete_trace(session_id: UUID):
    with engine.begin() as c:
        if c.execute(text("SELECT 1 FROM chat_run WHERE session_id=:s AND state='running'"),{"s":session_id}).first():
            raise HTTPException(409,"실행 완료 후 삭제하세요.")
        count = c.execute(text("DELETE FROM trace WHERE session_id=:s"),{"s":session_id}).rowcount
    return {"deleted_events":count}
