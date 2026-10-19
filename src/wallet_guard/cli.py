from __future__ import annotations

import argparse
import os
import sys
from functools import partial
from pathlib import Path

from wallet_guard.config import (
    ChainSettings,
    GuardConfigurationError,
    GuardSettings,
    load_guard_settings,
)
from wallet_guard.execution import (
    MAINNET_CONFIRMATION,
    InteractiveTerminal,
    exclusive_execution_lock,
    execute_chain_native,
    run_parallel_execution,
)
from wallet_guard.native import NativePlanError, build_native_plan
from wallet_guard.parallel import ParallelResult, run_parallel
from wallet_guard.preflight import PreflightError, run_chain_preflight
from wallet_guard.retry import (
    RetryAction,
    RetryPolicy,
    classify_rpc_failure,
    run_with_retry,
)
from wallet_guard.rpc import HttpJsonRpcClient, JsonRpcError
from wallet_guard.signer import (
    SigningError,
    check_private_key_matches,
    run_non_broadcastable_signature_test,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepara transferencias EVM nativas; o modo real exige confirmacao "
            "e travas explicitas."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-config",
        action="store_true",
        help="valida enderecos, redes, RPCs, proxies e travas de seguranca",
    )
    mode.add_argument(
        "--check-private-key",
        action="store_true",
        help="confere offline se a chave privada pertence a carteira de origem",
    )
    mode.add_argument(
        "--test-mainnet-signatures",
        action="store_true",
        help="assina offline testes nao executaveis para os chainIds configurados",
    )
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="executa apenas eth_call/eth_estimateGas e leituras RPC",
    )
    mode.add_argument(
        "--prepare-native",
        action="store_true",
        help="constroi planos nativos completos sem assinar e sem broadcast",
    )
    mode.add_argument(
        "--execute-native",
        action="store_true",
        help="assina e transmite saldos nativos nas 8 redes em paralelo",
    )
    mode.add_argument(
        "--retry-self-test",
        action="store_true",
        help="demonstra localmente a politica de dez tentativas",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="arquivo de configuracao local; o padrao e .env",
    )
    parser.add_argument(
        "--native-only",
        action="store_true",
        help="compatibilidade: o Wallet Guard atual sempre processa apenas nativos",
    )
    parser.add_argument(
        "--confirm-mainnet",
        metavar="FRASE",
        help="confirmacao literal exigida exclusivamente por --execute-native",
    )
    return parser


def _run_retry_self_test() -> None:
    policy = RetryPolicy()
    scripted = (
        "timeout",
        "HTTP 429 too many requests",
        "HTTP 503",
        "connection reset",
        "already known",
        "timeout",
        "replacement transaction underpriced",
        "timeout",
        "nonce too low",
        "already known",
    )
    print("Retry self-test: assinatura=NAO broadcast=NAO")
    for attempt, (delay, message) in enumerate(
        zip(policy.delays_seconds, scripted, strict=True), start=1
    ):
        action = classify_rpc_failure(message)
        print(f"  tentativa={attempt}/10 espera={delay}s acao={action.value}")


def _run_chain(
    item: ChainSettings,
    *,
    settings: GuardSettings,
) -> ParallelResult:
    attempts = 0

    def attempt_preflight():
        nonlocal attempts
        attempts += 1
        with HttpJsonRpcClient(
            rpc_url=item.rpc_url,
            proxy_url=settings.proxy_url,
            timeout_seconds=settings.rpc_timeout_seconds,
        ) as rpc:
            return run_chain_preflight(
                rpc,
                chain=item.chain,
                source_wallet=settings.source_wallet,
                safe_wallet=settings.safe_wallet,
                token_addresses=(),
            )

    def is_transient(exc: Exception) -> bool:
        return isinstance(exc, JsonRpcError) and classify_rpc_failure(
            str(exc)
        ) is RetryAction.REBROADCAST

    try:
        outcome = run_with_retry(
            attempt_preflight,
            should_retry=is_transient,
            policy=RetryPolicy(max_attempts=settings.retry_attempts),
        )
        report_lines = report_lines_with_attempts(
            outcome.value.safe_lines(), outcome.attempts
        )
        return ParallelResult(item.chain.key, report_lines, outcome.value.passed)
    except (JsonRpcError, PreflightError) as exc:
        return ParallelResult(
            item.chain.key,
            (
                f"[{item.chain.name}] FAIL RPC/proxy: {exc}",
                f"  tentativas_rpc={attempts}/{settings.retry_attempts}",
                "  assinatura=NAO broadcast=NAO",
            ),
            False,
        )


def report_lines_with_attempts(
    lines: tuple[str, ...], attempts: int
) -> tuple[str, ...]:
    if not lines:
        return (f"tentativas_rpc={attempts}/10",)
    return (*lines[:-1], f"  tentativas_rpc={attempts}/10", lines[-1])


def _prepare_native_chain(
    item: ChainSettings, *, settings: GuardSettings
) -> ParallelResult:
    attempts = 0

    def attempt_plan():
        nonlocal attempts
        attempts += 1
        with HttpJsonRpcClient(
            rpc_url=item.rpc_url,
            proxy_url=settings.proxy_url,
            timeout_seconds=settings.rpc_timeout_seconds,
        ) as rpc:
            return build_native_plan(
                rpc,
                chain=item.chain,
                source_wallet=settings.source_wallet,
                safe_wallet=settings.safe_wallet,
            )

    def is_transient(exc: Exception) -> bool:
        return isinstance(exc, JsonRpcError) and classify_rpc_failure(
            str(exc)
        ) is RetryAction.REBROADCAST

    try:
        outcome = run_with_retry(
            attempt_plan,
            should_retry=is_transient,
            policy=RetryPolicy(max_attempts=settings.retry_attempts),
        )
        return ParallelResult(
            item.chain.key,
            report_lines_with_attempts(
                outcome.value.safe_lines(), outcome.attempts
            ),
            True,
        )
    except (JsonRpcError, NativePlanError) as exc:
        return ParallelResult(
            item.chain.key,
            (
                f"[{item.chain.name}] NATIVE PLAN FAIL: {exc}",
                f"  tentativas_rpc={attempts}/{settings.retry_attempts}",
                "  assinatura=NAO broadcast=NAO",
            ),
            False,
        )


def main() -> None:
    args = _parser().parse_args()
    if args.retry_self_test:
        _run_retry_self_test()
        return

    if args.execute_native and args.confirm_mainnet != MAINNET_CONFIRMATION:
        raise SystemExit(
            "Execucao bloqueada: use --confirm-mainnet "
            f"{MAINNET_CONFIRMATION}."
        )
    if args.confirm_mainnet and not args.execute_native:
        raise SystemExit("--confirm-mainnet so pode ser usado com --execute-native.")

    try:
        settings = load_guard_settings(
            args.env_file,
            execution_mode=args.execute_native,
        )
    except GuardConfigurationError as exc:
        raise SystemExit(f"Configuracao wallet guard invalida: {exc}") from exc

    if args.check_config:
        print(f"Wallet guard configurado: {settings.safe_summary()}")
        print("Metodos de assinatura e broadcast: BLOQUEADOS")
        return

    if args.check_private_key:
        try:
            result = check_private_key_matches(
                os.getenv("WALLET_GUARD_PRIVATE_KEY", ""),
                expected_source_wallet=settings.source_wallet,
            )
        except SigningError as exc:
            raise SystemExit(f"Check offline da chave falhou: {exc}") from exc
        for line in result.safe_lines():
            print(line)
        return

    if args.test_mainnet_signatures:
        try:
            report = run_non_broadcastable_signature_test(
                os.getenv("WALLET_GUARD_PRIVATE_KEY", ""),
                expected_source_wallet=settings.source_wallet,
                chains=tuple(item.chain for item in settings.chains),
            )
        except SigningError as exc:
            raise SystemExit(f"Teste offline de assinatura falhou: {exc}") from exc
        for line in report.safe_lines():
            print(line)
        return

    if args.execute_native:
        private_key = os.getenv("WALLET_GUARD_PRIVATE_KEY", "")
        try:
            check_private_key_matches(
                private_key,
                expected_source_wallet=settings.source_wallet,
            )
        except SigningError as exc:
            raise SystemExit(f"Execucao bloqueada pela chave: {exc}") from exc

        terminal = InteractiveTerminal(sys.stdout)
        print(
            "WALLET GUARD MAINNET — 8 REDES EM PARALELO",
            flush=True,
        )
        try:
            with exclusive_execution_lock(Path(__file__).resolve().parents[2]):
                reports = run_parallel_execution(
                    settings.chains,
                    worker=partial(
                        execute_chain_native,
                        settings=settings,
                        private_key=private_key,
                        emit=terminal.event,
                    ),
                )
        except RuntimeError as exc:
            raise SystemExit(f"Execucao bloqueada: {exc}") from exc
        terminal.final(reports)
        if not all(report.success for report in reports):
            raise SystemExit(2)
        return

    if args.prepare_native:
        results = run_parallel(
            settings.chains,
            partial(_prepare_native_chain, settings=settings),
        )
        for result in results:
            for line in result.lines:
                print(line)
        if not all(result.passed for result in results):
            raise SystemExit(2)
        return

    results = run_parallel(
        settings.chains,
        partial(_run_chain, settings=settings),
    )
    for result in results:
        for line in result.lines:
            print(line)

    if not all(result.passed for result in results):
        raise SystemExit(2)
