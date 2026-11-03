"""Single key presses for the menu: msvcrt on Windows, termios elsewhere. Stdlib only.

read_key(timeout=None) -> "up", "down", "enter", "esc", "q", a digit, "other", or None when the timeout passes.
Ctrl+C raises KeyboardInterrupt promptly: Windows polls kbhit() in short sleeps instead of blocking in getwch(), and
POSIX keeps cbreak mode (no echo) for the whole menu via session() while Python still sees SIGINT.
"""
import contextlib
import os
import sys
import time

LEAD = ("\x00", "\xe0")
POLL = 0.05
_session_fd = [None]


def map_windows(first, second=""):
    """Windows console codes: arrows arrive as a lead code plus a second code; a lone lead code is an ordinary letter."""
    if first in LEAD:
        return {"H": "up", "P": "down"}.get(second, "other")
    return _map_char(first)


def map_posix(seq):
    """Terminal sequences: ESC [ A / ESC [ B (or ESC O A / ESC O B) for the arrows; a lone ESC is Esc."""
    if seq in ("\x1b[A", "\x1bOA"):
        return "up"
    if seq in ("\x1b[B", "\x1bOB"):
        return "down"
    if seq == "\x1b":
        return "esc"
    if seq.startswith("\x1b"):
        return "other"
    return _map_char(seq)


def _map_char(ch):
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x1b":
        return "esc"
    if ch.isdigit():
        return ch
    if ch in ("q", "Q"):
        return "q"
    if ch == "k":
        return "up"
    if ch == "j":
        return "down"
    return "other"


def _read_windows(timeout):
    import msvcrt
    end = None if timeout is None else time.monotonic() + timeout
    while not msvcrt.kbhit():  # never block in getwch(): a sleeping poll lets Ctrl+C interrupt at once
        if end is not None and time.monotonic() >= end:
            return None
        time.sleep(POLL)
    first = msvcrt.getwch()
    second = msvcrt.getwch() if first in LEAD and msvcrt.kbhit() else ""
    return map_windows(first, second)


def in_session():
    return _session_fd[0] is not None


@contextlib.contextmanager
def posix_session():
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        _session_fd[0] = fd
        yield
    finally:
        _session_fd[0] = None
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


@contextlib.contextmanager
def session():
    """Keep the terminal in no-echo single-key mode for a whole menu (nothing to do on Windows)."""
    if os.name == "nt":
        yield
    else:
        with posix_session():
            yield


def _read_posix(timeout):
    import select
    if in_session():
        return _read_posix_raw(timeout, select)
    with posix_session():
        return _read_posix_raw(timeout, select)


def _read_posix_raw(timeout, select):
    fd = sys.stdin.fileno()
    if timeout is not None and not select.select([sys.stdin], [], [], timeout)[0]:
        return None
    seq = os.read(fd, 1).decode("utf-8", "replace")
    if seq == "\x1b":  # an arrow key sends more bytes at once; a lone Esc does not
        while select.select([sys.stdin], [], [], 0.03)[0] and len(seq) < 3:
            seq += os.read(fd, 1).decode("utf-8", "replace")
    return map_posix(seq)


def read_key(timeout=None):
    return _read_windows(timeout) if os.name == "nt" else _read_posix(timeout)
