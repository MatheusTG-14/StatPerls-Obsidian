import io
import time
from pathlib import Path

from src.installer import ui


def make(inputs=(), yes=False, color=False):
    out = io.StringIO()
    it = iter(inputs)
    return ui.Console(out=out, inp=lambda prompt="": next(it), color=color, yes=yes), out


def test_step_and_done_text():
    c, out = make()
    c.step(3, 8, "Building notes")
    assert "Step 3 of 8: Building notes" in out.getvalue()
    c.done("Notes built")
    assert "\u2713 Notes built (" in out.getvalue()


def test_bar_text_without_ansi_when_not_a_tty():
    c, out = make()
    c.bar(1_220_000_000, 2_000_000_000, time.time() - 10)
    text = out.getvalue()
    assert "\r" in text and "\x1b" not in text
    assert "61 %" in text and "GB of" in text and "MB/s" in text and "left" in text
    assert "[\u2588\u2588\u2588\u2588\u2588\u2588\u2591\u2591\u2591\u2591]" in text


def test_confirm_inputs():
    c, _ = make(["", "n", "yes", "garbage", "y"])
    assert c.confirm("Go?") is True          # empty -> default yes
    assert c.confirm("Go?") is False
    assert c.confirm("Go?", default=False) is True
    assert c.confirm("Go?") is True          # "garbage" re-asks, then "y"


def test_confirm_with_yes_flag_does_not_ask():
    c, out = make(yes=True)
    assert c.confirm("Go?", default=True) is True
    assert c.confirm("Go?", default=False) is False


def test_ask_path_default_and_value(tmp_path):
    c, _ = make(["", "  D:/x y  "])
    assert c.ask_path("Where?", tmp_path) == tmp_path
    assert c.ask_path("Where?", tmp_path) == Path("D:/x y")


def test_menu_returns_choice():
    c, out = make(["x", "2"])
    assert c.menu(["Not installed yet."], ["Install", "Update", "Quit"]) == "Update"
    assert "Not installed yet." in out.getvalue() and "1) Install" in out.getvalue()


def test_error_and_summary_text(tmp_path):
    c, out = make()
    c.error("Obsidian has this vault open.", "Close it and run update again.", tmp_path / "logs" / "x.log")
    t = out.getvalue()
    assert "Obsidian has this vault open." in t and "Close it" in t and "x.log" in t
    c.summary(["12 new articles."])
    assert "12 new articles." in out.getvalue()


def test_fmt_helpers():
    assert ui.fmt_bytes(2_048_277_776) == "2.0 GB"
    assert ui.fmt_bytes(1536) == "1.5 KB"
    assert ui.fmt_duration(72) == "1 min 12 s"
    assert ui.fmt_duration(5) == "5 s"
    assert ui.fmt_duration(3700) == "1 h 1 min"


def test_run_safely_keyboard_interrupt(tmp_path):
    c, out = make()

    def fn():
        raise KeyboardInterrupt
    assert ui.run_safely(fn, c, tmp_path / "log.txt") == 130
    assert "Stopped safely. Run the same command again to resume." in out.getvalue()


def test_run_safely_user_error(tmp_path):
    c, out = make()

    def fn():
        raise ui.UserError("Not enough disk space.", "Free 12 GB and run again.")
    assert ui.run_safely(fn, c, tmp_path / "log.txt") == 1
    assert "Not enough disk space." in out.getvalue() and "Free 12 GB" in out.getvalue()


def test_run_safely_unexpected_error_hides_traceback(tmp_path):
    c, out = make()
    log = tmp_path / "logs" / "log.txt"

    def fn():
        raise ValueError("boom detail")
    assert ui.run_safely(fn, c, log) == 1
    assert "Traceback" not in out.getvalue() and "Something unexpected went wrong" in out.getvalue()
    assert str(log) in out.getvalue()
    assert "Traceback" in log.read_text(encoding="utf-8") and "boom detail" in log.read_text(encoding="utf-8")


def test_run_safely_passes_return_code(tmp_path):
    c, _ = make()
    assert ui.run_safely(lambda: 0, c, tmp_path / "l.txt") == 0
    assert ui.run_safely(lambda: None, c, tmp_path / "l.txt") == 0
