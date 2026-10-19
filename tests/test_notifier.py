from token_forwarder.notifier import play_beep_sequence


def test_plays_eight_888_hz_beeps_of_eight_seconds() -> None:
    beep_calls: list[tuple[int, int]] = []
    sleep_calls: list[float] = []

    play_beep_sequence(
        frequency_hz=888,
        duration_ms=8_000,
        repeat=8,
        gap_ms=250,
        beep=lambda frequency, duration: beep_calls.append((frequency, duration)),
        sleep=sleep_calls.append,
    )

    assert beep_calls == [(888, 8_000)] * 8
    assert sleep_calls == [0.25] * 7

