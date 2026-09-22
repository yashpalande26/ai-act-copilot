import pytest

from app import config


def test_conftest_forces_test_environment():
    # conftest.py sets APP_ENV=test before anything imports; the whole suite
    # depends on this so its trace rows never count against production.
    assert config.app_env() == "test"


def test_default_is_dev_when_unset(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    assert config.app_env() == "dev"


def test_production_must_be_explicit(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert config.app_env() == "production"


def test_unknown_value_is_refused(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(RuntimeError, match="APP_ENV='staging'"):
        config.app_env()


def test_vocabulary_is_closed():
    assert set(config.APP_ENVIRONMENTS) == {"production", "dev", "test"}


def test_daily_limits_default_to_the_measured_constants_and_read_env(monkeypatch):
    from app.config import daily_limit_global, daily_limit_per_user

    monkeypatch.delenv("DAILY_LIMIT_PER_USER", raising=False)
    monkeypatch.delenv("DAILY_LIMIT_GLOBAL", raising=False)
    assert daily_limit_per_user() == 20 and daily_limit_global() == 100
    monkeypatch.setenv("DAILY_LIMIT_PER_USER", "200")
    monkeypatch.setenv("DAILY_LIMIT_GLOBAL", "500")
    assert daily_limit_per_user() == 200 and daily_limit_global() == 500
