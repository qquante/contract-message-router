from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

try:
    import winsound
except ImportError:  # pragma: no cover - the application targets Windows
    winsound = None  # type: ignore[assignment]

LOGGER = logging.getLogger("token_forwarder.notifier")
_STOP = object()


def play_beep_sequence(
    *,
    frequency_hz: int,
    duration_ms: int,
    repeat: int,
    gap_ms: int,
    beep: Callable[[int, int], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Play a synchronous beep sequence; designed to run in a worker thread."""
    if beep is None:
        if winsound is None:
            raise RuntimeError("O alerta sonoro winsound esta disponivel somente no Windows.")
        beep = winsound.Beep

    for index in range(repeat):
        beep(frequency_hz, duration_ms)
        if gap_ms and index < repeat - 1:
            sleep(gap_ms / 1_000)


class BeepNotifier:
    """Serialize sound alerts on a daemon thread without blocking Telegram events."""

    def __init__(
        self,
        *,
        enabled: bool,
        frequency_hz: int,
        duration_ms: int,
        repeat: int,
        gap_ms: int,
    ) -> None:
        self._enabled = enabled
        self._frequency_hz = frequency_hz
        self._duration_ms = duration_ms
        self._repeat = repeat
        self._gap_ms = gap_ms
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="token-forwarder-beep",
            daemon=True,
        )
        self._thread.start()

    def notify(self) -> None:
        if self._enabled:
            self._queue.put_nowait(object())

    def close(self) -> None:
        if self._thread is None:
            return
        self._queue.put_nowait(_STOP)
        self._thread.join(timeout=1)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            try:
                play_beep_sequence(
                    frequency_hz=self._frequency_hz,
                    duration_ms=self._duration_ms,
                    repeat=self._repeat,
                    gap_ms=self._gap_ms,
                )
            except RuntimeError:
                LOGGER.exception("Nao foi possivel tocar o alerta sonoro.")

