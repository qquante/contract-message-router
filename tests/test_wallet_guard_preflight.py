from collections.abc import Sequence
from typing import Any

import pytest

from wallet_guard.chains import get_chain
from wallet_guard.preflight import PreflightError, run_chain_preflight

SOURCE = "0x1111111111111111111111111111111111111111"
SAFE = "0x2222222222222222222222222222222222222222"
TOKEN = "0x3333333333333333333333333333333333333333"


class FakeRpc:
    def __init__(
        self,
        *,
        chain_id: int = 8453,
        transfer_succeeds: bool = True,
        source_code: str = "0x",
    ) -> None:
        self.chain_id = chain_id
        self.transfer_succeeds = transfer_succeeds
        self.source_code = source_code
        self.methods: list[str] = []
        self.requests: list[tuple[str, Sequence[Any]]] = []

    def call(self, method: str, params: Sequence[Any] = ()) -> Any:
        self.methods.append(method)
        self.requests.append((method, params))
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_blockNumber":
            return hex(123456)
        if method == "eth_getBalance":
            return hex(10**18)
        if method == "eth_getTransactionCount":
            return "0xc"
        if method == "eth_gasPrice":
            return hex(10**9)
        if method == "eth_getCode":
            address = params[0]
            if address == TOKEN:
                return "0x60006000"
            if address == SOURCE:
                return self.source_code
            return "0x"
        if method == "eth_call":
            call = params[0]
            data = call["data"]
            if data.startswith("0x70a08231"):
                return hex(150_000_000)
            if data == "0x313ce567":
                return hex(6)
            if data.startswith("0xa9059cbb"):
                return hex(1 if self.transfer_succeeds else 0)
        if method == "eth_estimateGas":
            call = params[0]
            return hex(50_000 if call["data"].startswith("0xa9059cbb") else 21_000)
        raise AssertionError(f"Metodo inesperado: {method} {params}")


def test_preflight_proves_token_then_native_without_signing() -> None:
    rpc = FakeRpc()
    report = run_chain_preflight(
        rpc,
        chain=get_chain("base"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
        token_addresses=(TOKEN,),
    )

    assert report.passed
    assert report.tokens[0].status == "ready"
    assert report.tokens[0].display_balance == "150"
    assert report.native.status == "ready"
    assert report.execution_order == (f"token:0x3333...3333", "native:ETH")
    assert report.native.sendable_raw < report.native.balance_raw
    assert "eth_sendRawTransaction" not in rpc.methods
    assert "eth_sendTransaction" not in rpc.methods


@pytest.mark.parametrize(
    ("chain_key", "expected_symbol"),
    [
        ("ethereum", "ETH"),
        ("stable", "USDT0"),
        ("base", "ETH"),
        ("bnb", "BNB"),
        ("robinhood", "ETH"),
        ("arbitrum", "ETH"),
        ("hyperevm", "HYPE"),
        ("avalanche", "AVAX"),
    ],
)
def test_same_read_only_native_and_token_flow_covers_every_approved_chain(
    chain_key: str, expected_symbol: str
) -> None:
    chain = get_chain(chain_key)
    report = run_chain_preflight(
        FakeRpc(chain_id=chain.chain_id),
        chain=chain,
        source_wallet=SOURCE,
        safe_wallet=SAFE,
        token_addresses=(TOKEN,),
    )

    assert report.passed
    assert report.native.symbol == expected_symbol
    assert report.execution_order[-1] == f"native:{expected_symbol}"


def test_preflight_fails_when_token_transfer_returns_false() -> None:
    report = run_chain_preflight(
        FakeRpc(transfer_succeeds=False),
        chain=get_chain("base"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
        token_addresses=(TOKEN,),
    )

    assert not report.passed
    assert report.tokens[0].status == "failed"
    assert report.tokens[0].error == "transfer retornou false"


def test_preflight_rejects_rpc_connected_to_wrong_chain() -> None:
    with pytest.raises(PreflightError, match="rede errada"):
        run_chain_preflight(
            FakeRpc(chain_id=1),
            chain=get_chain("base"),
            source_wallet=SOURCE,
            safe_wallet=SAFE,
            token_addresses=(),
        )


def test_hyperevm_uses_latest_for_state_reads() -> None:
    chain = get_chain("hyperevm")
    rpc = FakeRpc(chain_id=chain.chain_id)

    run_chain_preflight(
        rpc,
        chain=chain,
        source_wallet=SOURCE,
        safe_wallet=SAFE,
        token_addresses=(TOKEN,),
    )

    state_reads = [
        params[-1]
        for method, params in rpc.requests
        if method in {"eth_getBalance", "eth_getTransactionCount", "eth_call"}
    ]
    assert state_reads
    assert set(state_reads) == {"latest"}


def test_eip7702_delegated_eoa_is_allowed_with_warning() -> None:
    delegation = "0xef0100" + "44" * 20
    report = run_chain_preflight(
        FakeRpc(source_code=delegation),
        chain=get_chain("base"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
        token_addresses=(),
    )

    assert report.passed
    assert report.source_has_code
    assert report.source_is_eip7702
    assert any("EIP-7702" in line for line in report.safe_lines())


def test_regular_contract_source_remains_blocked() -> None:
    report = run_chain_preflight(
        FakeRpc(source_code="0x60006000"),
        chain=get_chain("base"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
        token_addresses=(),
    )

    assert not report.passed
    assert report.source_has_code
    assert not report.source_is_eip7702
