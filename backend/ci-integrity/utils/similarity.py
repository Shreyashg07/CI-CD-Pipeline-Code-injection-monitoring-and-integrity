# utils/similarity.py
import numpy as np

def cosine_sim(a: np.ndarray, b: np.ndarray):
    # a, b: 1D numpy arrays
    if a is None or b is None:
        return 0.0
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
