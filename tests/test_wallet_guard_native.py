from collections.abc import Sequence
from typing import Any

import pytest

from wallet_guard.chains import get_chain
from wallet_guard.native import BASE_GAS_PRICE_ORACLE, NativePlanError, build_native_plan

SOURCE = "0x1111111111111111111111111111111111111111"
SAFE = "0x2222222222222222222222222222222222222222"


class NativeRpc:
    def __init__(
        self,
        *,
        chain_id: int,
        balance: int = 10**18,
        base_fee: int | None = 100,
        priority_fee: int = 2,
        gas_price: int = 100,
        l1_upper_bound: int = 0,
        source_code: str = "0x",
    ) -> None:
        self.chain_id = chain_id
        self.balance = balance
        self.base_fee = base_fee
        self.priority_fee = priority_fee
        self.gas_price = gas_price
        self.l1_upper_bound = l1_upper_bound
        self.source_code = source_code
        self.calls: list[tuple[str, Sequence[Any]]] = []

    def call(self, method: str, params: Sequence[Any] = ()) -> Any:
        self.calls.append((method, params))
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getBalance":
            return hex(self.balance)
        if method == "eth_getTransactionCount":
            return "0x7"
        if method == "eth_getCode":
            return self.source_code if params[0] == SOURCE else "0x"
        if method == "eth_estimateGas":
            return hex(21_000)
        if method == "eth_getBlockByNumber":
            return (
                {"baseFeePerGas": hex(self.base_fee)}
                if self.base_fee is not None
                else {}
            )
        if method == "eth_maxPriorityFeePerGas":
            return hex(self.priority_fee)
        if method == "eth_gasPrice":
            return hex(self.gas_price)
        if method == "eth_call":
            call = params[0]
            assert call["to"].lower() == BASE_GAS_PRICE_ORACLE.lower()
            return hex(self.l1_upper_bound)
        raise AssertionError(f"Metodo inesperado: {method} {params}")


def test_builds_eip1559_native_sweep_plan_without_signing() -> None:
    rpc = NativeRpc(chain_id=1)

    plan = build_native_plan(
        rpc,
        chain=get_chain("ethereum"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
    )

    assert plan.fee_mode == "eip1559"
    assert plan.estimated_gas == 21_000
    assert plan.gas_limit == 25_200
    assert plan.max_priority_fee_per_gas == 2
    assert plan.max_fee_per_gas == 202
    assert plan.execution_fee_reserve == 25_200 * 202
    assert plan.send_value == plan.balance - plan.total_fee_reserve
    assert plan.unsigned_transaction["type"] == 2
    assert plan.unsigned_transaction["value"] == plan.send_value
    assert len([method for method, _ in rpc.calls if method == "eth_estimateGas"]) == 2


def test_builds_legacy_plan_when_latest_block_has_no_base_fee() -> None:
    rpc = NativeRpc(chain_id=56, base_fee=None, gas_price=100)

    plan = build_native_plan(
        rpc,
        chain=get_chain("bnb"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
    )

    assert plan.fee_mode == "legacy"
    assert plan.gas_price == 125
    assert "type" not in plan.unsigned_transaction
    assert plan.unsigned_transaction["gasPrice"] == 125


def test_stable_uses_zero_priority_tip_as_documented() -> None:
    rpc = NativeRpc(chain_id=988, priority_fee=999)

    plan = build_native_plan(
        rpc,
        chain=get_chain("stable"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
    )

    assert plan.max_priority_fee_per_gas == 0
    assert plan.max_fee_per_gas == 200
    assert "eth_maxPriorityFeePerGas" not in [method for method, _ in rpc.calls]


@pytest.mark.parametrize("chain_key", ["arbitrum", "robinhood"])
def test_nitro_chains_get_extra_gas_headroom(chain_key: str) -> None:
    chain = get_chain(chain_key)
    rpc = NativeRpc(chain_id=chain.chain_id)

    plan = build_native_plan(
        rpc,
        chain=chain,
        source_wallet=SOURCE,
        safe_wallet=SAFE,
    )

    assert plan.estimated_gas == 21_000
    assert plan.gas_limit == 28_350


def test_base_reserves_l1_upper_bound_with_buffer_and_accepts_eip7702() -> None:
    delegation = "0xef0100" + "44" * 20
    rpc = NativeRpc(
        chain_id=8453,
        l1_upper_bound=1_000,
        source_code=delegation,
    )

    plan = build_native_plan(
        rpc,
        chain=get_chain("base"),
        source_wallet=SOURCE,
        safe_wallet=SAFE,
    )

    assert plan.source_is_eip7702
    assert plan.l1_fee_reserve == 1_250
    assert plan.total_fee_reserve == plan.execution_fee_reserve + 1_250


def test_regular_contract_source_is_rejected() -> None:
    rpc = NativeRpc(chain_id=8453, source_code="0x60006000")

    with pytest.raises(NativePlanError, match="contrato"):
        build_native_plan(
            rpc,
            chain=get_chain("base"),
            source_wallet=SOURCE,
            safe_wallet=SAFE,
        )


def test_insufficient_balance_is_rejected() -> None:
    rpc = NativeRpc(chain_id=1, balance=1)

    with pytest.raises(NativePlanError, match="[Ss]aldo"):
        build_native_plan(
            rpc,
            chain=get_chain("ethereum"),
            source_wallet=SOURCE,
            safe_wallet=SAFE,
        )
