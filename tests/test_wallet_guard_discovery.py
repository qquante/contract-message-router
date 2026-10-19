import json

import pytest

from wallet_guard.discovery import TokenDiscoveryError, load_token_discovery

SOURCE = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
TOKEN = "0x3333333333333333333333333333333333333333"


def test_loads_dynamic_tokens_from_detector_and_deduplicates(tmp_path) -> None:
    path = tmp_path / "discovery.json"
    path.write_text(
        json.dumps(
            {
                "source_wallet": SOURCE,
                "chains": {"ethereum": [TOKEN, TOKEN], "bnb": []},
            }
        ),
        encoding="utf-8",
    )

    discovery = load_token_discovery(path, expected_source_wallet=SOURCE)

    assert discovery.tokens_for("ethereum") == (TOKEN,)
    assert discovery.tokens_for("bnb") == ()
    assert discovery.tokens_for("base") == ()


def test_rejects_discovery_for_another_wallet(tmp_path) -> None:
    path = tmp_path / "discovery.json"
    path.write_text(
        json.dumps({"source_wallet": OTHER, "chains": {"ethereum": [TOKEN]}}),
        encoding="utf-8",
    )

    with pytest.raises(TokenDiscoveryError, match="outra carteira"):
        load_token_discovery(path, expected_source_wallet=SOURCE)


def test_rejects_unapproved_chain_from_detector(tmp_path) -> None:
    path = tmp_path / "discovery.json"
    path.write_text(
        json.dumps({"source_wallet": SOURCE, "chains": {"unichain": [TOKEN]}}),
        encoding="utf-8",
    )

    with pytest.raises(TokenDiscoveryError, match="nao permitida"):
        load_token_discovery(path, expected_source_wallet=SOURCE)
