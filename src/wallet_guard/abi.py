from __future__ import annotations

import re


ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}\Z")

BALANCE_OF_SELECTOR = "70a08231"
DECIMALS_SELECTOR = "313ce567"
TRANSFER_SELECTOR = "a9059cbb"


class AbiError(ValueError):
    """Raised when an address or ABI result is malformed."""


def normalize_address(value: str) -> str:
    normalized = value.strip()
    if not ADDRESS_PATTERN.fullmatch(normalized):
        raise AbiError(f"Endereco EVM invalido: {mask_address(normalized)}.")
    return normalized.lower()


def is_eip7702_delegation_code(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("0x"):
        return False
    payload = value[2:].lower()
    return len(payload) == 46 and payload.startswith("ef0100")


def mask_address(value: str) -> str:
    value = value.strip()
    if len(value) < 12:
        return "<invalido>"
    return f"{value[:6]}...{value[-4:]}"


def _address_word(address: str) -> str:
    return normalize_address(address)[2:].rjust(64, "0")


def encode_balance_of(owner: str) -> str:
    return f"0x{BALANCE_OF_SELECTOR}{_address_word(owner)}"


def encode_decimals() -> str:
    return f"0x{DECIMALS_SELECTOR}"


def encode_transfer(destination: str, amount_raw: int) -> str:
    if amount_raw < 0 or amount_raw >= 2**256:
        raise AbiError("Quantidade do token fora do intervalo uint256.")
    return (
        f"0x{TRANSFER_SELECTOR}{_address_word(destination)}"
        f"{amount_raw:064x}"
    )


def decode_uint256(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise AbiError("Resposta ABI nao hexadecimal.")
    payload = value[2:]
    if not payload or len(payload) > 64:
        raise AbiError("Resposta ABI nao representa uint256.")
    try:
        return int(payload, 16)
    except ValueError as exc:
        raise AbiError("Resposta ABI nao representa uint256.") from exc


def transfer_result_succeeded(value: str) -> bool:
    if value == "0x":
        return True
    return decode_uint256(value) != 0


def format_units(amount_raw: int, decimals: int | None) -> str:
    if decimals is None:
        return str(amount_raw)
    if decimals < 0 or decimals > 255:
        raise AbiError("Decimals fora do intervalo esperado.")
    if decimals == 0:
        return str(amount_raw)
    digits = str(amount_raw).rjust(decimals + 1, "0")
    whole, fraction = digits[:-decimals], digits[-decimals:].rstrip("0")
    return whole if not fraction else f"{whole}.{fraction}"
