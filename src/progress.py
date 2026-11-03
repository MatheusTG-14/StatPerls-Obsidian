"""Coarse progress reports from long pipeline stages to whoever listens (the installer dashboard).

Stdlib only. Without a listener every call is a no-op, so `sp.py` output and the vault bytes are unchanged (rule 5).
"""
import contextlib
import time

STEPS = ("unpack", "figures", "read", "classify", "notes", "figure-notes", "search")
EVERY = 50      # forward at least every this many items ...
MIN_GAP = 0.25  # ... or this many seconds

_listener = None
_last = {"step": None, "done": 0, "at": 0.0}


def set_listener(fn):
    """fn(step, done, total, unit) or None to stop listening."""
    global _listener
    _listener = fn
    _last.update(step=None, done=0, at=0.0)


def _forward(step, done, total, unit):
    _last.update(step=step, done=done, at=time.monotonic())
    try:
        _listener(step, done, total, unit)
    except Exception:  # noqa: BLE001 - a display problem must never stop the pipeline
        pass


def tick(step, done, total, unit=""):
    if _listener is None:
        return
    if (_last["step"] != step or done == total or done < _last["done"] or done - _last["done"] >= EVERY
            or time.monotonic() - _last["at"] >= MIN_GAP):
        _forward(step, done, total, unit)


@contextlib.contextmanager
def stage(name, total=0, unit=""):
    """Announces the start (0 of total) and the end (total of total) of a stage."""
    if _listener is not None:
        _forward(name, 0, total, unit)
    yield
    if _listener is not None:
        _forward(name, total, total, unit)
