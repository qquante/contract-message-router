from pathlib import Path

import pytest

from token_forwarder.config import ConfigurationError, load_settings

API_HASH = "0123456789abcdef0123456789abcdef"


def _valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", API_HASH)
    monkeypatch.setenv("EXPECTED_ACCOUNT_USERNAME", "@KenjiHL")
    monkeypatch.setenv("DESTINATION_CHAT", "t.me/helenus_trojanbot")
    monkeypatch.setenv("SOURCE_CHATS", "")
    monkeypatch.setenv("ALLOW_ANY_PRIVATE_SOURCE", "true")
    monkeypatch.setenv("DRY_RUN", "true")


def test_loads_and_normalizes_safe_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_environment(monkeypatch)

    settings = load_settings(tmp_path / "missing.env")

    assert settings.expected_account_username == "kenjihl"
    assert settings.destination_chat == "@helenus_trojanbot"
    assert settings.allow_any_private_source
    assert API_HASH not in settings.safe_summary()


def test_requires_source_or_explicit_private_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_environment(monkeypatch)
    monkeypatch.setenv("ALLOW_ANY_PRIVATE_SOURCE", "false")

    with pytest.raises(ConfigurationError, match="SOURCE_CHATS"):
        load_settings(tmp_path / "missing.env")


def test_rejects_malformed_api_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_environment(monkeypatch)
    monkeypatch.setenv("TELEGRAM_API_HASH", "nao-e-um-api-hash")

    with pytest.raises(ConfigurationError, match="32 caracteres"):
        load_settings(tmp_path / "missing.env")


def test_rejects_frequency_outside_windows_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_environment(monkeypatch)
    monkeypatch.setenv("BEEP_FREQUENCY_HZ", "888000000")

    with pytest.raises(ConfigurationError, match="37 e 32767"):
        load_settings(tmp_path / "missing.env")


def test_channel_source_does_not_require_channel_name_as_account_username(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_environment(monkeypatch)
    monkeypatch.setenv("EXPECTED_ACCOUNT_USERNAME", "")
    monkeypatch.setenv("SOURCE_CHATS", "t.me/kenjihl")
    monkeypatch.setenv("ALLOW_ANY_PRIVATE_SOURCE", "false")

    settings = load_settings(tmp_path / "missing.env")

    assert settings.expected_account_username is None
    assert settings.source_chats == ("@kenjihl",)
    assert not settings.allow_any_private_source
