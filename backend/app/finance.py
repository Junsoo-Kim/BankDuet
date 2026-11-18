import calendar
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, Field

MAX_WON = 10**13


class Terms(BaseModel):
    title: str = Field(default="신혼집 자기자금", min_length=1, max_length=80)
    target: int = Field(default=1_000_000_000, gt=0, le=MAX_WON)
    months: int = Field(default=120, ge=1, le=600)


class Expense(BaseModel):
    id: UUID
    amount: int = Field(gt=0, le=MAX_WON)
    note: str = Field(default="예정 지출", max_length=120)


def now():
    return datetime.now(timezone.utc)


def date_after(start, months):
    first = date.fromisoformat(start)
    year, month = divmod(first.year * 12 + first.month - 1 + months, 12)
    if year > 9999:
        return None
    return date(year, month + 1, min(first.day, calendar.monthrange(year, month+1)[1])).isoformat()


def new_private():
    from app.mock_accounts import savings_history,read_balance,registered_id
    history=savings_history(registered_id)["entries"]
    account=read_balance(registered_id)
    return {"balance":int(account["available_amt"]), "as_of":account["as_of"], "savings_history":history,
            "reserve": 5_000_000, "monthly":sum(x["amount"] for x in history)//len(history),
            "expenses": {}, "missed": {}, "deposits": {}, "consent": "none", "revision": 0, "expires": None}


def contribution(private):
    pending = sum(x["amount"] for x in private["expenses"].values() if not x["posted"])
    deposits = private.get("deposits",{})
    adjustments={month:private["monthly"]-amount for month,amount in private.get("closed_amounts",{}).items()}
    adjustments.update({month:private["monthly"] for month in private["missed"]})
    for month,amount in deposits.items():
        adjustments[month] = private["monthly"] - amount
    return {"capital": max(0, private["balance"] - sum(deposits.values()) - private["reserve"] - pending),
            "monthly": private["monthly"], "revision": private["revision"], "as_of":now().isoformat(),
            "expires": private["expires"], "missed": sum(private["missed"].values()),
            "adjustments": adjustments}


def renew(private):
    private["expires"] = (now() + timedelta(days=30)).isoformat()


def forecast(shared, monthly_detail=False):
    shares = shared["shares"]
    if len(shares) != 2:
        return None
    capital = sum(s["capital"] for s in shares.values())
    monthly = sum(s["monthly"] for s in shares.values())
    term, target = shared["months"], shared["target"]
    adjustments = {}
    for share in shares.values():
        entries = share.get("adjustments", {"1":share["missed"]} if share.get("missed") else {})
        for month, amount in entries.items():
            m = int(month)
            adjustments[m] = adjustments.get(m,0) + amount
    def amount_at(m):
        deductions = sum(value for month,value in adjustments.items() if month<=m)
        return max(capital, capital + monthly*m - deductions)
    projected = amount_at(term)
    gap = max(0, target - projected)
    remaining = max(0, target - capital)
    needed = None
    if remaining == 0:
        needed = 0
    elif monthly:
        upper = max(1,max(adjustments,default=0),
                    (remaining + sum(max(0,x) for x in adjustments.values()) + monthly - 1)//monthly)
        lo = 0
        while lo<upper:
            mid=(lo+upper)//2
            if amount_at(mid)>=target:
                upper=mid
            else:
                lo=mid+1
        needed=lo
    elif adjustments:
        needed=next((m for m in sorted(adjustments) if amount_at(m)>=target),None)
    milestones = range(term+1) if monthly_detail else sorted({0, term, *range(12, term, 12)})
    elapsed=max((m for m in adjustments if m<=term),default=0)
    remaining_cycles=term-elapsed
    return {"capital": capital, "monthly": monthly, "projected": projected, "gap": gap,
            "remaining_cycles":remaining_cycles,
            "needed_months": needed, "extra_monthly": (gap+remaining_cycles-1)//remaining_cycles if remaining_cycles else None,
            "target_date": date_after(shared["start"], term),
            "achieve_date": date_after(shared["start"], needed) if needed is not None else None,
            "milestones": [{"month": m, "amount": amount_at(m),"progress_pct":round(amount_at(m)*100/target,2)} for m in milestones]}
