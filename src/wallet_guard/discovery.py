from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from wallet_guard.abi import AbiError, normalize_address
from wallet_guard.chains import UnsupportedChainError, get_chain


class TokenDiscoveryError(ValueError):
    """Raised when detector output is invalid, stale or for another wallet."""


@dataclass(frozen=True, slots=True)
class TokenDiscovery:
    source_wallet: str
    tokens_by_chain: dict[str, tuple[str, ...]]

    def tokens_for(self, chain_key: str) -> tuple[str, ...]:
        return self.tokens_by_chain.get(chain_key, ())


def _address(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TokenDiscoveryError(f"{field} deve ser um endereco EVM.")
    try:
        return normalize_address(value)
    except AbiError as exc:
        raise TokenDiscoveryError(f"{field}: endereco EVM invalido.") from exc


def load_token_discovery(
    path: Path, *, expected_source_wallet: str
) -> TokenDiscovery:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TokenDiscoveryError("Arquivo de descoberta nao pode ser lido.") from exc
    except json.JSONDecodeError as exc:
        raise TokenDiscoveryError("Arquivo de descoberta contem JSON invalido.") from exc

    if not isinstance(raw, dict):
        raise TokenDiscoveryError("Descoberta deve ser um objeto JSON.")
    source_wallet = _address(raw.get("source_wallet"), "source_wallet")
    if source_wallet != expected_source_wallet:
        raise TokenDiscoveryError(
            "Descoberta pertence a outra carteira de origem; execucao recusada."
        )

    raw_chains = raw.get("chains")
    if not isinstance(raw_chains, dict):
        raise TokenDiscoveryError("chains deve ser um objeto JSON.")

    tokens_by_chain: dict[str, tuple[str, ...]] = {}
    for raw_key, raw_tokens in raw_chains.items():
        if not isinstance(raw_key, str):
            raise TokenDiscoveryError("Chave de rede invalida na descoberta.")
        try:
            chain = get_chain(raw_key)
        except UnsupportedChainError as exc:
            raise TokenDiscoveryError(str(exc)) from exc
        if not isinstance(raw_tokens, list):
            raise TokenDiscoveryError(
                f"chains.{chain.key} deve ser uma lista de contratos."
            )

        tokens: list[str] = []
        seen: set[str] = set()
        for index, raw_token in enumerate(raw_tokens):
            token = _address(raw_token, f"chains.{chain.key}[{index}]")
            if token not in seen:
                seen.add(token)
                tokens.append(token)
        tokens_by_chain[chain.key] = tuple(tokens)

    return TokenDiscovery(source_wallet, tokens_by_chain)
