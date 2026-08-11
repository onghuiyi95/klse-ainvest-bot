#!/usr/bin/env python3
# simulate_guest.py — 模拟一个全新 ainvest guest（清掉认证 cookie -> 重新加载 -> 服务端下发新 mt_xxx + 新 2 次配额）
# 用法: python simulate_guest.py   ->  打印新 guest id 并刷新 cookie.txt
import os
import json, urllib.request, re, time

MCP="http://127.0.0.1:9010/mcp"
HDR={"content-type":"application/json","accept":"application/json, text/event-stream"}
AUTH=["sess_tk","ticket","sessionid","cuc","userid","u_name","escapename","user"]

def rpc(method, params=None, id=1, session=None, timeout=20):
    h=dict(HDR)
    if session: h["Mcp-Session-Id"]=session
    body=json.dumps({"jsonrpc":"2.0","id":id,"method":method,"params":params or {}}).encode()
    try:
        r=urllib.request.urlopen(urllib.request.Request(MCP, data=body, headers=h), timeout=timeout)
    except Exception as e:
        return None, session
    sid=r.headers.get("Mcp-Session-Id"); raw=r.read().decode(); out=None
    for line in raw.splitlines():
        line=line.strip()
        if line.startswith("data:"):
            p=line[5:].strip()
            if p:
                try: out=json.loads(p)
                except: pass
    return out, sid
def call(name, args, sid, id=10):
    r,_=rpc("tools/call", {"name":name,"arguments":args}, id, sid); return r
def txt(r): return " ".join(c.get("text","") for c in r.get("result",{}).get("content",[]) if c.get("type")=="text")
def cookie_of(raw):
    mm=re.search(r"origin=https://www\.ainvest\.com/[^\]]*\]\s*(.*?)(?:\[END_UNTRUSTED|$)", raw, re.S)
    return (mm.group(1).strip() if mm else raw).strip()

init, sid = rpc("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"sim-guest","version":"1"}},1)
if not sid:
    print("ERR: browseros-neo 未在 127.0.0.1:9010 运行"); raise SystemExit(1)
h=dict(HDR); h["Mcp-Session-Id"]=sid
urllib.request.urlopen(urllib.request.Request(MCP, data=json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}).encode(), headers=h), timeout=10)

# 开新页面
op=call("tabs", {"action":"new","url":"https://www.ainvest.com/aime/"}, sid, 11)
pid=int(re.search(r"opened page (\d+)", txt(op)).group(1)); time.sleep(2)

# 清认证 cookie
clear_js="""
(function(){
  const dom=['www.ainvest.com','.ainvest.com','ainvest.com','tech.ainvest.com'];
  let cleared=[];
  for(const d of dom){
    document.cookie.split(';').forEach(c=>{
      const k=c.trim().split('=')[0];
      if(%s.includes(k)){
        try{ document.cookie=k+'=; expires=Thu, 01 Jan 1970 00:00:00 GMT; domain='+d+'; path=/'; cleared.push(k);}catch(e){}
      }
    });
  }
  return 'cleared:'+cleared.join(',');
})();
""" % json.dumps(AUTH)
print("clear:", txt(call("evaluate", {"page":pid,"code":clear_js}, sid, 12))[:120])

# 重载 -> 服务端下发新 guest
call("navigate", {"action":"reload","page":pid}, sid, 13); time.sleep(3)
raw=txt(call("evaluate", {"page":pid,"code":"return document.cookie"}, sid, 14))
ck=cookie_of(raw)
um=re.search(r"u_name=(mt_\d+)", ck) or re.search(r"escapename=(mt_\d+)", ck)
print("新 guest id:", um.group(1) if um else "无")
print("user_status:", (re.search(r"user_status=(\d+)",ck) or [None,"?"])[1])

# 存关键字段到 cookie.txt
keys=AUTH+["nova_fingerPrint"]
pairs=[p.strip() for p in ck.split(";") if p.strip()]
out={}
for p in pairs:
    if "=" in p:
        k,v=p.split("=",1)
        if k in keys: out[k]=v
s="; ".join(f"{k}={v}" for k,v in out.items())
with open("cookie.txt","w") as f: f.write(s)
print("已刷新 cookie.txt (%d bytes) -> 新 guest 身份可用" % len(s))
# 额外把完整 cookie 写到 cookie_<guestid>.txt（供多线程 worker 各自独占身份, 互不干扰）
import re as _re
um = _re.search(r"u_name=(mt_\d+)", s) or _re.search(r"escapename=(mt_\d+)", s)
gid = um.group(1) if um else "x"
with open(f"cookie_{gid}.txt","w") as f: f.write(s)
print("完整 cookie 已写 cookie_%s.txt" % gid)