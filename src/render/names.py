"""Filenames: sanitizing, collision handling, and the persistent registry (rule 11)."""
import re
import unicodedata
from pathlib import Path

from src.common import read_json, write_json

ILLEGAL = re.compile(r'[\\/:*?"<>|#^\[\]]')
MAX_STEM = 150


def sanitize(title):
    s = unicodedata.normalize("NFC", title)
    s = s.replace(": ", " - ").replace(":", "-")
    s = ILLEGAL.sub("-", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(". ")
    if len(s) > MAX_STEM:
        s = s[:MAX_STEM].rstrip(". -")
    return s or "untitled"


def fold(stem):
    """Key used for collision checks: NTFS is case-insensitive."""
    return unicodedata.normalize("NFC", stem).casefold()


class Registry:
    """Maps permanent keys to vault stems. Assigned once, never changed."""

    def __init__(self, path):
        self.path = Path(path)
        data = read_json(self.path) if self.path.exists() else {}
        self.maps = {k: dict(v) for k, v in data.items()}
        self.taken = {}
        for ns, m in self.maps.items():
            self.taken[ns] = {fold(v) for v in m.values()}

    def get(self, ns, key):
        return self.maps.get(ns, {}).get(key)

    def assign(self, ns, key, wanted, suffix):
        m = self.maps.setdefault(ns, {})
        taken = self.taken.setdefault(ns, set())
        if key in m:
            return m[key]
        stem = wanted
        if fold(stem) in taken:
            stem = f"{wanted} ({suffix})"
        n = 2
        while fold(stem) in taken:
            stem = f"{wanted} ({suffix} {n})"
            n += 1
        m[key] = stem
        taken.add(fold(stem))
        return stem

    def assign_with(self, ns, key, make):
        """make(n) -> candidate name for attempt n (1, 2, ...); first free one wins."""
        m = self.maps.setdefault(ns, {})
        taken = self.taken.setdefault(ns, set())
        if key in m:
            return m[key]
        n = 1
        while fold(make(n)) in taken:
            n += 1
        m[key] = make(n)
        taken.add(fold(m[key]))
        return m[key]

    def sticky(self, ns, key, value, force=False):
        """Non-unique value assigned once (e.g. category folder); only force replaces it."""
        m = self.maps.setdefault(ns, {})
        if force or key not in m:
            m[key] = value
        return m[key]

    def save(self):
        write_json(self.path, self.maps)
