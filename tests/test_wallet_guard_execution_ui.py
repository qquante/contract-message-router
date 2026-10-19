from __future__ import annotations

from io import StringIO
from threading import Barrier

from wallet_guard.chains import CHAINS, get_chain
from wallet_guard.config import ChainSettings
from wallet_guard.execution import (
    ChainExecutionReport,
    ExecutionEvent,
    InteractiveTerminal,
    run_parallel_execution,
)


def _report(chain_key: str, *, success: bool) -> ChainExecutionReport:
    chain = get_chain(chain_key)
    return ChainExecutionReport(
        chain_key=chain.key,
        chain_name=chain.name,
        native_symbol=chain.native_symbol,
        explorer_url=chain.explorer_url,
        success=success,
        final_phase="CONCLUIDA" if success else "BROADCAST",
        transaction_hash="0x" + "12" * 32 if success else None,
        balance_before=2 * 10**18,
        amount_sent=10**18,
        balance_after=10**18,
        block_number=123 if success else None,
        attempts=2 if success else 10,
        error=None if success else "timeout",
    )


def test_terminal_renders_live_and_final_success_failure_blocks() -> None:
    stream = StringIO()
    terminal = InteractiveTerminal(stream)
    terminal.event(
        ExecutionEvent(
            "ethereum",
            "Ethereum Mainnet",
            "ENVIANDO",
            "tentativa=2/10",
        )
    )
    terminal.final(
        (_report("ethereum", success=True), _report("base", success=False))
    )

    output = stream.getvalue()
    assert "[Ethereum Mainnet] ENVIANDO | tentativa=2/10" in output
    assert "[Ethereum Mainnet] TRANSACAO CONCLUIDA" in output
    assert "VALOR TX: 1 ETH" in output
    assert "SALDO RESTANTE: 1 ETH" in output
    assert "[Base Mainnet] TRANSACAO NAO CONFIRMADA" in output
    assert "RESUMO: CONCLUIDAS=1/2 NAO_CONFIRMADAS=1/2" in output


def test_execution_workers_start_in_parallel_and_results_keep_chain_order() -> None:
    items = tuple(
        ChainSettings(chain, f"https://{chain.key}.example")
        for chain in CHAINS
    )
    barrier = Barrier(len(items))

    def worker(item: ChainSettings) -> ChainExecutionReport:
        barrier.wait(timeout=1)
        return _report(item.chain.key, success=True)

    reports = run_parallel_execution(items, worker=worker)

    assert tuple(report.chain_key for report in reports) == tuple(
        item.chain.key for item in items
    )
