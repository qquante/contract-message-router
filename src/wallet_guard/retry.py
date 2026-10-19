from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar


T = TypeVar("T")


class RetryAction(str, Enum):
    ACCEPTED = "accepted"
    REBROADCAST = "rebroadcast"
    REPRICE = "reprice"
    REFRESH_STATE = "refresh_state"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 10
    fee_bump_percent: int = 15

    def __post_init__(self) -> None:
        if self.max_attempts != 10:
            raise ValueError("A politica de protecao exige exatamente 10 tentativas.")
        if not 10 <= self.fee_bump_percent <= 100:
            raise ValueError("O aumento de taxa deve ficar entre 10% e 100%.")

    @property
    def delays_seconds(self) -> tuple[int, ...]:
        return (0, 1, 2, 4, 8, 15, 15, 15, 15, 15)

    def bumped_fee(self, current_fee: int) -> int:
        if current_fee < 0:
            raise ValueError("Taxa nao pode ser negativa.")
        numerator = current_fee * (100 + self.fee_bump_percent)
        return max(current_fee + 1, (numerator + 99) // 100)


@dataclass(frozen=True, slots=True)
class RetryOutcome(Generic[T]):
    value: T
    attempts: int


def run_with_retry(
    operation: Callable[[], T],
    *,
    should_retry: Callable[[Exception], bool],
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryOutcome[T]:
    active_policy = policy or RetryPolicy()
    for attempt, delay in enumerate(active_policy.delays_seconds, start=1):
        if delay:
            sleep(delay)
        try:
            return RetryOutcome(operation(), attempt)
        except Exception as exc:
            if attempt == active_policy.max_attempts or not should_retry(exc):
                raise
    raise AssertionError("Politica de retry terminou sem resultado.")


def classify_rpc_failure(message: str) -> RetryAction:
    normalized = message.strip().lower()
    if "already known" in normalized or "known transaction" in normalized:
        return RetryAction.ACCEPTED
    if "nonce too low" in normalized or "nonce gap" in normalized:
        return RetryAction.REFRESH_STATE
    if "underpriced" in normalized or "fee too low" in normalized:
        return RetryAction.REPRICE
    transient_markers = (
        "timeout",
        "timed out",
        "connection",
        "rate limit",
        "too many requests",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
    )
    if any(marker in normalized for marker in transient_markers):
        return RetryAction.REBROADCAST
    return RetryAction.TERMINAL
