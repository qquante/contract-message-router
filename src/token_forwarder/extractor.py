from __future__ import annotations

import re
from typing import Literal

Network = Literal["auto", "solana", "evm"]

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_VALUES = {character: index for index, character in enumerate(_BASE58_ALPHABET)}

_EVM_PATTERN = re.compile(r"(?<![0-9A-Fa-f])0x[0-9A-Fa-f]{40}(?![0-9A-Fa-f])")
_SOLANA_PATTERN = re.compile(
    r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])"
)


def _is_solana_public_key(value: str) -> bool:
    """Validate that a Base58 string decodes to exactly 32 bytes."""
    if not 32 <= len(value) <= 44:
        return False

    number = 0
    try:
        for character in value:
            number = number * 58 + _BASE58_VALUES[character]
    except KeyError:
        return False

    leading_zero_bytes = len(value) - len(value.lstrip("1"))
    payload_bytes = (number.bit_length() + 7) // 8
    return leading_zero_bytes + payload_bytes == 32


def extract_contracts(text: str, network: Network = "auto") -> tuple[str, ...]:
    """Return unique valid contracts in the same order they appear in the text."""
    matches: list[tuple[int, str]] = []

    if network in {"auto", "evm"}:
        matches.extend((match.start(), match.group(0)) for match in _EVM_PATTERN.finditer(text))

    if network in {"auto", "solana"}:
        matches.extend(
            (match.start(), match.group(0))
            for match in _SOLANA_PATTERN.finditer(text)
            if _is_solana_public_key(match.group(0))
        )

    unique: list[str] = []
    seen: set[str] = set()
    for _, contract in sorted(matches, key=lambda item: item[0]):
        identity = contract.lower() if contract.startswith("0x") else contract
        if identity not in seen:
            seen.add(identity)
            unique.append(contract)
    return tuple(unique)


def extract_single_contract(text: str, network: Network = "auto") -> str | None:
    """Return one unambiguous contract; zero or multiple contracts return None."""
    contracts = extract_contracts(text, network)
    return contracts[0] if len(contracts) == 1 else None

