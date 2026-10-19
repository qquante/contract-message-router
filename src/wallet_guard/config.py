from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from wallet_guard.abi import AbiError, mask_address, normalize_address
from wallet_guard.chains import CHAINS, Chain, UnsupportedChainError, get_chain


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GuardConfigurationError(ValueError):
    """Raised when the read-only wallet guard is not fail-closed."""


@dataclass(frozen=True, slots=True)
class ChainSettings:
    chain: Chain
    rpc_url: str

    def safe_summary(self) -> str:
        return f"{self.chain.key}(id={self.chain.chain_id})"


@dataclass(frozen=True, slots=True)
class GuardSettings:
    source_wallet: str
    safe_wallet: str
    proxy_url: str | None
    chains: tuple[ChainSettings, ...]
    dry_run: bool
    signing_enabled: bool
    broadcast_enabled: bool
    require_proxy: bool
    retry_attempts: int
    rpc_timeout_seconds: float

    def safe_summary(self) -> str:
        chain_summary = ", ".join(item.safe_summary() for item in self.chains)
        return (
            f"origem={mask_address(self.source_wallet)}; "
            f"destino={mask_address(self.safe_wallet)}; redes=[{chain_summary}]; "
            f"proxy_global={'sim' if self.proxy_url else 'nao'}; "
            f"dry_run={self.dry_run}; assinatura={self.signing_enabled}; "
            f"broadcast={self.broadcast_enabled}; retries={self.retry_attempts}"
        )


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise GuardConfigurationError(f"{name} deve ser true ou false.")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise GuardConfigurationError(f"Defina {name} no .env.")
    return value


def _validate_url(name: str, value: str, schemes: set[str]) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in schemes or not parsed.hostname:
        expected = ", ".join(sorted(schemes))
        raise GuardConfigurationError(f"{name} deve usar {expected} e conter hostname.")
    return value


def _parse_address(name: str, value: str) -> str:
    try:
        return normalize_address(value)
    except AbiError as exc:
        raise GuardConfigurationError(f"{name}: {exc}") from exc


def load_guard_settings(
    env_file: Path | None = None,
    *,
    execution_mode: bool = False,
) -> GuardSettings:
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    dry_run = _parse_bool("WALLET_GUARD_DRY_RUN", True)
    signing_enabled = _parse_bool("WALLET_GUARD_SIGNING_ENABLED", False)
    broadcast_enabled = _parse_bool("WALLET_GUARD_BROADCAST_ENABLED", False)
    require_proxy = _parse_bool("WALLET_GUARD_REQUIRE_PROXY", True)

    if execution_mode and (
        dry_run or not signing_enabled or not broadcast_enabled
    ):
        raise GuardConfigurationError(
            "Execucao mainnet bloqueada: exige WALLET_GUARD_DRY_RUN=false, "
            "WALLET_GUARD_SIGNING_ENABLED=true e "
            "WALLET_GUARD_BROADCAST_ENABLED=true."
        )
    if not execution_mode and (
        not dry_run or signing_enabled or broadcast_enabled
    ):
        raise GuardConfigurationError(
            "Modo inseguro recusado: mantenha WALLET_GUARD_DRY_RUN=true, "
            "WALLET_GUARD_SIGNING_ENABLED=false e "
            "WALLET_GUARD_BROADCAST_ENABLED=false."
        )

    retry_raw = os.getenv("WALLET_GUARD_RETRY_ATTEMPTS", "10").strip()
    try:
        retry_attempts = int(retry_raw)
    except ValueError as exc:
        raise GuardConfigurationError(
            "WALLET_GUARD_RETRY_ATTEMPTS deve ser inteiro."
        ) from exc
    if retry_attempts != 10:
        raise GuardConfigurationError("WALLET_GUARD_RETRY_ATTEMPTS deve ser 10.")

    timeout_raw = os.getenv("WALLET_GUARD_RPC_TIMEOUT_SECONDS", "15").strip()
    try:
        rpc_timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise GuardConfigurationError(
            "WALLET_GUARD_RPC_TIMEOUT_SECONDS deve ser numerico."
        ) from exc
    if not 1 <= rpc_timeout_seconds <= 120:
        raise GuardConfigurationError(
            "WALLET_GUARD_RPC_TIMEOUT_SECONDS deve ficar entre 1 e 120."
        )

    source_wallet = _parse_address(
        "WALLET_GUARD_SOURCE_WALLET", _required("WALLET_GUARD_SOURCE_WALLET")
    )
    safe_wallet = _parse_address(
        "WALLET_GUARD_SAFE_WALLET", _required("WALLET_GUARD_SAFE_WALLET")
    )
    if safe_wallet == source_wallet:
        raise GuardConfigurationError(
            "WALLET_GUARD_SAFE_WALLET deve ser diferente da carteira de origem."
        )

    proxy_name = "WALLET_GUARD_PROXY_URL"
    proxy_raw = os.getenv(proxy_name, "").strip()
    if require_proxy and not proxy_raw:
        raise GuardConfigurationError(
            f"Defina {proxy_name}; conexao direta esta bloqueada."
        )
    proxy_url = (
        _validate_url(
            proxy_name, proxy_raw, {"http", "https", "socks5", "socks5h"}
        )
        if proxy_raw
        else None
    )

    chain_keys = tuple(
        item.strip().lower()
        for item in os.getenv("WALLET_GUARD_CHAINS", "").split(",")
        if item.strip()
    )
    if not chain_keys:
        raise GuardConfigurationError("Defina WALLET_GUARD_CHAINS no .env.")
    if len(chain_keys) != len(set(chain_keys)):
        raise GuardConfigurationError("WALLET_GUARD_CHAINS contem rede repetida.")
    if execution_mode and set(chain_keys) != {chain.key for chain in CHAINS}:
        raise GuardConfigurationError(
            "Execucao mainnet exige exatamente as 8 redes permitidas."
        )

    chain_settings: list[ChainSettings] = []
    for key in chain_keys:
        try:
            chain = get_chain(key)
        except UnsupportedChainError as exc:
            raise GuardConfigurationError(str(exc)) from exc
        suffix = chain.key.upper()
        rpc_name = f"WALLET_GUARD_RPC_{suffix}"

        rpc_url = _validate_url(rpc_name, _required(rpc_name), {"https"})
        chain_settings.append(
            ChainSettings(
                chain=chain,
                rpc_url=rpc_url,
            )
        )

    return GuardSettings(
        source_wallet=source_wallet,
        safe_wallet=safe_wallet,
        proxy_url=proxy_url,
        chains=tuple(chain_settings),
        dry_run=dry_run,
        signing_enabled=signing_enabled,
        broadcast_enabled=broadcast_enabled,
        require_proxy=require_proxy,
        retry_attempts=retry_attempts,
        rpc_timeout_seconds=rpc_timeout_seconds,
    )
