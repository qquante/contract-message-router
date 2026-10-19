from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from wallet_guard.retry import RetryAction, RetryPolicy, classify_rpc_failure
from wallet_guard.rpc import JsonRpcError
from wallet_guard.signer import SignedNativeTransaction


class BroadcastError(RuntimeError):
    """Raised when a signed transaction is not safely confirmed."""


class BroadcastRpc(Protocol):
    def call(self, method: str, params: Sequence[Any] = ()) -> Any: ...


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    chain_key: str
    transaction_hash: str
    attempts: int
    block_number: int

    def safe_lines(self) -> tuple[str, ...]:
        return (
            f"[{self.chain_key}] BROADCAST CONFIRMED",
            f"  tx_hash={self.transaction_hash}",
            f"  tentativas={self.attempts}/10 bloco={self.block_number}",
        )


def _normalize_hash(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
        raise BroadcastError(f"{label} retornou hash de transacao invalido.")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise BroadcastError(f"{label} retornou hash de transacao invalido.") from exc
    return value.lower()


def _quantity(value: object, *, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise BroadcastError(f"{label} retornou quantidade invalida.")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise BroadcastError(f"{label} retornou quantidade invalida.") from exc


def _confirmed_receipt(
    receipt: object,
    *,
    expected_hash: str,
) -> int | None:
    if receipt is None:
        return None
    if not isinstance(receipt, dict):
        raise BroadcastError("RPC retornou receipt invalido.")
    receipt_hash = _normalize_hash(
        receipt.get("transactionHash"), label="eth_getTransactionReceipt"
    )
    if receipt_hash != expected_hash:
        raise BroadcastError("Receipt pertence a outra transacao.")
    status = _quantity(receipt.get("status"), label="receipt.status")
    if status != 1:
        raise BroadcastError("Transacao foi minerada com falha (status 0).")
    return _quantity(receipt.get("blockNumber"), label="receipt.blockNumber")


def broadcast_signed_transaction(
    rpc: BroadcastRpc,
    signed: SignedNativeTransaction,
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_progress: Callable[[int, str], None] | None = None,
) -> BroadcastResult:
    """Rebroadcast the exact same raw transaction and require a success receipt."""
    active_policy = policy or RetryPolicy()
    expected_hash = _normalize_hash(signed.transaction_hash, label="assinatura")
    raw_hex = f"0x{signed.raw_transaction.hex()}"

    for attempt, delay in enumerate(active_policy.delays_seconds, start=1):
        if delay:
            if on_progress:
                on_progress(attempt, f"aguardando_retry_{delay}s")
            sleep(delay)

        if on_progress:
            on_progress(attempt, "enviando")
        try:
            returned_hash = _normalize_hash(
                rpc.call("eth_sendRawTransaction", (raw_hex,)),
                label="eth_sendRawTransaction",
            )
            if returned_hash != expected_hash:
                raise BroadcastError("RPC devolveu hash diferente do assinado.")
        except JsonRpcError as exc:
            action = classify_rpc_failure(str(exc))
            if action is RetryAction.REPRICE:
                raise BroadcastError(
                    "Taxa recusada; e obrigatorio replanejar e assinar novamente."
                ) from exc
            if action not in {
                RetryAction.ACCEPTED,
                RetryAction.REBROADCAST,
                RetryAction.REFRESH_STATE,
            }:
                raise BroadcastError(f"Broadcast recusado: {exc}") from exc

        try:
            if on_progress:
                on_progress(attempt, "aguardando_receipt")
            receipt = rpc.call(
                "eth_getTransactionReceipt", (signed.transaction_hash,)
            )
            block_number = _confirmed_receipt(
                receipt,
                expected_hash=expected_hash,
            )
        except JsonRpcError as exc:
            if classify_rpc_failure(str(exc)) is not RetryAction.REBROADCAST:
                raise BroadcastError(f"Falha ao consultar receipt: {exc}") from exc
            block_number = None

        if block_number is not None:
            return BroadcastResult(
                chain_key=signed.chain_key,
                transaction_hash=signed.transaction_hash,
                attempts=attempt,
                block_number=block_number,
            )

    raise BroadcastError(
        "Transacao nao foi confirmada apos exatamente 10 tentativas."
    )
