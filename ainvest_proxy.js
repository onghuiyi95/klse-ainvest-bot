// ainvest_proxy.js — 本地 CORS 代理，缓冲 body，避免上游 413
const http = require("http");
const https = require("https");
const { spawn } = require("child_process");
const UPSTREAM = "tech.ainvest.com";
const UP_PATH  = "/gateway/harness/api";
const LISTEN   = 8787;
const fs = require("fs");
const path = require("path");
const ROOT = __dirname;
const MIME = {".html":"text/html",".js":"text/javascript",".css":"text/css",".txt":"text/plain"};

function collect(req){
  return new Promise(res=>{ const c=[]; req.on("data",x=>c.push(x)); req.on("end",()=>res(Buffer.concat(c))); });
}
const server = http.createServer(async (req,res)=>{
  const url = new URL(req.url,"http://localhost");
  // 静态文件：GET / -> ainvest_web.html ; GET /cookie.txt ; PUT /cookie.txt 保存
  if(!url.pathname.startsWith("/interaction")){
    if(req.method==="PUT" && url.pathname==="/cookie.txt"){
      let b=Buffer.alloc(0); try{b=await collect(req);}catch(e){}
      fs.writeFile(path.join(ROOT,"cookie.txt"),b,(e)=>{ if(e){res.writeHead(500);res.end("err");}else{res.writeHead(200);res.end("ok");} });
      return;
    }
    if(url.pathname==="/echo_cookie"){
      res.writeHead(200,{"content-type":"application/json","access-control-allow-origin":"*"});
      res.end(JSON.stringify({cookie: req.headers["cookie"]||"", hasSessTk: /(^|;\s*)sess_tk=/.test(req.headers["cookie"]||"")}));
      return;
    }
    if(url.pathname==="/simulate_guest"){
      // 调本地 simulate_guest.py 通过 browseros-neo MCP 换新 guest 身份
      const py = spawn("python", ["simulate_guest.py"], {cwd: ROOT});
      let out="", err="";
      py.stdout.on("data",d=>out+=d.toString());
      py.stderr.on("data",d=>err+=d.toString());
      py.on("close",code=>{
        const m = out.match(/新 guest id:\s*(mt_\d+)/);
        const gid = m ? m[1] : null;
        res.writeHead(200,{"content-type":"application/json","access-control-allow-origin":"*"});
        res.end(JSON.stringify({ok: code===0 && !!gid, guestId: gid, raw: out.slice(-400), err: err.slice(-300)}));
      });
      return;
    }
    let f = url.pathname==="/" ? "/ainvest_web.html" : url.pathname;
    const fp = path.join(ROOT, f);
    if(fs.existsSync(fp) && fs.statSync(fp).isFile()){
      const ext=path.extname(fp);
      res.writeHead(200,{"content-type":MIME[ext]||"application/octet-stream","access-control-allow-origin":"*"});
      fs.createReadStream(fp).pipe(res);
    } else { res.writeHead(404); res.end("not found"); }
    return;
  }
  // API 代理
  let body=Buffer.alloc(0); try{ body=await collect(req); }catch(e){}
  // cookie 优先级: 前端显式带 cookie 头 > 服务端 cookie.txt (永远用最新有效身份)
  let cookieToSend = req.headers["cookie"] || "";
  if(!cookieToSend){
    try{ cookieToSend = fs.readFileSync(path.join(ROOT,"cookie.txt"),"utf8").trim(); }catch(e){}
  }
  const fwd={
    "host":UPSTREAM,"origin":"https://www.ainvest.com","referer":"https://www.ainvest.com/",
    "user-agent":req.headers["user-agent"]||"Mozilla/5.0",
    "accept":req.headers["accept"]||"text/event-stream",
    "accept-language":"zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "x-comefrom":req.headers["x-comefrom"]||"WebaimeRobot",
    "x-source":req.headers["x-source"]||"ths_wencai_international_pc_robot",
    "dnt":"1","cookie":cookieToSend
  };
  if(req.headers["content-type"]) fwd["content-type"]=req.headers["content-type"];
  if(body.length>0) fwd["content-length"]=String(body.length);
  const p=https.request({method:req.method,hostname:UPSTREAM,path:UP_PATH+url.pathname+url.search,headers:fwd,timeout:120000},pr=>{
    res.writeHead(pr.statusCode,{"content-type":pr.headers["content-type"]||"application/json","cache-control":"no-store","x-accel-buffering":"no"});
    pr.pipe(res);
  });
  p.on("error",e=>{res.writeHead(502);res.end(JSON.stringify({error:e.message}));});
  if(body.length>0) p.write(body);
  p.end();
});
server.listen(LISTEN,()=>console.log(`proxy http://localhost:${LISTEN} -> https://${UPSTREAM}${UP_PATH}`));
