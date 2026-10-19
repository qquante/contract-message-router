import pytest

from wallet_guard.chains import CHAINS, UnsupportedChainError, get_chain


def test_allowlist_contains_exactly_the_eight_approved_networks() -> None:
    assert {chain.chain_id for chain in CHAINS} == {
        1,
        56,
        988,
        999,
        4663,
        8453,
        42161,
        43114,
    }
    assert get_chain("stable").native_symbol == "USDT0"
    assert get_chain("hyperevm").native_symbol == "HYPE"


def test_unichain_is_rejected() -> None:
    with pytest.raises(UnsupportedChainError):
        get_chain(130)
    with pytest.raises(UnsupportedChainError):
        get_chain("unichain")
