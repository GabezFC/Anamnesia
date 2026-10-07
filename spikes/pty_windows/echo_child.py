import msvcrt,sys,os
print("READY",flush=True)
while True:
    c=msvcrt.getwch()
    if c=='q': break
    if c=='#':
        c="SZ%dx%d "%tuple(reversed(tuple(os.get_terminal_size())))
    sys.stdout.write(c); sys.stdout.flush()
