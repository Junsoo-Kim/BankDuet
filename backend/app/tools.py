import os

import httpx
from fastapi import HTTPException

from app.mock_accounts import list_accounts, read_balance


def describe(name, when, field=None):
    schema = {"type":"object","properties":{},"additionalProperties":False}
    if field:
        schema.update(properties={field:{"type":"string"}},required=[field])
    return {"type":"function","function":{"name":name,"description":when,"parameters":schema}}


CATALOG = [describe("list_accounts","주택 목표에 쓸 자기 은행의 가상 계좌 후보를 찾을 때"),
           describe("read_balance","후보 계좌의 출금가능액을 확인할 때","account_id"),
           describe("search_branches","상담할 지역의 은행 지점을 검색할 때","region")]


def call(name,args):
    if name == "list_accounts":
        try:
            listing=list_accounts()
            if listing["rsp_code"]!="A0000" or not isinstance(listing["res_list"],list):
                return {"ok":False,"code":"INVALID_RESPONSE"}
            return {"ok":True,"source":"mock","data":listing["res_list"]}
        except (TimeoutError,httpx.HTTPError,KeyError,TypeError):
            return {"ok":False,"code":"UPSTREAM_ERROR"}
    if name == "read_balance":
        try:
            detail = read_balance(args["account_id"])
            amount = detail.get("available_amt")
            if not isinstance(amount,str) or not amount.isascii() or not amount.isdigit():
                return {"ok":False,"code":"MISSING_AMOUNT"}
            if detail.get("account_id")!=args["account_id"] or detail.get("bank_rsp_code")!="000" or detail.get("rsp_code")!="A0000":
                return {"ok":False,"code":"INVALID_RESPONSE"}
            return {"ok":True,"source":"mock","data":{"available":int(amount),"as_of":detail.get("as_of")}}
        except (TimeoutError,httpx.HTTPError):
            return {"ok":False,"code":"UPSTREAM_ERROR"}
        except (HTTPException,KeyError):
            return {"ok":False,"code":"UNKNOWN_ACCOUNT"}
    if name != "search_branches" or not args.get("region"):
        return {"ok":False,"code":"BAD_ARGUMENT"}
    key = os.getenv("KAKAO_REST_API_KEY")
    if not key:
        return {"ok":False,"code":"MISSING_KEY"}
    try:
        result = httpx.get("https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query":args["region"]+" KB국민은행","category_group_code":"BK9"},
            headers={"Authorization":"KakaoAK "+key},timeout=5)
        result.raise_for_status()
        places = [{"name":x["place_name"],"address":x["address_name"],"url":x["place_url"]}
                  for x in result.json()["documents"] if "국민은행" in x["place_name"]][:3]
        return {"ok":True,"source":"kakao","data":places} if places else {"ok":False,"code":"NO_RESULT"}
    except (httpx.HTTPError,KeyError,ValueError):
        return {"ok":False,"code":"UPSTREAM_ERROR"}
