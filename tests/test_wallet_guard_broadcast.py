from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from wallet_guard.broadcast import BroadcastError, broadcast_signed_transaction
from wallet_guard.rpc import JsonRpcError
from wallet_guard.signer import SignedNativeTransaction


TX_HASH = "0x" + "12" * 32


def _signed() -> SignedNativeTransaction:
    return SignedNativeTransaction(
        chain_key="ethereum",
        source_wallet="0x1111111111111111111111111111111111111111",
        safe_wallet="0x2222222222222222222222222222222222222222",
        nonce=7,
        value=10**15,
        transaction_hash=TX_HASH,
        raw_transaction=b"\x02\x01\x02",
    )


def _receipt() -> dict[str, str]:
    return {
        "transactionHash": TX_HASH,
        "status": "0x1",
        "blockNumber": "0xabc",
    }


class ScriptedRpc:
    def __init__(self, sends: list[object], receipts: list[object]) -> None:
        self.sends = list(sends)
        self.receipts = list(receipts)
        self.raw_payloads: list[str] = []

    def call(self, method: str, params: Sequence[Any] = ()) -> Any:
        if method == "eth_sendRawTransaction":
            self.raw_payloads.append(params[0])
            outcome = self.sends.pop(0)
        elif method == "eth_getTransactionReceipt":
            outcome = self.receipts.pop(0)
        else:
            raise AssertionError(f"Metodo inesperado: {method}")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_rebroadcasts_same_raw_transaction_until_receipt() -> None:
    rpc = ScriptedRpc(
        sends=[
            JsonRpcError(None, "ConnectTimeout"),
            TX_HASH,
            JsonRpcError(-32000, "already known"),
        ],
        receipts=[None, None, _receipt()],
    )
    sleeps: list[float] = []

    result = broadcast_signed_transaction(rpc, _signed(), sleep=sleeps.append)

    assert result.attempts == 3
    assert result.block_number == 0xABC
    assert len(set(rpc.raw_payloads)) == 1
    assert sleeps == [1, 2]


def test_nonce_too_low_is_accepted_only_with_matching_success_receipt() -> None:
    rpc = ScriptedRpc(
        sends=[JsonRpcError(-32000, "nonce too low")],
        receipts=[_receipt()],
    )

    result = broadcast_signed_transaction(rpc, _signed(), sleep=lambda _: None)

    assert result.attempts == 1


def test_underpriced_requires_new_plan_and_signature() -> None:
    rpc = ScriptedRpc(
        sends=[JsonRpcError(-32000, "replacement transaction underpriced")],
        receipts=[],
    )

    with pytest.raises(BroadcastError, match="replanejar"):
        broadcast_signed_transaction(rpc, _signed(), sleep=lambda _: None)

    assert len(rpc.raw_payloads) == 1


def test_exhausts_exactly_ten_transient_attempts() -> None:
    rpc = ScriptedRpc(
        sends=[JsonRpcError(None, "timeout") for _ in range(10)],
        receipts=[None for _ in range(10)],
    )

    with pytest.raises(BroadcastError, match="10 tentativas"):
        broadcast_signed_transaction(rpc, _signed(), sleep=lambda _: None)

    assert len(rpc.raw_payloads) == 10


def test_rejects_failed_receipt() -> None:
    failed = _receipt()
    failed["status"] = "0x0"
    rpc = ScriptedRpc(sends=[TX_HASH], receipts=[failed])

    with pytest.raises(BroadcastError, match="status 0"):
        broadcast_signed_transaction(rpc, _signed(), sleep=lambda _: None)
