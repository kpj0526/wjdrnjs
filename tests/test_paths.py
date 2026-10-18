import sys

from r2clicker import paths


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_HELPER_HOME", str(tmp_path / "home"))
    assert paths.data_dir() == tmp_path / "home"
    assert paths.settings_path() == tmp_path / "home" / "settings.json"
    assert paths.resolve_in_data_dir("logs") == tmp_path / "home" / "logs"
    assert paths.resolve_in_data_dir(str(tmp_path / "abs")) == tmp_path / "abs"


def test_frozen_uses_exe_folder_when_writable(tmp_path, monkeypatch):
    monkeypatch.delenv("R2_HELPER_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "R2TargetHelper.exe"))
    assert paths.data_dir() == tmp_path


def test_frozen_falls_back_to_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("R2_HELPER_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ro" / "R2TargetHelper.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.setattr(paths, "_writable", lambda d: False)
    assert paths.data_dir() == tmp_path / "lad" / paths.APP_NAME


def test_source_checkout_uses_repo_root(monkeypatch):
    monkeypatch.delenv("R2_HELPER_HOME", raising=False)
    assert (paths.data_dir() / "README.md").is_file()


def test_bundled_sample_present():
    p = paths.sample_image()
    assert p is not None and p.name == "sample_1600x900.png"


def test_bundle_resource_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.resource_path("assets/x.png") == tmp_path / "assets" / "x.png"
