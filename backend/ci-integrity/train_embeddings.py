"""
Enhanced training script:
- walks malicious_samples/* subfolders (categories)
- computes embeddings per sample using sentence-transformers
- saves a pickled DB at embeddings/malicious.pkl

Output structure (pickled list of dicts):
[
  {
    "category": "backdoors",
    "path": "malicious_samples/backdoors/backdoor_1.py",
    "text_snippet": "<first 1200 chars>",
    "embedding": numpy.array([...], dtype=float32)
  },
  ...
]
"""
import os
import pickle
from collections import defaultdict
from sentence_transformers import SentenceTransformer
from utils.file_reader import read_file_text
import numpy as np

# Config
MAL_DIR = "malicious_samples"
OUT_DIR = "embeddings"
OUT_FILE = os.path.join(OUT_DIR, "malicious.pkl")
MODEL_NAME = os.environ.get("PYGUARD_MODEL", "all-MiniLM-L6-v2")
MAX_SNIPPET = 1200  # chars

def gather_samples_by_category(root_dir):
    samples = []
    counts = defaultdict(int)
    for category in sorted(os.listdir(root_dir)):
        cat_path = os.path.join(root_dir, category)
        if not os.path.isdir(cat_path) or category.startswith("."):
            continue
        for fname in sorted(os.listdir(cat_path)):
            if fname.startswith("."):
                continue
            fpath = os.path.join(cat_path, fname)
            text = read_file_text(fpath)
            if not text:
                continue
            samples.append({
                "category": category,
                "path": fpath,
                "text": text
            })
            counts[category] += 1
    return samples, counts

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.isdir(MAL_DIR):
        print(f"[train] Error: {MAL_DIR} not found. Create malicious_samples/ with subfolders.")
        return

    print(f"[train] Loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    samples, counts = gather_samples_by_category(MAL_DIR)
    total = len(samples)
    print(f"[train] Found total {total} samples across categories:")
    for c, n in counts.items():
        print(f"  - {c}: {n}")

    if total == 0:
        print("[train] No samples to embed. Exiting.")
        return

    texts = [s["text"] for s in samples]

    # compute embeddings (batched inside model.encode)
    print("[train] Computing embeddings (this may take a moment)...")
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

    # build DB entries
    db = []
    for s, emb in zip(samples, embeddings):
        db.append({
            "category": s["category"],
            "path": s["path"],
            "text_snippet": s["text"][:MAX_SNIPPET],
            # cast to float32 to keep file size lower and ensure pickling portability
            "embedding": emb.astype("float32")
        })

    # save DB
    with open(OUT_FILE, "wb") as f:
        pickle.dump(db, f)

    print(f"[train] Saved {len(db)} embeddings to {OUT_FILE}")
    # optionally write a small index summary
    idx_file = os.path.join(OUT_DIR, "index.txt")
    with open(idx_file, "w", encoding="utf-8") as fi:
        fi.write(f"model: {MODEL_NAME}\n")
        fi.write(f"total_samples: {len(db)}\n")
        for c, n in counts.items():
            fi.write(f"{c}: {n}\n")
    print(f"[train] Wrote summary to {idx_file}")

if __name__ == "__main__":
    main()
