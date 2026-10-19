from threading import Barrier

from wallet_guard.parallel import ParallelResult, run_parallel


def test_all_chains_start_concurrently_and_results_keep_input_order() -> None:
    items = ("ethereum", "base", "bnb", "arbitrum")
    started_together = Barrier(len(items))

    def worker(item: str) -> ParallelResult:
        started_together.wait(timeout=1)
        return ParallelResult(item, (f"{item}=PASS",), True)

    results = run_parallel(items, worker)

    assert tuple(result.key for result in results) == items
    assert all(result.passed for result in results)
