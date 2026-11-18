"""Contract-compatible B-bank message decoder used only by the isolated benchmark."""
import json
import os
from uuid import UUID
from fastapi import Header, Request
from app.main import app as original_app
from app.transport import auth, receive

app=original_app
if os.getenv("REPLACE_ADAPTER") == "1":
    from fastapi import FastAPI
    app=FastAPI(lifespan=original_app.router.lifespan_context)

    @app.post("/message:send")
    async def replacement(request:Request,authorization:str=Header("")):
        import asyncio
        auth(authorization)
        message=(await request.json())["message"]
        return await asyncio.to_thread(receive,UUID(message["messageId"]),UUID(message["contextId"]),
                                       json.loads(message["parts"][0]["text"]))
    app.mount("/",original_app)
