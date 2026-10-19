from pathlib import Path

from token_forwarder.history import ForwardHistory


def test_records_and_finds_sent_message(tmp_path: Path) -> None:
    database = tmp_path / "state" / "forwarder.sqlite3"
    history = ForwardHistory(database)
    try:
        assert not history.was_sent(10, 20, "contract")
        history.record_sent(10, 20, "contract", "@destination")
        assert history.was_sent(10, 20, "contract")
    finally:
        history.close()

    reopened = ForwardHistory(database)
    try:
        assert reopened.was_sent(10, 20, "contract")
    finally:
        reopened.close()

