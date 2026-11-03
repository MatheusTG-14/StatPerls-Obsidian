from pathlib import Path

import pytest

from src.installer import env
from src.installer.ui import UserError


def test_cloud_synced(monkeypatch):
    for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(k, raising=False)
    assert env.cloud_synced(Path("C:/Users/x/OneDrive/Vault")) == "OneDrive"
    assert env.cloud_synced(Path("C:/Users/x/OneDrive - Company/Vault")) == "OneDrive"
    assert env.cloud_synced(Path("D:/Google Drive/Vault")) == "Google Drive"
    assert env.cloud_synced(Path("G:/My Drive/Vault")) == "Google Drive"
    assert env.cloud_synced(Path("C:/Users/x/Dropbox/Vault")) == "Dropbox"
    assert env.cloud_synced(Path("C:/Users/x/iCloud Drive/Vault")) == "iCloud"
    assert env.cloud_synced(Path("D:/Study/Vault \u00e7")) is None


def test_cloud_synced_by_environment_variable(monkeypatch, tmp_path):
    sync = tmp_path / "Sync"
    monkeypatch.setenv("OneDrive", str(sync))
    assert env.cloud_synced(sync / "deep" / "Vault") == "OneDrive"
    assert env.cloud_synced(tmp_path / "Other") is None


def test_free_bytes_nonexistent_child(tmp_path):
    assert env.free_bytes(tmp_path / "a" / "b" / "c") > 0


def test_obsidian_title_match():
    assert env.title_matches("New tab - vault - Obsidian 1.12.7", "vault") is True
    assert env.title_matches("Doen\u00e7as biliares - __Obsidian - Obsidian 1.12.7", "vault") is False
    assert env.title_matches("Doen\u00e7as biliares - __Obsidian - Obsidian 1.12.7", "__Obsidian") is True
    assert env.title_matches("Untitled", "vault") is False


def test_check_python(monkeypatch):
    env.check_python()
    monkeypatch.setattr(env.sys, "version_info", (3, 11, 0, "final", 0))
    with pytest.raises(UserError):
        env.check_python()


def test_needed_bytes_is_sane():
    assert env.NEEDED_BYTES >= 1 << 30


def test_requirements_pinned():
    text = (Path(env.__file__).parent / "requirements.txt").read_text(encoding="utf-8")
    assert "lxml==6.1.1" in text and "PyYAML==6.0.3" in text and "jsonschema==4.26.0" in text
