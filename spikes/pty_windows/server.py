import asyncio,json,os,secrets,shutil,sys,threading
from urllib.parse import urlparse,parse_qs
from http import HTTPStatus
from winpty import PtyProcess
from websockets.asyncio.server import serve
from websockets.http11 import Response
from websockets.datastructures import Headers
HERE=os.path.dirname(os.path.abspath(__file__))
PORT=int(os.environ.get("PORT","8766")); TOKEN=secrets.token_urlsafe(24)
ALLOWED_ORIGINS={f"http://127.0.0.1:{PORT}"}
CMDS={"cmd":["cmd.exe"],"claude":[shutil.which("claude")],"hermes":[shutil.which("hermes")]}
STATIC={"/vendor/xterm.js":("vendor/xterm-xterm-6.0.0/package/lib/xterm.js","text/javascript"),
 "/vendor/xterm.css":("vendor/xterm-xterm-6.0.0/package/css/xterm.css","text/css"),
 "/vendor/addon-fit.js":("vendor/xterm-addon-fit-0.11.0/package/lib/addon-fit.js","text/javascript")}
def resp(code,body=b"",ct="text/plain"):
    return Response(code,HTTPStatus(code).phrase,Headers([("Content-Type",ct),("Content-Length",str(len(body))),("Cache-Control","no-store")]),body)
def page_req(conn,req):
    u=urlparse(req.path); q=parse_qs(u.query)
    if u.path=="/ws":
        if req.headers.get("Origin") not in ALLOWED_ORIGINS: return resp(403,b"bad origin")
        protos=[p.strip() for p in req.headers.get("Sec-WebSocket-Protocol","").split(",")]
        if not any(secrets.compare_digest(p,"tok."+TOKEN) for p in protos): return resp(401,b"bad token")
        if q.get("cmd",[""])[0] not in CMDS: return resp(400,b"bad cmd")
        return None
    if u.path=="/":
        if not secrets.compare_digest(q.get("t",[""])[0],TOKEN): return resp(401,b"token")
        return resp(200,open(os.path.join(HERE,"index.html"),"rb").read(),"text/html; charset=utf-8")
    if u.path in STATIC:
        f,ct=STATIC[u.path]; return resp(200,open(os.path.join(HERE,f),"rb").read(),ct)
    return resp(404,b"nf")
def pick(conn,subs): return next((s for s in subs if s=="tok."+TOKEN),None)
async def handler(ws):
    q=parse_qs(urlparse(ws.request.path).query)
    argv=CMDS[q["cmd"][0]]; rows=int(q.get("rows",["24"])[0]); cols=int(q.get("cols",["80"])[0])
    pt=PtyProcess.spawn(argv,dimensions=(rows,cols),cwd=os.environ.get("TEMP","C:/"))
    print("spawn",argv,"pid",pt.pid,flush=True)
    loop=asyncio.get_running_loop(); qu=asyncio.Queue()
    def pump():
        try:
            while True: loop.call_soon_threadsafe(qu.put_nowait,pt.read(65536))
        except Exception: loop.call_soon_threadsafe(qu.put_nowait,None)
    threading.Thread(target=pump,daemon=True).start()
    async def tx():
        while (d:=await qu.get()) is not None: await ws.send(d)
        await ws.close(1000,"child exited")
    t=asyncio.create_task(tx())
    try:
        async for m in ws:
            j=json.loads(m)
            if j["t"]=="in": pt.write(j["d"])
            elif j["t"]=="rs": pt.setwinsize(int(j["rows"]),int(j["cols"]))
    finally:
        t.cancel(); pt.close(force=True); print("closed pid",pt.pid,flush=True)
async def main():
    async with serve(handler,"127.0.0.1",PORT,process_request=page_req,select_subprotocol=pick,subprotocols=None):
        print("TOKEN",TOKEN,flush=True); await asyncio.Future()
if __name__=="__main__": asyncio.run(main())
