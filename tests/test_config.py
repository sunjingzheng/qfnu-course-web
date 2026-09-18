import json
import stat

import pytest

from qfnu_course_web.config import AppConfig, ConfigError, ConfigStore


def test_config_store_creates_a_private_default_file(tmp_path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)

    config = store.load_or_create()

    assert config == AppConfig()
    assert json.loads(path.read_text())["version"] == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_config_store_round_trips_valid_settings_atomically(tmp_path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    config = AppConfig.model_validate(
        {
            "account": {"username": "2024000000"},
            "auth": {"ocr_url": "http://127.0.0.1:9000"},
            "selection": {
                "round_keywords": ["补选", "正选"],
                "start_time": "09:59:00",
                "term_id": "2026-1",
            },
        }
    )

    store.save(config)

    loaded = store.load_or_create()
    assert loaded.account.username == "2024000000"
    assert loaded.selection.start_time.isoformat() == "09:59:00"
    assert not list(tmp_path.glob("*.tmp"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_config_store_does_not_overwrite_a_corrupt_file(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    store = ConfigStore(path)

    with pytest.raises(ConfigError, match="无法读取"):
        store.load_or_create()

    assert path.read_text(encoding="utf-8") == "{broken"


def test_config_rejects_passwords_and_unknown_versions() -> None:
    with pytest.raises(ValueError):
        AppConfig.model_validate({"account": {"username": "1", "password": "secret"}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"version": 2})
