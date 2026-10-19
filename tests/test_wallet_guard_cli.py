from __future__ import annotations

import sys

import pytest

import wallet_guard.cli as cli
from wallet_guard.config import GuardConfigurationError


def test_execute_requires_literal_confirmation_before_loading_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["wallet_guard", "--execute-native"])

    def must_not_load_config(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("configuracao nao deveria ser carregada")

    monkeypatch.setattr(cli, "load_guard_settings", must_not_load_config)

    with pytest.raises(SystemExit, match="SEND_NATIVE_BALANCES"):
        cli.main()


def test_execute_confirmation_still_requires_execution_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wallet_guard",
            "--execute-native",
            "--confirm-mainnet",
            "SEND_NATIVE_BALANCES",
        ],
    )
    execution_modes: list[bool] = []

    def blocked_config(
        _env_file: object,
        *,
        execution_mode: bool,
    ) -> None:
        execution_modes.append(execution_mode)
        raise GuardConfigurationError("flags de execucao ausentes")

    monkeypatch.setattr(cli, "load_guard_settings", blocked_config)

    with pytest.raises(SystemExit, match="flags de execucao ausentes"):
        cli.main()

    assert execution_modes == [True]
