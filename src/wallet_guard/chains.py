from __future__ import annotations

from dataclasses import dataclass


class UnsupportedChainError(ValueError):
    """Raised when a chain is not part of the protection allowlist."""


@dataclass(frozen=True, slots=True)
class Chain:
    key: str
    name: str
    chain_id: int
    native_symbol: str
    explorer_url: str
    state_block_tag: str = "pending"


CHAINS: tuple[Chain, ...] = (
    Chain("ethereum", "Ethereum Mainnet", 1, "ETH", "https://etherscan.io"),
    Chain("stable", "Stable Mainnet", 988, "USDT0", "https://stablescan.xyz"),
    Chain("base", "Base Mainnet", 8453, "ETH", "https://base.blockscout.com"),
    Chain("bnb", "BNB Smart Chain", 56, "BNB", "https://bscscan.com"),
    Chain(
        "robinhood",
        "Robinhood Chain",
        4663,
        "ETH",
        "https://robinhoodchain.blockscout.com",
    ),
    Chain("arbitrum", "Arbitrum One", 42161, "ETH", "https://arbiscan.io"),
    # O RPC padrao do HyperEVM suporta consultas de estado somente em "latest".
    Chain(
        "hyperevm",
        "HyperEVM",
        999,
        "HYPE",
        "https://hyperevmscan.io",
        "latest",
    ),
    Chain(
        "avalanche",
        "Avalanche C-Chain",
        43114,
        "AVAX",
        "https://explorer.avax.network/c-chain",
    ),
)

_BY_KEY = {chain.key: chain for chain in CHAINS}
_BY_ID = {chain.chain_id: chain for chain in CHAINS}


def get_chain(value: str | int) -> Chain:
    if isinstance(value, int):
        chain = _BY_ID.get(value)
    else:
        chain = _BY_KEY.get(value.strip().lower())
    if chain is None:
        raise UnsupportedChainError(f"Rede nao permitida: {value}.")
    return chain
