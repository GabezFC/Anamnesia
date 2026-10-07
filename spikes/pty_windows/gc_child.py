import subprocess,sys,time
g=subprocess.Popen([sys.executable,"-c","import time;time.sleep(300)"])
print("GC",g.pid,flush=True)
time.sleep(300)
