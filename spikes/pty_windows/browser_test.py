import asyncio,sys,json,re,time,functools
print=functools.partial(print,flush=True)
import server
from websockets.asyncio.server import serve
from playwright.async_api import async_playwright
PORT=server.PORT
def buf(page): return page.evaluate("""()=>{const b=term.buffer.active,o=[];for(let i=0;i<b.length;i++){const l=b.getLine(i);o.push(l?l.translateToString(true):'')}return o}""")
async def tail(page): 
    L=await buf(page); 
    while L and not L[-1].strip(): L.pop()
    return L
async def open_sess(ctx,cmd,w=1000,h=600):
    page=await ctx.new_page(); await page.set_viewport_size({"width":w,"height":h})
    await page.goto(f"http://127.0.0.1:{PORT}/?t={server.TOKEN}&cmd={cmd}")
    await page.wait_for_function("window.wsState==='open'"); await page.evaluate("term.focus()"); return page
async def main():
    async with serve(server.handler,"127.0.0.1",PORT,process_request=server.page_req,select_subprotocol=server.pick):
        async with async_playwright() as p:
            br=await p.chromium.launch(); ctx=await br.new_context()
            # security checks
            r=await ctx.request.get(f"http://127.0.0.1:{PORT}/"); print("no token page ->",r.status)
            pg=await ctx.new_page(); await pg.goto("about:blank")
            res=await pg.evaluate(f"""()=>new Promise(r=>{{const w=new WebSocket('ws://127.0.0.1:{PORT}/ws?cmd=cmd',['tok.wrong']);w.onerror=()=>r('error');w.onopen=()=>r('OPEN')}})""")
            print("bad-origin/bad-token ws ->",res); await pg.close()
            # cmd.exe
            page=await open_sess(ctx,"cmd")
            await page.wait_for_function("term.buffer.active.getLine(0).translateToString(true).length>0",timeout=10000)
            await asyncio.sleep(1)
            print("INIT buffer:",await tail(page))
            await page.keyboard.type("echo hello"); await page.keyboard.press("Enter"); await asyncio.sleep(1)
            L=await tail(page); print("after echo:",L)
            await page.screenshot(path="shots/cmd_echo.png")
            print("cols/rows before:",await page.evaluate("[term.cols,term.rows]"))
            await page.keyboard.type("mode con"); await page.keyboard.press("Enter"); await asyncio.sleep(1)
            print("mode con:",[l for l in await tail(page) if re.search("Lines|Columns|Linhas|Colunas",l)])
            await page.set_viewport_size({"width":700,"height":400}); await asyncio.sleep(1)
            print("cols/rows after:",await page.evaluate("[term.cols,term.rows]"))
            await page.keyboard.type("mode con"); await page.keyboard.press("Enter"); await asyncio.sleep(1)
            print("mode con after resize:",[l for l in await tail(page) if re.search("Lines|Columns|Linhas|Colunas",l)])
            await page.screenshot(path="shots/cmd_resized.png")
            await page.keyboard.type("exit"); await page.keyboard.press("Enter")
            try: await page.wait_for_function("window.wsState==='closed'",timeout=20000); print("cmd closed:",await page.evaluate("closeInfo"))
            except Exception: print("cmd NOT closed; tail:",(await tail(page))[-8:])
            # agents
            for name,exitseq in (("claude",["Control+c","Control+c"]),("hermes",["Control+c","Control+c"])):
                page=await open_sess(ctx,name,1200,750)
                await asyncio.sleep(12)
                await page.screenshot(path=f"shots/{name}_tui.png")
                L=await tail(page); print(f"== {name} buffer ({len(L)} lines):"); print("\n".join(L[:40]))
                await page.set_viewport_size({"width":900,"height":500}); await asyncio.sleep(2)
                await page.screenshot(path=f"shots/{name}_resized.png")
                print(name,"size after resize",await page.evaluate("[term.cols,term.rows]"))
                t0=time.time()
                for k in exitseq:
                    await page.keyboard.press(k); await asyncio.sleep(1)
                try: await page.wait_for_function("window.wsState==='closed'",timeout=10000); print("close latency s",round(time.time()-t0,1)); print(name,"exited cleanly:",await page.evaluate("closeInfo"))
                except Exception: print(name,"did not exit via Ctrl+C; closing page"); 
                await page.screenshot(path=f"shots/{name}_after_exit.png")
                await page.close(); await asyncio.sleep(1)
            await br.close()
asyncio.run(main())
