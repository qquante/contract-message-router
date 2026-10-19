from pathlib import Path

import pytest

from wallet_guard.config import GuardConfigurationError, load_guard_settings

SOURCE = "0x1111111111111111111111111111111111111111"
SAFE = "0x2222222222222222222222222222222222222222"


def _valid_guard_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLET_GUARD_DRY_RUN", "true")
    monkeypatch.setenv("WALLET_GUARD_SIGNING_ENABLED", "false")
    monkeypatch.setenv("WALLET_GUARD_BROADCAST_ENABLED", "false")
    monkeypatch.setenv("WALLET_GUARD_REQUIRE_PROXY", "true")
    monkeypatch.setenv("WALLET_GUARD_RETRY_ATTEMPTS", "10")
    monkeypatch.setenv("WALLET_GUARD_SOURCE_WALLET", SOURCE)
    monkeypatch.setenv("WALLET_GUARD_SAFE_WALLET", SAFE)
    monkeypatch.setenv("WALLET_GUARD_CHAINS", "ethereum")
    monkeypatch.setenv("WALLET_GUARD_RPC_ETHEREUM", "https://rpc.example")
    monkeypatch.setenv(
        "WALLET_GUARD_PROXY_URL",
        "socks5h://private-user:private-password@127.0.0.1:1080",
    )


def test_loads_strict_read_only_configuration_without_exposing_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_guard_environment(monkeypatch)
    settings = load_guard_settings(tmp_path / "missing.env")

    assert settings.retry_attempts == 10
    assert settings.safe_wallet == SAFE
    assert settings.proxy_url is not None
    summary = settings.safe_summary()
    assert SOURCE not in summary
    assert SAFE not in summary
    assert "private-password" not in summary


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WALLET_GUARD_DRY_RUN", "false"),
        ("WALLET_GUARD_SIGNING_ENABLED", "true"),
        ("WALLET_GUARD_BROADCAST_ENABLED", "true"),
    ],
)
def test_refuses_any_signing_or_broadcast_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str
) -> None:
    _valid_guard_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(GuardConfigurationError, match="Modo inseguro"):
        load_guard_settings(tmp_path / "missing.env")


def test_requires_proxy_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_guard_environment(monkeypatch)
    monkeypatch.delenv("WALLET_GUARD_PROXY_URL")

    with pytest.raises(GuardConfigurationError, match="conexao direta"):
        load_guard_settings(tmp_path / "missing.env")


def test_one_safe_wallet_and_proxy_are_shared_by_multiple_chains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_guard_environment(monkeypatch)
    monkeypatch.setenv("WALLET_GUARD_CHAINS", "ethereum,bnb")
    monkeypatch.setenv("WALLET_GUARD_RPC_BNB", "https://bsc.example")

    settings = load_guard_settings(tmp_path / "missing.env")

    assert settings.safe_wallet == SAFE
    assert settings.proxy_url == (
        "socks5h://private-user:private-password@127.0.0.1:1080"
    )
    assert [item.chain.key for item in settings.chains] == ["ethereum", "bnb"]


def test_rejects_unichain_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_guard_environment(monkeypatch)
    monkeypatch.setenv("WALLET_GUARD_CHAINS", "unichain")

    with pytest.raises(GuardConfigurationError, match="nao permitida"):
        load_guard_settings(tmp_path / "missing.env")


def test_execution_mode_requires_all_three_explicit_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_guard_environment(monkeypatch)

    with pytest.raises(GuardConfigurationError, match="Execucao mainnet bloqueada"):
        load_guard_settings(tmp_path / "missing.env", execution_mode=True)


def test_execution_mode_accepts_only_all_eight_chains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_guard_environment(monkeypatch)
    monkeypatch.setenv("WALLET_GUARD_DRY_RUN", "false")
    monkeypatch.setenv("WALLET_GUARD_SIGNING_ENABLED", "true")
    monkeypatch.setenv("WALLET_GUARD_BROADCAST_ENABLED", "true")

    with pytest.raises(GuardConfigurationError, match="8 redes"):
        load_guard_settings(tmp_path / "missing.env", execution_mode=True)


def test_execution_mode_accepts_exactly_all_eight_chains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _valid_guard_environment(monkeypatch)
    monkeypatch.setenv("WALLET_GUARD_DRY_RUN", "false")
    monkeypatch.setenv("WALLET_GUARD_SIGNING_ENABLED", "true")
    monkeypatch.setenv("WALLET_GUARD_BROADCAST_ENABLED", "true")
    chain_keys = (
        "ethereum",
        "stable",
        "base",
        "bnb",
        "robinhood",
        "arbitrum",
        "hyperevm",
        "avalanche",
    )
    monkeypatch.setenv("WALLET_GUARD_CHAINS", ",".join(chain_keys))
    for key in chain_keys:
        monkeypatch.setenv(f"WALLET_GUARD_RPC_{key.upper()}", f"https://{key}.example")

    settings = load_guard_settings(
        tmp_path / "missing.env",
        execution_mode=True,
    )

    assert tuple(item.chain.key for item in settings.chains) == chain_keys
