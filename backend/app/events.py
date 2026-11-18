import asyncio
import json
import logging
import os

from sqlalchemy import text
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.db import engine
from app.storage import emit, packed

router = APIRouter(prefix="/api")
subscribers = []


def persist(session_id,run_id,kind,payload):
    if os.getenv("TRACE_ENABLED","1") == "0":
        return
    with engine.begin() as c:
        c.execute(text("""INSERT INTO trace(session_id,run_id,kind,payload)
            VALUES(:s,:r,:k,CAST(:p AS jsonb))"""),
            {"s":session_id,"r":run_id,"k":kind,"p":packed(payload)})


subscribers.append(persist)


def publish(s,r,k,p):
    for callback in subscribers:
        try:
            callback(s,r,k,p)
        except Exception:
            logging.getLogger(__name__).warning("실행 로그 저장 실패")
    with engine.begin() as c:
        emit(c,"run.progress",{"run_id":str(r),"session_id":str(s),"stage":k})


def since(cursor):
    with engine.connect() as c:
        return c.execute(text("SELECT seq,kind,payload FROM bank_event WHERE seq>:n ORDER BY seq LIMIT 100"),
                         {"n":cursor}).mappings().all()


@router.get("/events")
async def stream(request: Request, after: int = Query(0,ge=0), last_event_id: str = Header("")):
    cursor = int(last_event_id) if last_event_id.isdigit() else after

    async def generate():
        nonlocal cursor
        while not await request.is_disconnected():
            rows = await asyncio.to_thread(since,cursor)
            for row in rows:
                cursor = row["seq"]
                body = json.dumps({"kind":row["kind"], **row["payload"]},ensure_ascii=False)
                yield f"id: {cursor}\ndata: {body}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)
    return StreamingResponse(generate(),media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@router.get("/events/cursor")
def last_cursor():
    with engine.connect() as c:
        return {"cursor":c.execute(text("SELECT COALESCE(MAX(seq),0) FROM bank_event")).scalar()}
