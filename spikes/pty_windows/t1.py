import sys,time,threading
from winpty import PtyProcess
p=PtyProcess.spawn([sys.executable,"echo_child.py"],dimensions=(24,80))
buf=[]
threading.Thread(target=lambda:[buf.append(p.read(65536)) for _ in iter(int,1)],daemon=True).start()
time.sleep(2);print(repr(buf));buf.clear()
p.write("a");time.sleep(.5);print(repr(buf));buf.clear()
p.write("#");time.sleep(.5);print(repr(buf));buf.clear()
p.setwinsize(30,120);time.sleep(.3);p.write("#");time.sleep(.5);print(repr(buf))
p.close(force=True)
