import pytest


@pytest.fixture(autouse=True)
def _private_installer_config(tmp_path_factory, monkeypatch):
    """Installer commands remember vault folders in the user profile; tests keep that list in a temp folder."""
    monkeypatch.setenv("SP_CONFIG_DIR", str(tmp_path_factory.mktemp("installer-config")))
