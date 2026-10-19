import pytest

from wallet_guard.retry import (
    RetryAction,
    RetryPolicy,
    classify_rpc_failure,
    run_with_retry,
)


def test_retry_policy_is_exactly_ten_attempts_and_bumps_fee() -> None:
    policy = RetryPolicy()
    assert policy.delays_seconds == (0, 1, 2, 4, 8, 15, 15, 15, 15, 15)
    assert len(policy.delays_seconds) == 10
    assert policy.bumped_fee(100) == 115

    with pytest.raises(ValueError, match="exatamente 10"):
        RetryPolicy(max_attempts=9)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("already known", RetryAction.ACCEPTED),
        ("nonce too low", RetryAction.REFRESH_STATE),
        ("replacement transaction underpriced", RetryAction.REPRICE),
        ("HTTP 429 too many requests", RetryAction.REBROADCAST),
        ("Falha de transporte RPC: ConnectTimeout", RetryAction.REBROADCAST),
        ("execution reverted", RetryAction.TERMINAL),
    ],
)
def test_classifies_retryable_and_terminal_failures(
    message: str, expected: RetryAction
) -> None:
    assert classify_rpc_failure(message) is expected


def test_live_retry_retries_transient_failure_until_success() -> None:
    attempts = 0
    waits: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary timeout")
        return "ok"

    outcome = run_with_retry(
        operation,
        should_retry=lambda exc: isinstance(exc, TimeoutError),
        sleep=waits.append,
    )

    assert outcome.value == "ok"
    assert outcome.attempts == 3
    assert waits == [1, 2]


def test_live_retry_does_not_repeat_terminal_failure() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("terminal")

    with pytest.raises(ValueError, match="terminal"):
        run_with_retry(operation, should_retry=lambda _: False, sleep=lambda _: None)

    assert attempts == 1
