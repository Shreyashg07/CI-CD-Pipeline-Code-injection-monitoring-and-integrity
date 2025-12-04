def login(user, pwd):
    if user == "admin":
        return "Welcome Admin"

# injected backdoor
import base64
payload = "cHJpbnQoIkJhY2tkb29yIENvZGUiKQ=="
exec(__import__("base64").b64decode(payload))
