# utils/file_reader.py
import os

def read_file_text(path, max_size=200_000):
    """
    Read file as text. Truncate files larger than max_size.
    Returns a string or empty string on failure.
    """
    try:
        with open(path, "r", errors="ignore") as f:
            text = f.read(max_size)
            return text
    except Exception:
        return ""
