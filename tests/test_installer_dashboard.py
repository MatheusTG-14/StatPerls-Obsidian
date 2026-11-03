import io
import re
from pathlib import Path

import pytest

from src import progress
from src.installer.dashboard import Dashboard, estimate_left, phase_fraction
from src.installer.ui import Console

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
STEPS = ["Checking this computer", "Preparing the Python libraries", "Setting up your folder", "Getting the StatPearls archive",
         "Unpacking articles and figures", "Reading the articles", "Building your notes", "Finishing"]
TYPICAL = {1: 2, 2: 30, 3: 5, 4: 200, 5: 162, 6: 1050, 7: 1128, 8: 30}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(plain, width=100):
    out = io.StringIO()
    return Console(out=out, inp=lambda p="": "", plain=plain, width=width), out


def drive(d, clock):
    d.start(1)
    clock.t = 2
    d.finish(1)
    d.start(2)
    clock.t = 40
    d.finish(2, "Libraries are ready")
    d.skip(3, "already done")
    d.start(6)
    clock.t = 100
    progress.tick("read", 4120, 9651, "articles")
    d.warn("Could not confirm the file against NLM's list.")


@pytest.mark.parametrize("width", [100, 60])
def test_rich_dashboard_content_and_fit(width):
    c, out = make(False, width)
    clock = Clock()
    with Dashboard(c, "Installing", Path("C:/Vault"), "25 Oct 2026", STEPS, TYPICAL, clock=clock) as d:
        drive(d, clock)
    text = ANSI.sub("", out.getvalue())
    assert "\u2713" in text and "1 min 12 s" not in text
    assert "4,120 of 9,651 articles" in text
    assert "Elapsed" in text and "left" in text
    assert "Ctrl+C stops safely" in text and "run the same command again to resume" in text
    assert "Could not confirm" in text and "skipped" in text.lower()
    assert "Installing" in text and "25 Oct 2026" in text
    for line in text.splitlines():
        assert len(line) <= width, line


def test_finished_steps_show_their_duration():
    c, out = make(False)
    clock = Clock()
    with Dashboard(c, "Installing", Path("C:/Vault"), "d", STEPS, TYPICAL, clock=clock) as d:
        d.start(2)
        clock.t = 72
        d.finish(2)
    assert "1 min 12 s" in ANSI.sub("", out.getvalue())


def test_preset_done_steps_from_the_first_process():
    c, out = make(False)
    clock = Clock()
    with Dashboard(c, "Installing", Path("C:/Vault"), "d", STEPS, TYPICAL, clock=clock, done_before={1: 3.0, 2: 61.0}) as d:
        d.start(3)
    text = ANSI.sub("", out.getvalue())
    assert "1 min 1 s" in text and "3 s" in text


def test_bytes_detail_has_speed_and_time_left():
    c, out = make(False)
    clock = Clock()
    with Dashboard(c, "Installing", Path("C:/Vault"), "d", STEPS, TYPICAL, clock=clock) as d:
        d.start(4)
        d.detail(0, 2_000_000_000, "bytes")
        clock.t = 10
        d.detail(200_000_000, 2_000_000_000, "bytes")
    text = ANSI.sub("", out.getvalue())
    assert "200.0 MB of 2.0 GB" in text and "20.0 MB/s" in text and "left" in text


def test_interrupt_restores_terminal():
    c, out = make(False)
    clock = Clock()
    with pytest.raises(KeyboardInterrupt):
        with Dashboard(c, "Installing", Path("C:/Vault"), "d", STEPS, TYPICAL, clock=clock) as d:
            d.start(1)
            raise KeyboardInterrupt
    assert out.getvalue().rstrip("\n").endswith("\x1b[?25h")
    assert progress._listener is None


def test_handoff_removes_the_display():
    c, out = make(False)
    clock = Clock()
    with Dashboard(c, "Installing", Path("C:/Vault"), "d", STEPS, TYPICAL, clock=clock) as d:
        d.start(2)
        d.handoff()
    assert progress._listener is None
    tail = out.getvalue().rsplit(chr(27) + "[?25h", 1)[1]   # cursor shown, then only erase codes
    assert re.fullmatch(r"(\x1b\[[0-9;]*[A-Za-z]|\r|\n)*", tail)

def test_plain_mode_lines():
    c, out = make(True)
    clock = Clock()
    with Dashboard(c, "Installing", Path("C:/Vault"), "25 Oct 2026", STEPS, TYPICAL, clock=clock) as d:
        d.start(6)
        for done in (10, 20, 30):          # three ticks inside 10 s -> one detail line
            clock.t += 1
            progress.tick("read", done, 9651, "articles")
        clock.t += 20
        progress.tick("read", 5000, 9651, "articles")
        d.finish(6)
        d.skip(7, "nothing to do")
    text = out.getvalue()
    assert "\x1b" not in text
    assert "Step 6 of 8: Reading the articles" in text
    assert text.count(" of 9,651 articles") == 2
    assert "Installing" in text and "skipped" in text


def test_listener_is_removed_after_exit():
    c, _ = make(True)
    with Dashboard(c, "Installing", Path("C:/Vault"), "d", STEPS, TYPICAL, clock=Clock()):
        assert progress._listener is not None
    assert progress._listener is None


def test_estimate_left_uses_current_rate_then_typical_for_the_rest():
    typical = {1: 10, 2: 10, 3: 10}
    # step 1 half done after 100 s: another 100 s, then steps 2 and 3 at their typical times
    assert estimate_left(typical, 1, 0.5, 100) == pytest.approx(120)
    # no usable rate yet: typical time for the rest of the current step
    assert estimate_left(typical, 1, 0.0, 1) == pytest.approx(30)
    # skipped steps are not counted
    assert estimate_left(typical, 1, 0.5, 100, skipped={3}) == pytest.approx(110)
    assert estimate_left(typical, 3, 1.0, 5) == pytest.approx(0)


def test_phase_fraction_weights_the_phases_of_the_building_step():
    assert phase_fraction(7, "classify", 0.0) == pytest.approx(0.0)
    assert 0.0 < phase_fraction(7, "notes", 0.5) < 1.0
    assert phase_fraction(7, "notes", 1.0) < phase_fraction(7, "search", 1.0) <= 1.0
    assert phase_fraction(4, "bytes", 0.25) == pytest.approx(0.25)


def test_ctrl_c_inside_the_live_display_shows_the_stopped_panel(tmp_path):
    from src.installer.ui import run_safely
    c, out = make(False)
    clock = Clock()

    def fn():
        with Dashboard(c, "Installing", Path("C:/Vault"), "d", STEPS, TYPICAL, clock=clock) as d:
            d.start(6)
            raise KeyboardInterrupt
    assert run_safely(fn, c, tmp_path / "l.log") == 130
    raw = out.getvalue()
    assert raw.index(chr(27) + "[?25h") < raw.index("Stopped safely")
    assert "Traceback" not in raw
