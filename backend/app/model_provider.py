"""GMS Responses transport and the existing Chat Completions configuration."""
import os

import httpx


def configured():
    return bool(os.getenv("GMS_KEY") or all(os.getenv(k) for k in ("LLM_CHAT_URL","LLM_API_KEY","LLM_MODEL")))


def request_model(instruction, prompt, tools=None):
    key = os.getenv("GMS_KEY")
    if key:
        url = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/responses"
        body = {"model":"gpt-6.1-sol","instructions":instruction,"input":prompt}
        if tools:
            body.update(tools=[{"type":"function",**t["function"]} for t in tools],tool_choice="auto")
    else:
        url = os.environ["LLM_CHAT_URL"]
        if not url.startswith("https://"):
            raise ValueError("HTTPS required")
        body = {"model":os.environ["LLM_MODEL"],"messages":[{"role":"system","content":instruction},
                {"role":"user","content":prompt}]}
        if tools:
            body.update(tools=tools,tool_choice="auto")
    response = httpx.post(url,timeout=25,headers={"Authorization":"Bearer "+(key or os.environ["LLM_API_KEY"])},json=body)
    response.raise_for_status()
    data = response.json()
    if key:
        output = data["output"]
        if tools:
            return next((item["name"] for item in output if item["type"]=="function_call"),None)
        return "".join(part["text"] for item in output if item["type"]=="message"
                       for part in item["content"] if part["type"]=="output_text")
    message = data["choices"][0]["message"]
    if tools:
        return next((call["function"]["name"] for call in message.get("tool_calls",[])),None)
    return message["content"]
