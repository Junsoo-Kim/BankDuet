"""Runs only against the isolated bankduet-verify Compose project on loopback."""
import json
import os
import subprocess
from pathlib import Path
from time import monotonic, sleep

import requests

root=Path(__file__).resolve().parents[1]
env={**os.environ,"WEB_PORT":"18474"}
base="http://127.0.0.1:18474"
client=requests.Session()
client.trust_env=False

def compose(*args):
    subprocess.run(["docker","compose","-p","bankduet-verify","-f","compose.yaml","-f","tests/transport.compose.yaml",*args],
                   env=env,cwd=root,check=True)

def api(bank,path,method="GET",body=None):
    url=f"{base}/{bank}/api/{path}"
    r=client.request(method,url,json=body,timeout=10)
    # The proxy may still hold a stopped container's address briefly after recreation.
    if method=="GET" or path=="session":
        end=monotonic()+8
        while r.status_code in (502,503,504) and monotonic()<end:
            sleep(.25)
            r=client.request(method,url,json=body,timeout=10)
    r.raise_for_status()
    return r.json()

def await_plan(bank,gid,predicate):
    end=monotonic()+40
    while monotonic()<end:
        rows=api(bank,"plans")
        if any(x["id"]==gid and predicate(x) for x in rows):
            return
        sleep(.1)
    raise RuntimeError("은행 간 반영 시간 초과")

def sample(fault):
    for bank in ("kb","b"):
        api(bank,"session","POST")
    if fault:
        compose("stop","b-api")
    t=monotonic()
    try:
        g=api("kb","plans","POST",{"title":"전송 비교","mode":"auto"})
        gid=g["id"]
        if fault:
            sleep(1.3)
    finally:
        if fault:
            compose("up","-d","--wait","b-api")
    await_plan("b",gid,lambda x:True)
    route="plans/"+gid
    api("b",route+"/consent","POST",{"mode":"auto"})
    await_plan("kb",gid,lambda x:x["status"]=="review")
    version=api("kb",route)["version"]
    update=api("kb",route,"PUT",{"title":"변경 합의","months":121,"version":version})
    await_plan("b",gid,lambda x:x["version"]==update["version"])
    for bank in ("kb","b"):
        api(bank,route+f"/versions/{update['version']}/decisions","POST",{"choice":"approve"})
    await_plan("b",gid,lambda x:x["status"]=="confirmed")
    elapsed=round((monotonic()-t)*1000)
    api("kb",route,"DELETE")
    return elapsed

if __name__=="__main__":
    data=[]
    try:
        compose("build","kb-api","b-api")
        compose("up","-d","--wait","web")
        for mode,replace in [("rest","0"),("a2a","0"),("a2a","1")]:
            env.update(BENCH_TRANSPORT=mode,BENCH_REPLACE=replace)
            compose("up","-d","--wait","kb-api","b-api")
            data.append(dict(mode=mode,replacement=replace=="1",
                             latency_ms=[sample(False) for _ in range(3)],recovery_ms=sample(True)))
    finally:
        subprocess.run(["docker","compose","-p","bankduet-verify","up","-d","--wait","kb-api","b-api"],env=env,cwd=root,check=True)
    (root/"docs/evidence/transport.json").write_text(json.dumps(data,indent=2),encoding="utf-8")
    print(data)
