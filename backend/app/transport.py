"""Durable bank-to-bank delivery over the A2A v1 HTTP+JSON binding."""
import asyncio
import hmac
import json
from datetime import datetime
import os
from uuid import UUID, NAMESPACE_URL, uuid5

import httpx
from a2a import types
from fastapi import APIRouter, Header, HTTPException, Request
from google.protobuf.json_format import MessageToDict, ParseDict
from sqlalchemy import text

from app.db import bank_id, engine
from app.finance import new_private, now
from app.journeys import apply_decision, apply_share, broadcast, changed, peer
from app.storage import emit, journey, new_row, packed

router = APIRouter()
remote = f"http://{peer}-api:8000"
secret = os.environ["BANK_PEER_SECRET"]
SKILL = "coordinate-goal"


def auth(value):
    if not hmac.compare_digest(value, "Bearer " + secret):
        raise HTTPException(403, "은행 간 자격을 확인하세요.")


@router.get("/internal/consent/{goal_id}", include_in_schema=False)
def consent_status(goal_id: UUID, authorization: str = Header("")):
    auth(authorization)
    with engine.connect() as c:
        s,p = journey(c,goal_id)
        valid = not s["deleted"] and p["consent"] in ("once","auto") and datetime.fromisoformat(p["expires"])>now()
        return {"valid":valid,"revision":p["revision"]}


@router.get("/.well-known/agent-card.json")
def card():
    agent = types.AgentCard(name=f"BankDuet {bank_id}", description="공동 목표 협의",
        version="1.0.0", default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        supported_interfaces=[types.AgentInterface(url=f"http://{bank_id}-api:8000",
            protocol_binding="HTTP+JSON", protocol_version="1.0")],
        capabilities=types.AgentCapabilities(),
        skills=[types.AgentSkill(id=SKILL,name="공동 계획",description="동의 · 기여액 · 결정",tags=["finance"])])
    return MessageToDict(agent)


def task(goal_id, deleted=False):
    return MessageToDict(types.SendMessageResponse(task=types.Task(
        id=str(uuid5(NAMESPACE_URL, str(goal_id))), context_id=str(goal_id),
        status=types.TaskStatus(state=types.TaskState.TASK_STATE_COMPLETED if deleted else types.TaskState.TASK_STATE_INPUT_REQUIRED))))


def receive(message_id, goal_id, body):
    kind, payload = body["kind"], body["payload"]
    with engine.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": str(goal_id)})
        prior = c.execute(text("SELECT reply FROM incoming WHERE message_id=:id"), {"id": message_id}).scalar()
        if prior:
            return prior
        row = c.execute(text("SELECT shared, private FROM journey WHERE id=:id FOR UPDATE"),
                        {"id":goal_id}).first()
        s,p = row if row else (None,None)
        if kind == "snapshot" and payload["owner"] == peer and payload["id"] == str(goal_id):
            if not row:
                s,p = payload,new_private()
                new_row(c,s,p)
            elif s["owner"] == peer and payload["sequence"] > s["sequence"]:
                s = payload
        elif row and s["owner"] == bank_id and not s["deleted"]:
            if kind == "share":
                apply_share(s,peer,payload["snapshot"],payload["revision"])
            elif kind == "decision":
                try:
                    apply_decision(s,payload["version"],peer,payload["choice"])
                except HTTPException as exc:
                    if exc.status_code==503:
                        raise
                    # A superseded decision is terminal; return the current snapshot to the sender.
                    emit(c,"decision.declined",{"id":str(goal_id),"reason":exc.detail})
            else:
                raise HTTPException(422, "지원하지 않는 작업")
            broadcast(c,s)
        elif not (row and s["deleted"]):
            raise HTTPException(409, "작업 소유권 또는 초대 확인 필요")
        changed(c,s,p)
        reply = task(goal_id, s["deleted"])
        c.execute(text("INSERT INTO incoming VALUES (:id,CAST(:r AS jsonb))"),
                  {"id":message_id,"r":packed(reply)})
        emit(c,"a2a.received",{"id":str(goal_id),"kind":kind,"message_id":str(message_id)})
        return reply


@router.post("/message:send")
async def accept(request: Request, authorization: str = Header("")):
    auth(authorization)
    try:
        m = ParseDict(await request.json(), types.SendMessageRequest()).message
        goal_id, message_id = UUID(m.context_id), UUID(m.message_id)
        if m.role != types.Role.ROLE_USER or len(m.parts) != 1:
            raise ValueError()
        body = json.loads(m.parts[0].text)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise HTTPException(422, "메시지 형식 오류") from exc
    return await asyncio.to_thread(receive,message_id,goal_id,body)


@router.post("/internal/comparison", include_in_schema=False)
async def compare_receive(request: Request, authorization: str = Header("")):
    auth(authorization)
    if os.getenv("JOURNEY_TRANSPORT") != "rest":
        raise HTTPException(404)
    packet = await request.json()
    return await asyncio.to_thread(receive,UUID(packet["id"]),UUID(packet["goal"]),packet["body"])


def send_rest(client,row):
    response = client.post(remote+"/internal/comparison",headers={"Authorization":"Bearer "+secret},
        json={"id":str(row["message_id"]),"goal":str(row["goal_id"]),"body":row["body"]})
    response.raise_for_status()
    if response.json()["task"]["contextId"] != str(row["goal_id"]):
        raise ValueError("context")


@router.get("/tasks/{task_id}")
def get_task(task_id: UUID, authorization: str = Header("")):
    auth(authorization)
    with engine.connect() as c:
        record = c.execute(text("SELECT reply FROM incoming WHERE reply->'task'->>'id'=:id LIMIT 1"),
                           {"id":str(task_id)}).scalar()
        if not record:
            raise HTTPException(404)
        gid = record["task"]["contextId"]
        s = c.execute(text("SELECT shared FROM journey WHERE id=:g"), {"g":gid}).scalar_one()
        return task(gid,s["deleted"])["task"]


def deliver_one():
    with engine.begin() as c:
        if not c.execute(text("SELECT pg_try_advisory_xact_lock(239841)")).scalar():
            return False
        row = c.execute(text("SELECT * FROM outgoing WHERE NOT delivered ORDER BY seq LIMIT 1 FOR UPDATE")).mappings().first()
        if not row:
            return False
        reason = None
        try:
            with httpx.Client(timeout=3,trust_env=False) as client:
                if os.getenv("JOURNEY_TRANSPORT")=="rest":
                    send_rest(client,row)
                else:
                    send_a2a(client,row)
        except (httpx.HTTPError, ValueError, StopIteration) as exc:
            reason = type(exc).__name__
        c.execute(text("UPDATE outgoing SET attempts=attempts+1, delivered=:ok,last_error=:err WHERE seq=:s"),
                  {"ok":reason is None,"err":reason,"s":row["seq"]})
        if not reason:
            emit(c,"a2a.delivered",{"id":str(row["goal_id"]), "message_id":str(row["message_id"])})
        return reason is None


def send_a2a(client,row):
    discovery = client.get(remote+"/.well-known/agent-card.json")
    discovery.raise_for_status()
    agent = ParseDict(discovery.json(), types.AgentCard())
    if not any(skill.id == SKILL for skill in agent.skills):
        raise ValueError("skill")
    endpoint = next(i.url for i in agent.supported_interfaces
                    if i.protocol_binding == "HTTP+JSON" and i.url == remote)
    gid = str(row["goal_id"])
    message = {"messageId":str(row["message_id"]),"contextId":gid,
               "role":"ROLE_USER","parts":[{"text":packed(row["body"]), "mediaType":"application/json"}]}
    if row["body"]["kind"] != "snapshot" or row["body"]["payload"].get("sequence",0)>1:
        message["taskId"] = str(uuid5(NAMESPACE_URL,gid))
    req = ParseDict({"message":message},types.SendMessageRequest())
    response = client.post(endpoint+"/message:send",json=MessageToDict(req),headers={
        "Authorization":"Bearer "+secret,"A2A-Version":"1.0","Content-Type":"application/a2a+json"})
    response.raise_for_status()
    result = ParseDict(response.json(),types.SendMessageResponse())
    if result.task.context_id != gid:
        raise ValueError("context")


async def dispatch():
    import logging
    while True:
        try:
            sent = await asyncio.to_thread(deliver_one)
        except Exception:
            logging.getLogger(__name__).warning("은행 간 전달 대기")
            sent = False
        await asyncio.sleep(0.02 if sent else 0.6)
