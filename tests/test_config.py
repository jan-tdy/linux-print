import json

from linuxprint import config


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)


def test_load_settings_defaults_when_file_missing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    settings = config.load_settings()
    assert settings.check_interval_seconds == 30
    assert settings.autoheal_enabled is True


def test_load_settings_defaults_on_non_object_json(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config.SETTINGS_FILE.write_text("[]", encoding="utf-8")
    assert config.load_settings() == config.Settings()

    config.SETTINGS_FILE.write_text("null", encoding="utf-8")
    assert config.load_settings() == config.Settings()


def test_load_settings_rejects_wrong_field_type(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config.SETTINGS_FILE.write_text(
        json.dumps({"check_interval_seconds": "30", "autoheal_enabled": True}), encoding="utf-8"
    )
    settings = config.load_settings()
    # the bad field falls back to its default instead of poisoning the object
    assert settings.check_interval_seconds == 30
    assert isinstance(settings.check_interval_seconds, int)
    assert settings.autoheal_enabled is True


def test_load_settings_keeps_valid_values(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config.SETTINGS_FILE.write_text(
        json.dumps({"check_interval_seconds": 90, "notifications_enabled": False}), encoding="utf-8"
    )
    settings = config.load_settings()
    assert settings.check_interval_seconds == 90
    assert settings.notifications_enabled is False
