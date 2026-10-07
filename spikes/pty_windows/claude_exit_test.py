import asyncio,time,functools
print=functools.partial(print,flush=True)
import server
from websockets.asyncio.server import serve
from playwright.async_api import async_playwright
async def main():
    async with serve(server.handler,"127.0.0.1",server.PORT,process_request=server.page_req,select_subprotocol=server.pick):
        async with async_playwright() as p:
            br=await p.chromium.launch(); ctx=await br.new_context()
            for keys in (["Control+c","Control+c"],["Enter"]):  # Enter on default "No, exit" (declines trust)
                pg=await ctx.new_page(); await pg.set_viewport_size({"width":1200,"height":750})
                await pg.goto(f"http://127.0.0.1:{server.PORT}/?t={server.TOKEN}&cmd=claude")
                await pg.wait_for_function("window.wsState==='open'"); await pg.evaluate("term.focus()"); await asyncio.sleep(10)
                t0=time.time()
                for k in keys: await pg.keyboard.press(k); await asyncio.sleep(1.2)
                try: await pg.wait_for_function("window.wsState==='closed'",timeout=10000); print(keys,"-> closed after",round(time.time()-t0,1),await pg.evaluate("closeInfo"))
                except Exception: print(keys,"-> still open; closing page")
                await pg.close(); await asyncio.sleep(1)
            await br.close()
asyncio.run(main())
