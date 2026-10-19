from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterator, TextIO

from wallet_guard.broadcast import BroadcastError, broadcast_signed_transaction
from wallet_guard.config import ChainSettings, GuardSettings
from wallet_guard.native import NativePlanError, build_native_plan
from wallet_guard.retry import RetryAction, RetryPolicy, classify_rpc_failure, run_with_retry
from wallet_guard.rpc import HttpBroadcastRpcClient, HttpJsonRpcClient, JsonRpcError
from wallet_guard.signer import SigningError, sign_native_plan_from_private_key


MAINNET_CONFIRMATION = "SEND_NATIVE_BALANCES"


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    chain_key: str
    chain_name: str
    phase: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ChainExecutionReport:
    chain_key: str
    chain_name: str
    native_symbol: str
    explorer_url: str
    success: bool
    final_phase: str
    transaction_hash: str | None = None
    balance_before: int | None = None
    amount_sent: int | None = None
    balance_after: int | None = None
    block_number: int | None = None
    attempts: int = 0
    error: str | None = None
    balance_error: str | None = None


def format_native_amount(value: int | None, symbol: str) -> str:
    if value is None:
        return "indisponivel"
    rendered = format(Decimal(value) / Decimal(10**18), "f").rstrip("0").rstrip(".")
    return f"{rendered or '0'} {symbol}"


class InteractiveTerminal:
    """Serialize live events emitted concurrently so terminal lines never mix."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def event(self, event: ExecutionEvent) -> None:
        detail = f" | {event.detail}" if event.detail else ""
        with self._lock:
            print(
                f"[{event.chain_name}] {event.phase}{detail}",
                file=self._stream,
                flush=True,
            )

    def final(self, reports: Sequence[ChainExecutionReport]) -> None:
        with self._lock:
            print("\n================ RESULTADO FINAL ================", file=self._stream)
            for report in reports:
                print("", file=self._stream)
                if report.success:
                    print(
                        f"[{report.chain_name}] TRANSACAO CONCLUIDA",
                        file=self._stream,
                    )
                    print(f"TX: {report.transaction_hash}", file=self._stream)
                    print(
                        "SALDO ANTES: "
                        f"{format_native_amount(report.balance_before, report.native_symbol)}",
                        file=self._stream,
                    )
                    print(
                        "VALOR TX: "
                        f"{format_native_amount(report.amount_sent, report.native_symbol)}",
                        file=self._stream,
                    )
                    print(
                        "SALDO RESTANTE: "
                        f"{format_native_amount(report.balance_after, report.native_symbol)}",
                        file=self._stream,
                    )
                    print(f"BLOCO: {report.block_number}", file=self._stream)
                    print(f"TENTATIVAS: {report.attempts}/10", file=self._stream)
                    print(
                        f"EXPLORER: {report.explorer_url}/tx/{report.transaction_hash}",
                        file=self._stream,
                    )
                    if report.balance_error:
                        print(
                            f"AVISO SALDO FINAL: {report.balance_error}",
                            file=self._stream,
                        )
                else:
                    print(
                        f"[{report.chain_name}] TRANSACAO NAO CONFIRMADA",
                        file=self._stream,
                    )
                    print(f"ETAPA: {report.final_phase}", file=self._stream)
                    print(f"TX: {report.transaction_hash or 'NAO GERADA'}", file=self._stream)
                    print(
                        "SALDO ANTES: "
                        f"{format_native_amount(report.balance_before, report.native_symbol)}",
                        file=self._stream,
                    )
                    print(f"TENTATIVAS: {report.attempts}/10", file=self._stream)
                    print(f"ERRO: {report.error or 'erro nao informado'}", file=self._stream)
                    print("SALDO MOVIMENTADO: NAO CONFIRMADO", file=self._stream)
            completed = sum(report.success for report in reports)
            print("", file=self._stream)
            print(
                f"RESUMO: CONCLUIDAS={completed}/{len(reports)} "
                f"NAO_CONFIRMADAS={len(reports) - completed}/{len(reports)}",
                file=self._stream,
                flush=True,
            )


def _quantity(value: object, label: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise JsonRpcError(None, f"{label} retornou quantidade invalida.")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise JsonRpcError(None, f"{label} retornou quantidade invalida.") from exc


def _transient(exc: Exception) -> bool:
    return isinstance(exc, JsonRpcError) and classify_rpc_failure(
        str(exc)
    ) is RetryAction.REBROADCAST


def execute_chain_native(
    item: ChainSettings,
    *,
    settings: GuardSettings,
    private_key: str,
    emit: Callable[[ExecutionEvent], None],
) -> ChainExecutionReport:
    chain = item.chain
    phase = "PREPARANDO"
    plan_attempts = 0
    broadcast_attempts = 0
    transaction_hash: str | None = None
    balance_before: int | None = None
    amount_sent: int | None = None

    try:
        def prepare_once():
            nonlocal plan_attempts
            plan_attempts += 1
            emit(
                ExecutionEvent(
                    chain.key,
                    chain.name,
                    "PREPARANDO",
                    f"tentativa={plan_attempts}/10",
                )
            )
            with HttpJsonRpcClient(
                rpc_url=item.rpc_url,
                proxy_url=settings.proxy_url,
                timeout_seconds=settings.rpc_timeout_seconds,
            ) as rpc:
                return build_native_plan(
                    rpc,
                    chain=chain,
                    source_wallet=settings.source_wallet,
                    safe_wallet=settings.safe_wallet,
                )

        plan_outcome = run_with_retry(
            prepare_once,
            should_retry=_transient,
            policy=RetryPolicy(max_attempts=settings.retry_attempts),
        )
        plan = plan_outcome.value
        balance_before = plan.balance
        amount_sent = plan.send_value
        emit(
            ExecutionEvent(
                chain.key,
                chain.name,
                "PLANO PRONTO",
                f"nonce={plan.nonce} valor={format_native_amount(plan.send_value, chain.native_symbol)}",
            )
        )

        phase = "ASSINANDO"
        emit(ExecutionEvent(chain.key, chain.name, phase, "somente memoria local"))
        signed = sign_native_plan_from_private_key(plan, private_key=private_key)
        transaction_hash = signed.transaction_hash
        emit(
            ExecutionEvent(
                chain.key,
                chain.name,
                "ASSINADA",
                f"tx={transaction_hash}",
            )
        )

        phase = "BROADCAST"

        def broadcast_progress(attempt: int, state: str) -> None:
            nonlocal broadcast_attempts
            broadcast_attempts = attempt
            label = state.replace("_", " ").upper()
            emit(
                ExecutionEvent(
                    chain.key,
                    chain.name,
                    label,
                    f"tentativa={attempt}/10 tx={transaction_hash}",
                )
            )

        with HttpBroadcastRpcClient(
            rpc_url=item.rpc_url,
            proxy_url=settings.proxy_url,
            timeout_seconds=settings.rpc_timeout_seconds,
        ) as rpc:
            broadcast = broadcast_signed_transaction(
                rpc,
                signed,
                policy=RetryPolicy(max_attempts=settings.retry_attempts),
                on_progress=broadcast_progress,
            )
        del signed

        emit(
            ExecutionEvent(
                chain.key,
                chain.name,
                "RECEIPT CONFIRMADO",
                f"bloco={broadcast.block_number} tx={transaction_hash}",
            )
        )

        balance_after: int | None = None
        balance_error: str | None = None
        phase = "LENDO SALDO FINAL"
        emit(ExecutionEvent(chain.key, chain.name, phase))
        try:
            def read_balance_once() -> int:
                with HttpJsonRpcClient(
                    rpc_url=item.rpc_url,
                    proxy_url=settings.proxy_url,
                    timeout_seconds=settings.rpc_timeout_seconds,
                ) as rpc:
                    return _quantity(
                        rpc.call(
                            "eth_getBalance",
                            (settings.source_wallet, "latest"),
                        ),
                        "eth_getBalance final",
                    )

            balance_after = run_with_retry(
                read_balance_once,
                should_retry=_transient,
                policy=RetryPolicy(max_attempts=settings.retry_attempts),
            ).value
        except JsonRpcError as exc:
            balance_error = str(exc)

        emit(
            ExecutionEvent(
                chain.key,
                chain.name,
                "TRANSACAO CONCLUIDA",
                f"tx={transaction_hash}",
            )
        )
        return ChainExecutionReport(
            chain_key=chain.key,
            chain_name=chain.name,
            native_symbol=chain.native_symbol,
            explorer_url=chain.explorer_url,
            success=True,
            final_phase="CONCLUIDA",
            transaction_hash=transaction_hash,
            balance_before=balance_before,
            amount_sent=amount_sent,
            balance_after=balance_after,
            block_number=broadcast.block_number,
            attempts=broadcast.attempts,
            balance_error=balance_error,
        )
    except (JsonRpcError, NativePlanError, SigningError, BroadcastError) as exc:
        emit(ExecutionEvent(chain.key, chain.name, "NAO CONFIRMADA", str(exc)))
        return ChainExecutionReport(
            chain_key=chain.key,
            chain_name=chain.name,
            native_symbol=chain.native_symbol,
            explorer_url=chain.explorer_url,
            success=False,
            final_phase=phase,
            transaction_hash=transaction_hash,
            balance_before=balance_before,
            amount_sent=amount_sent,
            attempts=(
                plan_attempts if phase == "PREPARANDO" else broadcast_attempts
            ),
            error=str(exc),
        )
    except Exception as exc:
        safe_error = f"Erro interno controlado: {type(exc).__name__}."
        emit(ExecutionEvent(chain.key, chain.name, "NAO CONFIRMADA", safe_error))
        return ChainExecutionReport(
            chain_key=chain.key,
            chain_name=chain.name,
            native_symbol=chain.native_symbol,
            explorer_url=chain.explorer_url,
            success=False,
            final_phase=phase,
            transaction_hash=transaction_hash,
            balance_before=balance_before,
            amount_sent=amount_sent,
            error=safe_error,
        )


def run_parallel_execution(
    items: Sequence[ChainSettings],
    *,
    worker: Callable[[ChainSettings], ChainExecutionReport],
) -> tuple[ChainExecutionReport, ...]:
    if not items:
        return ()
    with ThreadPoolExecutor(
        max_workers=len(items),
        thread_name_prefix="wallet-guard-execute",
    ) as executor:
        futures = tuple(executor.submit(worker, item) for item in items)
        return tuple(future.result() for future in futures)


@contextmanager
def exclusive_execution_lock(project_root: Path) -> Iterator[None]:
    """Prevent two wallet-guard execution processes from racing the same nonces."""
    data_dir = project_root / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / "wallet_guard_execute.lock"
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "Ja existe outra execucao Wallet Guard ativa."
            ) from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
