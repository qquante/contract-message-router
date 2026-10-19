from __future__ import annotations

import json
from pathlib import Path

import pytest
from eth_account import Account

from wallet_guard.chains import get_chain
from wallet_guard.native import NativeTransactionPlan
from wallet_guard.signer import (
    SigningError,
    check_private_key_matches,
    run_non_broadcastable_signature_test,
    sign_native_plan_from_keystore,
)


SAFE = "0x2222222222222222222222222222222222222222"
PASSWORD = "senha-descartavel-de-teste"


def test_private_key_check_derives_expected_address_offline() -> None:
    account = Account.create("wallet-guard-disposable-key-check")

    result = check_private_key_matches(
        account.key.hex(),
        expected_source_wallet=account.address,
    )

    assert result.derived_wallet == account.address.lower()
    assert result.safe_lines()[-1] == "  rpc=NAO assinatura=NAO broadcast=NAO"


def test_private_key_check_rejects_different_wallet() -> None:
    account = Account.create("wallet-guard-disposable-key-mismatch")
    other = Account.create("wallet-guard-disposable-other-wallet")

    with pytest.raises(SigningError, match="nao pertence"):
        check_private_key_matches(
            account.key.hex(),
            expected_source_wallet=other.address,
        )


def test_private_key_check_rejects_invalid_key_without_echoing_it() -> None:
    invalid = "segredo-que-nao-deve-apare"

    with pytest.raises(SigningError) as error:
        check_private_key_matches(
            invalid,
            expected_source_wallet=SAFE,
        )

    assert invalid not in str(error.value)


def test_non_broadcastable_signature_test_uses_real_chain_ids_offline() -> None:
    account = Account.create("wallet-guard-disposable-mainnet-signatures")
    chains = (get_chain("ethereum"), get_chain("base"), get_chain("avalanche"))

    report = run_non_broadcastable_signature_test(
        account.key.hex(),
        expected_source_wallet=account.address,
        chains=chains,
    )

    assert report.chain_names_and_ids == tuple(
        (chain.name, chain.chain_id) for chain in chains
    )
    assert not hasattr(report, "raw_transaction")
    assert report.safe_lines()[-1] == (
        "  rpc=NAO raw_exibida=NAO arquivo=NAO broadcast=NAO"
    )


def _plan(source: str) -> NativeTransactionPlan:
    chain = get_chain("ethereum")
    transaction = {
        "chainId": chain.chain_id,
        "nonce": 7,
        "to": SAFE,
        "value": 10**15,
        "data": "0x",
        "gas": 25_200,
        "type": 2,
        "maxFeePerGas": 202,
        "maxPriorityFeePerGas": 2,
        "accessList": [],
    }
    return NativeTransactionPlan(
        chain=chain,
        source_wallet=source,
        safe_wallet=SAFE,
        balance=10**18,
        nonce=7,
        estimated_gas=21_000,
        gas_limit=25_200,
        fee_mode="eip1559",
        gas_price=None,
        max_fee_per_gas=202,
        max_priority_fee_per_gas=2,
        execution_fee_reserve=25_200 * 202,
        l1_fee_reserve=0,
        total_fee_reserve=25_200 * 202,
        send_value=10**15,
        source_is_eip7702=False,
        unsigned_transaction=transaction,
    )


def _write_keystore(path: Path, account) -> None:
    payload = Account.encrypt(
        account.key,
        PASSWORD,
        kdf="pbkdf2",
        iterations=1_000,
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_signs_offline_and_recovers_expected_source(tmp_path: Path) -> None:
    account = Account.create("wallet-guard-disposable-test")
    keystore_path = tmp_path / "keystore.json"
    _write_keystore(keystore_path, account)

    signed = sign_native_plan_from_keystore(
        _plan(account.address),
        keystore_path=keystore_path,
        password=PASSWORD,
    )

    assert signed.source_wallet.lower() == account.address.lower()
    assert Account.recover_transaction(signed.raw_transaction) == account.address
    assert signed.transaction_hash.startswith("0x")
    assert len(signed.transaction_hash) == 66


def test_rejects_keystore_from_different_source(tmp_path: Path) -> None:
    account = Account.create("wallet-guard-disposable-wrong-source")
    expected = Account.create("wallet-guard-disposable-expected")
    keystore_path = tmp_path / "keystore.json"
    _write_keystore(keystore_path, account)

    with pytest.raises(SigningError, match="nao pertence"):
        sign_native_plan_from_keystore(
            _plan(expected.address),
            keystore_path=keystore_path,
            password=PASSWORD,
        )


def test_rejects_wrong_password_without_exposing_it(tmp_path: Path) -> None:
    account = Account.create("wallet-guard-disposable-password")
    keystore_path = tmp_path / "keystore.json"
    _write_keystore(keystore_path, account)

    with pytest.raises(SigningError, match="descriptografar") as error:
        sign_native_plan_from_keystore(
            _plan(account.address),
            keystore_path=keystore_path,
            password="senha-incorreta",
        )

    assert "senha-incorreta" not in str(error.value)


def test_rejects_tampered_destination_before_decrypting(tmp_path: Path) -> None:
    account = Account.create("wallet-guard-disposable-tamper")
    plan = _plan(account.address)
    plan.unsigned_transaction["to"] = (
        "0x3333333333333333333333333333333333333333"
    )

    with pytest.raises(SigningError, match="campo to"):
        sign_native_plan_from_keystore(
            plan,
            keystore_path=tmp_path / "nao-precisa-existir.json",
            password=PASSWORD,
        )
