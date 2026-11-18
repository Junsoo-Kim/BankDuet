import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text


def packed(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def journey(c, goal_id, lock=False):
    q = "SELECT shared, private FROM journey WHERE id=:id"
    row = c.execute(text(q + (" FOR UPDATE" if lock else "")), {"id": goal_id}).first()
    if not row:
        raise HTTPException(404, "목표를 찾을 수 없습니다.")
    return row.shared, row.private


def new_row(c, shared, private):
    c.execute(text("""INSERT INTO journey (id,shared,private)
        VALUES (:id,CAST(:shared AS jsonb),CAST(:private AS jsonb))"""),
        {"id": shared["id"], "shared": packed(shared), "private": packed(private)})


def save(c, shared, private):
    c.execute(text("""UPDATE journey SET shared=CAST(:s AS jsonb),
        private=CAST(:p AS jsonb) WHERE id=:id"""),
        {"id": shared["id"], "s": packed(shared), "p": packed(private)})


def emit(c, kind, payload):
    # Serialize allocation with commit order so a reconnect cursor cannot skip a late commit.
    c.execute(text("SELECT pg_advisory_xact_lock(761134)"))
    c.execute(text("INSERT INTO bank_event(kind,payload) VALUES (:k,CAST(:p AS jsonb))"),
              {"k": kind, "p": packed(payload)})


def enqueue(c, shared, kind, payload):
    c.execute(text("INSERT INTO outgoing(message_id,goal_id,body) VALUES (:m,:g,CAST(:p AS jsonb))"),
              {"m": str(uuid4()), "g": shared["id"], "p": packed({"kind": kind, "payload": payload})})
