import os
import json
import pickle
import sys
from datetime import datetime
from sentence_transformers import SentenceTransformer
import numpy as np

# ✅ Fix Windows encoding issue for special characters like "→"
sys.stdout.reconfigure(encoding='utf-8')

from utils.file_reader import read_file_text
from utils.similarity import cosine_sim


# =========================
# CONFIG
# =========================

EMBEDDINGS_FILE = r"D:\ai-cicd-security-tool\backend\ci-integrity\embeddings\malicious.pkl"
REPORT_DIR = "reports"
MODEL_NAME = "all-MiniLM-L6-v2"

# Risk thresholds
THRESHOLD_LOW = 0.50
THRESHOLD_MED = 0.65
THRESHOLD_HIGH = 0.80

# Folders to ignore
IGNORE_FOLDERS = [
    "venv", "env", "__pycache__", ".git", "node_modules",
    ".idea", ".vscode", "dist", "build", "migrations"
]

# File extensions to scan
SCAN_FILE_TYPES = (
    ".py", ".js", ".sh", ".yml", ".yaml",
    ".json", ".php", ".txt", "Dockerfile"
)


# =========================
# LOADING FUNCTIONS
# =========================

def load_embeddings():
    if not os.path.exists(EMBEDDINGS_FILE):
        raise FileNotFoundError("Missing embedding DB: " + EMBEDDINGS_FILE)

    with open(EMBEDDINGS_FILE, "rb") as f:
        return pickle.load(f)


def classify_risk(score):
    if score >= THRESHOLD_HIGH:
        return "HIGH"
    elif score >= THRESHOLD_MED:
        return "MEDIUM"
    elif score >= THRESHOLD_LOW:
        return "LOW"
    else:
        return "SAFE"


def threat_score(score):
    """Convert cosine similarity → threat % out of 100."""
    return round(score * 100, 1)


# =========================
# FILE CHUNKING
# =========================

def chunk_text(text, size=1500, overlap=200):
    """Split large files into overlapping chunks for better accuracy."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


# =========================
# SCANNING FUNCTIONS
# =========================

def scan_chunk(model, chunk, db):
    emb = model.encode(chunk, convert_to_numpy=True)

    best_score = 0
    best_entry = None

    for entry in db:
        sim = cosine_sim(emb, entry["embedding"])
        if sim > best_score:
            best_score = sim
            best_entry = entry

    return best_score, best_entry


def scan_file(model, filepath, db):
    """Return highest score from ALL chunks of the file."""
    text = read_file_text(filepath)
    if not text.strip():
        return None, None

    chunks = chunk_text(text)
    best_score = 0
    best_entry = None

    for ch in chunks:
        score, entry = scan_chunk(model, ch, db)
        if score > best_score:
            best_score = score
            best_entry = entry

    return best_score, best_entry


def scan_repo(repo_path, fail_on_high=False):
    print("[pyguard] Loading model:", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    print("[pyguard] Loading malicious DB...")
    db = load_embeddings()

    os.makedirs(REPORT_DIR, exist_ok=True)
    print(f"[pyguard] Scanning repo: {repo_path}")

    findings = []
    total_files = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORE_FOLDERS]

        for f in files:
            fp = os.path.join(root, f)

            if not fp.endswith(SCAN_FILE_TYPES):
                continue

            total_files += 1
            score, entry = scan_file(model, fp, db)
            if score is None or score < THRESHOLD_LOW:
                continue

            risk = classify_risk(score)
            tscore = threat_score(score)

            print(f"[alert] {fp} -> {risk} ({tscore}%)")

            findings.append({
                "file": fp,
                "score": float(score),
                "threat_percent": tscore,
                "risk": risk,
                "category": entry["category"],
                "matched_sample": entry["path"],
                "snippet": entry["text_snippet"][:300]
            })

    # Build summary
    summary = {
        "timestamp": str(datetime.now()),
        "repository": repo_path,
        "files_scanned": total_files,
        "findings": len(findings),
        "overall_risk": max([f["risk"] for f in findings], default="SAFE"),
        "details": findings
    }

    # Save reports
    json_report = os.path.join(REPORT_DIR, "embedding_report.json")
    with open(json_report, "w", encoding="utf-8") as jf:
        json.dump(summary, jf, indent=4)

    html_report = os.path.join(REPORT_DIR, "embedding_report.html")
    with open(html_report, "w", encoding="utf-8") as hf:
        hf.write(generate_html(summary))

    print(f"\n[pyguard] JSON report: {json_report}")
    print(f"[pyguard] HTML report: {html_report}")

    # Auto-fail if high risk
    if fail_on_high and summary["overall_risk"] == "HIGH":
        print("[pyguard] High-risk detected -> exiting with code 1")
        sys.exit(1)

    return summary


# =========================
# HTML REPORT
# =========================

def generate_html(data):
    html = f"""
    <html>
    <head>
        <title>PyGuard AI Report</title>
        <style>
            body {{ font-family: Arial; background:#f2f2f2; }}
            .card {{ background:#fff; padding:15px; margin:15px; border-radius:8px;
                     box-shadow: 0 0 6px #bbb; }}
            .HIGH {{ color:red; font-weight:bold; }}
            .MEDIUM {{ color:orange; font-weight:bold; }}
            .LOW {{ color:green; font-weight:bold; }}
        </style>
    </head>
    <body>
        <h1>PyGuard AI — Integrity Scan Report</h1>

        <div class="card">
            <b>Timestamp:</b> {data["timestamp"]}<br>
            <b>Repository:</b> {data["repository"]}<br>
            <b>Files scanned:</b> {data["files_scanned"]}<br>
            <b>Findings:</b> {data["findings"]}<br>
            <b>Overall Risk:</b> {data["overall_risk"]}<br>
        </div>
    """

    for f in data["details"]:
        html += f"""
        <div class="card">
            <h3 class="{f["risk"]}">Risk: {f["risk"]} ({f["threat_percent"]}%)</h3>
            <b>Category:</b> {f["category"]}<br>
            <b>File:</b> {f["file"]}<br>
            <b>Matched:</b> {f["matched_sample"]}<br><br>
            <code>{f["snippet"]}</code>
        </div>
        """

    html += "</body></html>"
    return html


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pyguard_embedding.py <repo-path> [--fail-on-high]")
        sys.exit(1)

    repo = sys.argv[1]
    flag = "--fail-on-high" in sys.argv

    scan_repo(repo, fail_on_high=flag)
