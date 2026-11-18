from datetime import datetime
from zoneinfo import ZoneInfo
import os
import httpx
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db import engine, bank_id
from app.contracts import PlanView
from app.finance import Expense, Terms, contribution, forecast, new_private, now, renew
from app.storage import emit, enqueue, journey, new_row, save

router = APIRouter(prefix="/api/plans", tags=["공동 계획"])
peer = "b" if bank_id == "kb" else "kb"


class Consent(BaseModel):
    mode: Literal["once", "auto", "revoked"]


class Decision(BaseModel):
    choice: Literal["approve", "reject", "extend"]


class ChangeTerms(Terms):
    version: int = Field(ge=1)


class CreateTerms(Terms):
    mode: Literal["once", "auto"]


class Missed(BaseModel):
    month: int = Field(ge=1, le=600)


class Budget(BaseModel):
    reserve: int = Field(ge=0,le=10**13)
    monthly: int = Field(ge=0,le=10**13)


class Deposit(Missed):
    amount: int = Field(gt=0,le=10**13)


def view(s, p):
    return {**s, "forecast": forecast(s), "private": p, "local_bank": bank_id}


def reset_version(s):
    s["version"] += 1
    s["votes"] = {}
    s["status"] = "review" if len(s["shares"]) == 2 else "invited"


def broadcast(c, s):
    s["sequence"] += 1
    enqueue(c, s, "snapshot", s)


def changed(c, s, p):
    save(c, s, p)
    emit(c, "plan", {"id": s["id"], "version": s["version"]})


def apply_share(s, actor, snap, revision):
    if revision <= s["revisions"].get(actor, -1):
        return
    s["revisions"][actor] = revision
    if snap is None:
        s["shares"].pop(actor, None)
    else:
        s["shares"][actor] = snap
    reset_version(s)


def share(c, s, p):
    p["revision"] += 1
    snap = None if p["consent"] == "revoked" else contribution(p)
    if bank_id == s["owner"]:
        apply_share(s, bank_id, snap, p["revision"])
        broadcast(c, s)
    else:
        enqueue(c, s, "share", {"snapshot": snap, "revision": p["revision"]})


def validate_peer(s):
    try:
        response = httpx.get(f"http://{peer}-api:8000/internal/consent/{s['id']}",
            headers={"Authorization":"Bearer "+os.environ["BANK_PEER_SECRET"]},timeout=2,trust_env=False)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError,ValueError) as exc:
        raise HTTPException(503,"상대 은행의 최신 동의를 확인할 수 없어 확정을 보류합니다.") from exc
    if not result["valid"] or result["revision"] != s["revisions"][peer]:
        raise HTTPException(409,"상대 은행의 동의 또는 기여액이 변경되었습니다.")


def apply_decision(s, version, actor, choice, authoritative=True):
    if version != s["version"] or s["deleted"]:
        raise HTTPException(409, "이전 버전입니다. 최신 계획을 확인하세요.")
    if len(s["shares"]) != 2 or any(datetime.fromisoformat(x["expires"]) <= now() for x in s["shares"].values()):
        raise HTTPException(409, "유효한 양측 기여액이 필요합니다.")
    if s["status"] != "review":
        raise HTTPException(409, "이미 결정된 제안입니다.")
    if choice == "extend":
        f = forecast(s)
        n = f["needed_months"]
        if n is None or not s["months"] < n <= 600:
            raise HTTPException(409, "현재 조건에서 적용할 기간 연장안이 없습니다.")
        s["months"] = n
        reset_version(s)
        return
    if choice == "reject":
        s["status"] = "rejected"
        s["votes"][actor] = "reject"
        return
    if forecast(s)["gap"]:
        raise HTTPException(409, "목표 달성이 가능한 수정안을 먼저 제안하세요.")
    if authoritative and set(s["votes"]) | {actor} == {bank_id, peer}:
        validate_peer(s)
    s["votes"][actor] = "approve"
    if set(s["votes"]) == {bank_id, peer}:
        s["status"] = "confirmed"
        s["confirmed"] = {"version": version, "months": s["months"], "target": s["target"],
                          "date": forecast(s)["target_date"], "forecast": forecast(s)}
        s.setdefault("history",[]).append(dict(s["confirmed"]))


@router.post("", status_code=201,response_model=PlanView)
def create(terms: CreateTerms):
    p = new_private()
    p.update(consent=terms.mode, revision=1)
    renew(p)
    s = {**terms.model_dump(exclude={"mode"}), "id": str(uuid4()), "owner": bank_id, "start": now().astimezone(ZoneInfo("Asia/Seoul")).date().isoformat(),
         "created_at": now().isoformat(), "version": 1, "sequence": 0, "status": "invited",
         "shares": {bank_id: contribution(p)}, "revisions": {bank_id: 1},
         "votes": {}, "confirmed": None, "deleted": False}
    with engine.begin() as c:
        broadcast(c, s)
        new_row(c, s, p)
        emit(c, "plan", {"id": s["id"]})
    return view(s, p)


@router.get("",response_model=list[PlanView])
def listing():
    with engine.connect() as c:
        rows = c.execute(text("SELECT shared, private FROM journey ORDER BY created_at DESC"))
        return [view(s,p) for s,p in rows if not s["deleted"]]


@router.get("/{goal_id}",response_model=PlanView)
def detail(goal_id: UUID):
    with engine.connect() as c:
        s,p = journey(c, goal_id)
        if s["deleted"]:
            raise HTTPException(404)
        return view(s,p)


@router.get("/{goal_id}/trajectory")
def trajectory(goal_id: UUID):
    with engine.connect() as c:
        s,_=journey(c,goal_id)
        if s["deleted"]:
            raise HTTPException(404)
        return {"version":s["version"],"forecast":forecast(s,monthly_detail=True)}


def active(c, goal_id):
    s,p = journey(c, goal_id, lock=True)
    if s["deleted"]:
        raise HTTPException(410, "삭제된 목표입니다.")
    return s,p


@router.put("/{goal_id}",response_model=PlanView)
def update(goal_id: UUID, terms: ChangeTerms):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        if s["owner"] != bank_id or s["version"] != terms.version:
            raise HTTPException(409, "개설 은행에서 최신 버전을 수정하세요.")
        s.update(terms.model_dump(exclude={"version"}))
        reset_version(s)
        broadcast(c,s)
        changed(c,s,p)
        return view(s,p)


@router.delete("/{goal_id}")
def remove(goal_id: UUID):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        if s["owner"] != bank_id:
            raise HTTPException(403, "개설 은행에서 삭제할 수 있습니다.")
        s["deleted"] = True
        reset_version(s)
        broadcast(c,s)
        changed(c,s,p)
    return {"deleted": True}


@router.post("/{goal_id}/consent",response_model=PlanView)
def consent(goal_id: UUID, cmd: Consent):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        p["consent"] = cmd.mode
        renew(p)
        share(c,s,p)
        changed(c,s,p)
        return view(s,p)


@router.post("/{goal_id}/expenses",response_model=PlanView)
def add_expense(goal_id: UUID, cmd: Expense):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        key = str(cmd.id)
        if key in p["expenses"]:
            old = p["expenses"][key]
            if (old["amount"],old["note"]) != (cmd.amount,cmd.note):
                raise HTTPException(409, "동일 ID의 지출 정보가 다릅니다.")
            return view(s,p)
        p["expenses"][key] = {"amount": cmd.amount, "note": cmd.note, "posted": False}
        if p["consent"] == "auto" and datetime.fromisoformat(p["expires"]) > now():
            share(c,s,p)
        changed(c,s,p)
        return view(s,p)


@router.post("/{goal_id}/expenses/{expense_id}/post",response_model=PlanView)
def post_expense(goal_id: UUID, expense_id: UUID):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        item = p["expenses"].get(str(expense_id))
        if not item:
            raise HTTPException(404)
        if not item["posted"]:
            if item["amount"] > p["balance"]:
                raise HTTPException(409,"현재 모킹 잔액보다 큰 금액을 출금 처리할 수 없습니다.")
            item["posted"] = True
            p["balance"] -= item["amount"]
            p["as_of"]=now().isoformat()
        changed(c,s,p)
        return view(s,p)


@router.post("/{goal_id}/missed",response_model=PlanView)
def missed(goal_id: UUID, cmd: Missed):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        if cmd.month > s["months"]:
            raise HTTPException(422, "계획 기간을 확인하세요.")
        if str(cmd.month) in p.get("deposits",{}):
            raise HTTPException(409,"이미 납입한 회차입니다.")
        if str(cmd.month) not in p["missed"]:
            p["missed"][str(cmd.month)] = p["monthly"]
            if p["consent"] == "auto" and datetime.fromisoformat(p["expires"]) > now():
                share(c,s,p)
        changed(c,s,p)
        return view(s,p)


@router.post("/{goal_id}/deposits",response_model=PlanView)
def deposit(goal_id: UUID, cmd: Deposit):
    with engine.begin() as c:
        s,p = active(c,goal_id)
        if cmd.month > s["months"]:
            raise HTTPException(422,"계획 기간을 확인하세요.")
        k = str(cmd.month)
        prior = p.setdefault("deposits",{}).get(k)
        if prior is not None:
            if prior != cmd.amount:
                raise HTTPException(409,"이미 반영된 납입 회차입니다.")
            return view(s,p)
        p["deposits"][k]=cmd.amount
        p["missed"].pop(k,None)
        p["balance"]+=cmd.amount
        p["as_of"]=now().isoformat()
        if p["consent"]=="auto" and datetime.fromisoformat(p["expires"])>now():
            share(c,s,p)
        changed(c,s,p)
        return view(s,p)


@router.post("/{goal_id}/versions/{version}/decisions",response_model=PlanView)
def decide(goal_id: UUID, version: int, cmd: Decision):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        if p["consent"] in ("none","revoked") or p["revision"] != s["revisions"].get(bank_id):
            raise HTTPException(409, "본인 기여액이 반영된 후 결정할 수 있습니다.")
        if version != s["version"] or s["status"] != "review":
            raise HTTPException(409, "최신 검토 버전을 확인하세요.")
        if bank_id == s["owner"]:
            apply_decision(s,version,bank_id,cmd.choice)
            broadcast(c,s)
        else:
            apply_decision(dict(s, votes=dict(s["votes"]),history=list(s.get("history",[]))),
                           version,bank_id,cmd.choice,authoritative=False)
            enqueue(c,s,"decision",{"version": version, "choice": cmd.choice})
        changed(c,s,p)
        return view(s,p)


@router.put("/{goal_id}/budget",response_model=PlanView)
def budget(goal_id: UUID, cmd: Budget):
    with engine.begin() as c:
        s,p = active(c, goal_id)
        if cmd.reserve > p["balance"]:
            raise HTTPException(422,"비상금은 현재 잔액 범위에서 설정하세요.")
        if (p["monthly"],p["reserve"]) != (cmd.monthly,cmd.reserve):
            if cmd.monthly != p["monthly"]:
                completed=max(map(int,[*p["missed"],*p.get("deposits",{})]),default=0)
                closed=p.setdefault("closed_amounts",{})
                for month in range(1,completed+1):
                    closed.setdefault(str(month),p["monthly"])
            p.update(cmd.model_dump())
            if p["consent"] == "auto" and datetime.fromisoformat(p["expires"]) > now():
                share(c,s,p)
            changed(c,s,p)
        return view(s,p)
