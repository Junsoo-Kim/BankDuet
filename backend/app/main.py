import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import os
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import bank_id, engine
from app.mock_accounts import router as mock_accounts
from app import chat, events, journeys, schedules, transport

@asynccontextmanager
async def lifespan(app):
    with engine.begin() as c:
        c.execute(text("UPDATE chat_run SET state='failed', answer='서버 재시작으로 중단되었습니다.' WHERE state='running'"))
    worker = asyncio.create_task(transport.dispatch())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title=f"BankDuet {bank_id}", lifespan=lifespan, openapi_url="/api/openapi.json",
              docs_url=None, redoc_url=None,servers=[{"url":"/"+bank_id}])
app.include_router(mock_accounts)
for module in (journeys, schedules, chat, events, transport):
    app.include_router(module.router)


def demo_cookie():
    return hmac.digest(os.environ["DB_PASSWORD"].encode(),("demo:"+bank_id).encode(),"sha256").hex()


@app.middleware("http")
async def session_boundary(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        origin = request.headers.get("origin")
        if request.method not in ("GET","HEAD") and origin and urlsplit(origin).hostname not in ("localhost","127.0.0.1"):
            return JSONResponse({"detail":"로컬 시연 세션이 필요합니다."},status_code=403)
        public = path in ("/api/health","/api/session","/api/openapi.json","/api/docs") or path.startswith("/api/mock/")
        if not public and not hmac.compare_digest(request.cookies.get("demo_"+bank_id,""),demo_cookie()):
            return JSONResponse({"detail":"은행별 시연 세션을 먼저 여세요."},status_code=401)
    return await call_next(request)


@app.post("/api/session")
def demo_session():
    response = JSONResponse({"bank":bank_id,"customer":"민지" if bank_id=="kb" else "준호"})
    response.set_cookie("demo_"+bank_id,demo_cookie(),httponly=True,samesite="strict",path="/"+bank_id+"/")
    return response


@app.get("/api/docs", include_in_schema=False)
def docs():
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(openapi_url=f"/{bank_id}/api/openapi.json",title="BankDuet API",
        swagger_js_url="/swagger/swagger-ui-bundle.js",swagger_css_url="/swagger/swagger-ui.css",
        swagger_favicon_url="/swagger/favicon-32x32.png")


@app.get("/api/health")
def health():
    try:
        with engine.connect() as connection:
            customer = connection.execute(text("""
                SELECT display_name, created_at FROM demo_customer WHERE id = :id
            """), {"id": bank_id + "-demo"}).mappings().one()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="은행 데이터 연결 대기 중")
    return {"bank": bank_id, "status": "ready", "demo_customer": customer["display_name"],
            "seeded_at": customer["created_at"]}
