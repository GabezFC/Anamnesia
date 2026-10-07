import asyncio,json,os,re,statistics,subprocess,sys,threading,time,shutil
from winpty import PtyProcess
import websockets
HERE=os.path.dirname(os.path.abspath(__file__)); PY=sys.executable
_bufs={}
def rd(p,secs=2.0,until=None):
    if id(p) not in _bufs:
        buf=_bufs[id(p)]=[]
        def r():
            try:
                while True: buf.append(p.read(65536))
            except Exception: pass
        threading.Thread(target=r,daemon=True).start()
    buf=_bufs[id(p)]; end=time.time()+secs
    while time.time()<end:
        if until and until in "".join(buf): break
        time.sleep(0.05)
    o="".join(buf); buf.clear(); return o
def strip(o): return re.sub(r"\[[0-9;?]*[A-Za-z]|\][^]*(|\\)","",o)
def pids(): 
    o=subprocess.run(["powershell","-NoProfile","-Command","Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|$($_.CommandLine)\" }"],capture_output=True,text=True,encoding='utf-8',errors='replace').stdout or ''
    return o.splitlines()
def exe(n): return shutil.which(n)
print("== A: one-shot")
for argv in (["cmd","/c","echo hi"],[exe("claude"),"--version"],[exe("hermes"),"--version"]):
    p=PtyProcess.spawn(argv,dimensions=(24,80)); o=rd(p,4)
    print(argv[:2],repr(o[:200]))
print("== B: resize + stdin (echo_child)")
p=PtyProcess.spawn([PY,os.path.join(HERE,"echo_child.py")],dimensions=(24,80)); print(repr(rd(p,6,"READY")[-40:]))
p.write("#"); print("80x24 ->",repr(rd(p,1.5,"SZ")))
p.setwinsize(30,120); time.sleep(.3)
p.write("#"); print("after resize ->",repr(rd(p,1.5,"SZ")))
p.write("q"); time.sleep(.7); print("alive after q:",p.isalive())
print("== C: claude TUI probe")
p=PtyProcess.spawn([exe("claude")],dimensions=(24,80),cwd=os.environ.get("TEMP","C:/"))
o=rd(p,6); print("bytes",len(o),"ansi",len(re.findall(r"\x1b\[",o)),repr(o[:150]))
p.setwinsize(30,120); o2=rd(p,2); print("after resize bytes",len(o2),"redraw ansi",len(re.findall(r"\x1b\[",o2)))
before=set(pids()); p.close(force=True); time.sleep(2)
print("claude alive:",p.isalive())
print("== D: hermes TUI probe")
p=PtyProcess.spawn([exe("hermes")],dimensions=(24,80),cwd=os.environ.get("TEMP","C:/"))
o=rd(p,8); print("bytes",len(o),"ansi",len(re.findall(r"\x1b\[",o)),repr(o[:150]))
p.setwinsize(30,120); o2=rd(p,2); print("after resize bytes",len(o2))
p.close(force=True); time.sleep(2); print("hermes alive:",p.isalive())
print("== E: WS latency")
async def main():
    async def h(ws):
        pt=PtyProcess.spawn([PY,os.path.join(HERE,"echo_child.py")],dimensions=(24,80))
        loop=asyncio.get_running_loop(); q=asyncio.Queue()
        def pump():
            try:
                while True: loop.call_soon_threadsafe(q.put_nowait,pt.read(65536))
            except Exception: loop.call_soon_threadsafe(q.put_nowait,None)
        threading.Thread(target=pump,daemon=True).start()
        async def tx():
            while (d:=await q.get()) is not None: await ws.send(d)
        t=asyncio.create_task(tx())
        try:
            async for m in ws:
                j=json.loads(m)
                if j["t"]=="in": pt.write(j["d"])
                else: pt.setwinsize(j["rows"],j["cols"])
        finally: t.cancel(); pt.close(force=True)
    async with websockets.serve(h,"127.0.0.1",8765):
        async with websockets.connect("127.0.0.1" and "ws://127.0.0.1:8765") as c:
            acc=""
            while "READY" not in acc: acc+=await asyncio.wait_for(c.recv(),15)
            await c.send(json.dumps({"t":"rs","rows":30,"cols":120})); await asyncio.sleep(.3)
            await c.send(json.dumps({"t":"in","d":"#"})); acc=""
            while "SZ" not in acc or not acc.rstrip().endswith("x120") and "x120" not in acc: acc+=await asyncio.wait_for(c.recv(),3)
            print("WS resize ->",repr(acc))
            lat=[]
            for i in range(200):
                ch="abcdefghijklmnoprstuvwxyz"[i%25]
                t0=time.perf_counter(); await c.send(json.dumps({"t":"in","d":ch}))
                while True:
                    m=await asyncio.wait_for(c.recv(),3)
                    if ch in m: break
                lat.append((time.perf_counter()-t0)*1000); await asyncio.sleep(.01)
            lat.sort(); print("n",len(lat),"median %.2f p95 %.2f max %.2f min %.2f"%(statistics.median(lat),lat[int(.95*len(lat))],lat[-1],lat[0]))
asyncio.run(main())
import subprocess as sp
print("== F: grandchild kill")
p=PtyProcess.spawn([PY,os.path.join(HERE,"gc_child.py")],dimensions=(24,80)); o=rd(p,15,"GC "); print(repr(o))
gc=int(re.search(r"GC (\d+)",o).group(1)); print("child",p.pid,"gc",gc)
def alive(n): return any(l.startswith(f"{n}|") for l in pids())
print("before close alive child/gc:",alive(p.pid),alive(gc))
p.close(force=True); time.sleep(2)
print("after close alive child/gc:",alive(p.pid),alive(gc))
if alive(gc): subprocess.run(["taskkill","/F","/T","/PID",str(gc)],capture_output=True)
