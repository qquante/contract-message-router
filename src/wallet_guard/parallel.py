from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ParallelResult:
    key: str
    lines: tuple[str, ...]
    passed: bool


def run_parallel(
    items: Sequence[T], worker: Callable[[T], ParallelResult]
) -> tuple[ParallelResult, ...]:
    """Start every chain concurrently and return output in configured order."""
    if not items:
        return ()
    with ThreadPoolExecutor(
        max_workers=len(items), thread_name_prefix="wallet-guard-chain"
    ) as executor:
        futures = tuple(executor.submit(worker, item) for item in items)
        return tuple(future.result() for future in futures)
