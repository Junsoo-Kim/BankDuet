"""은행별 합성 응답. 인증 정보나 외부 네트워크를 사용하지 않는다."""
from fastapi import APIRouter, HTTPException
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from app.db import bank_id

router = APIRouter(prefix="/api/mock/accounts", tags=["모킹 계좌"])
registered_id = {"kb": "kb-demo-01", "b": "b-demo-01"}[bank_id]


@router.get("/{account_id}/savings-history")
def savings_history(account_id: str):
    if account_id != registered_id:
        raise HTTPException(status_code=404,detail="등록되지 않은 가상 계좌입니다.")
    cursor=datetime.now(ZoneInfo("Asia/Seoul")).date().replace(day=1)
    entries=[]
    for amount in (2_500_000,2_600_000,2_400_000):
        cursor=(cursor-timedelta(days=1)).replace(day=1)
        entries.append({"date":cursor.replace(day=25).isoformat(),"amount":amount,"type":"저축 이체"})
    return {"source":"mock","entries":entries}


@router.get("")
def list_accounts():
    return {"source": "mock", "rsp_code": "A0000", "res_list": [
        {"account_id": registered_id, "product_name": "목표 참여 입출금계좌"}
    ]}


@router.get("/{account_id}/balance")
def read_balance(account_id: str):
    if account_id != registered_id:
        raise HTTPException(status_code=404, detail="등록되지 않은 가상 계좌입니다.")
    return {"source": "mock", "account_id": account_id, "rsp_code": "A0000",
            "as_of":datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "bank_rsp_code": "000", "balance_amt": "205000000",
            "available_amt": "205000000"}
