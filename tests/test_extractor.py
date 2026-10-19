import pytest

from token_forwarder.extractor import extract_contracts, extract_single_contract

SOLANA_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOLANA_WRAPPED_SOL = "So11111111111111111111111111111111111111112"
EVM_CONTRACT = "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (f"CA: {SOLANA_USDC}", SOLANA_USDC),
        (f"Contrato\n{SOLANA_WRAPPED_SOL}\n", SOLANA_WRAPPED_SOL),
        (f"Token: `{EVM_CONTRACT}`", EVM_CONTRACT),
        (f"https://solscan.io/token/{SOLANA_USDC}?cluster=mainnet", SOLANA_USDC),
        (f"({SOLANA_USDC}).", SOLANA_USDC),
    ],
)
def test_extracts_exact_contract(message: str, expected: str) -> None:
    assert extract_single_contract(message) == expected


def test_deduplicates_repeated_contract() -> None:
    message = f"CA: {SOLANA_USDC}\nCopy: {SOLANA_USDC}"
    assert extract_contracts(message) == (SOLANA_USDC,)


def test_rejects_ambiguous_message() -> None:
    message = f"Token A: {SOLANA_USDC}\nToken B: {SOLANA_WRAPPED_SOL}"
    assert extract_single_contract(message) is None
    assert extract_contracts(message) == (SOLANA_USDC, SOLANA_WRAPPED_SOL)


def test_network_filter() -> None:
    message = f"{SOLANA_USDC} {EVM_CONTRACT}"
    assert extract_contracts(message, "solana") == (SOLANA_USDC,)
    assert extract_contracts(message, "evm") == (EVM_CONTRACT,)


@pytest.mark.parametrize(
    "message",
    [
        "sem contrato",
        "0x1234",
        "O0Il-not-base58-111111111111111111111111",
        "11111111111111111111111111111111111111111111",
    ],
)
def test_rejects_invalid_candidates(message: str) -> None:
    assert extract_contracts(message) == ()

