Flask backend for the CI/CD pipeline system.

Quick start (Windows PowerShell):

1. Create and activate a Python venv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run the app

```powershell
python app.py
```

The backend listens on port 5000 by default and exposes APIs under `/api/...`.
SocketIO is available at the same host (no path configured). The frontend's connection string is intentionally left empty for you to fill in later.
