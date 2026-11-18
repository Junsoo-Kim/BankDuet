from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import text

from app.db import engine
from app.storage import emit

router = APIRouter(prefix="/api/appointments",tags=["개인 상담 준비 일정"])


class Schedule(BaseModel):
    title: str = Field(min_length=1,max_length=100)
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("종료 시각을 확인하세요.")
        return self


@router.get("")
def appointments():
    with engine.connect() as c:
        return c.execute(text("SELECT * FROM appointment ORDER BY starts_at")).mappings().all()


@router.get("/{item_id}")
def appointment(item_id: UUID):
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM appointment WHERE id=:id"),{"id":item_id}).mappings().first()
        if not row:
            raise HTTPException(404)
        return row


def write(item_id, cmd, create):
    params = {**cmd.model_dump(), "id":item_id}
    with engine.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(344671)"))
        query = ("INSERT INTO appointment(id,title,starts_at,ends_at) VALUES(:id,:title,:starts_at,:ends_at)"
                 if create else "UPDATE appointment SET title=:title,starts_at=:starts_at,ends_at=:ends_at WHERE id=:id")
        row = c.execute(text(query+" RETURNING *"),params).mappings().first()
        if not row:
            raise HTTPException(404)
        conflicts = c.execute(text("""SELECT id,title FROM appointment WHERE id<>:id
            AND starts_at<:ends_at AND ends_at>:starts_at ORDER BY starts_at"""),params).mappings().all()
        emit(c,"appointment",{"id":str(item_id)})
        return {"appointment":row,"conflicts":conflicts}


@router.post("",status_code=201)
def create(cmd: Schedule):
    return write(uuid4(),cmd,True)


@router.put("/{item_id}")
def update(item_id: UUID, cmd: Schedule):
    return write(item_id,cmd,False)


@router.delete("/{item_id}")
def remove(item_id: UUID):
    with engine.begin() as c:
        if not c.execute(text("DELETE FROM appointment WHERE id=:id"),{"id":item_id}).rowcount:
            raise HTTPException(404)
        emit(c,"appointment",{"id":str(item_id)})
    return {"deleted":True}
