from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import to_checksum_address

from wallet_guard.abi import mask_address, normalize_address
from wallet_guard.chains import Chain
from wallet_guard.native import NativeTransactionPlan


class SigningError(RuntimeError):
    """Raised when an encrypted keystore cannot safely sign a native plan."""


@dataclass(frozen=True, slots=True)
class PrivateKeyCheck:
    derived_wallet: str
    expected_wallet: str

    def safe_lines(self) -> tuple[str, ...]:
        return (
            "[OFFLINE PRIVATE KEY CHECK] PASS",
            (
                f"  derivado={mask_address(self.derived_wallet)} "
                f"origem={mask_address(self.expected_wallet)}"
            ),
            "  rpc=NAO assinatura=NAO broadcast=NAO",
        )


@dataclass(frozen=True, slots=True)
class OfflineSignatureTestReport:
    chain_names_and_ids: tuple[tuple[str, int], ...]
    source_wallet: str

    def safe_lines(self) -> tuple[str, ...]:
        lines: list[str] = []
        for chain_name, chain_id in self.chain_names_and_ids:
            lines.append(
                f"[{chain_name}] OFFLINE SIGNATURE TEST PASS chain_id={chain_id}"
            )
        lines.extend(
            (
                f"  origem={mask_address(self.source_wallet)}",
                "  teste_nao_executavel=SIM gas=0 value=0 destino=origem",
                "  rpc=NAO raw_exibida=NAO arquivo=NAO broadcast=NAO",
            )
        )
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class SignedNativeTransaction:
    chain_key: str
    source_wallet: str
    safe_wallet: str
    nonce: int
    value: int
    transaction_hash: str
    raw_transaction: bytes

    def safe_lines(self) -> tuple[str, ...]:
        return (
            f"[{self.chain_key}] OFFLINE SIGN PASS",
            (
                f"  origem={mask_address(self.source_wallet)} "
                f"destino={mask_address(self.safe_wallet)} nonce={self.nonce}"
            ),
            f"  tx_hash={self.transaction_hash}",
            "  broadcast=NAO",
        )


def _account_from_private_key(private_key: str) -> LocalAccount:
    candidate = private_key.strip()
    payload = candidate[2:] if candidate.lower().startswith("0x") else candidate
    if len(payload) != 64:
        raise SigningError("WALLET_GUARD_PRIVATE_KEY deve conter exatamente 32 bytes.")
    try:
        return Account.from_key(bytes.fromhex(payload))
    except (TypeError, ValueError) as exc:
        raise SigningError("WALLET_GUARD_PRIVATE_KEY possui formato invalido.") from exc


def check_private_key_matches(
    private_key: str,
    *,
    expected_source_wallet: str,
) -> PrivateKeyCheck:
    """Derive the public address locally without signing or contacting an RPC."""
    account = _account_from_private_key(private_key)

    expected = normalize_address(expected_source_wallet)
    derived = normalize_address(account.address)
    if derived != expected:
        raise SigningError(
            "A chave privada nao pertence a WALLET_GUARD_SOURCE_WALLET."
        )
    return PrivateKeyCheck(derived_wallet=derived, expected_wallet=expected)


def run_non_broadcastable_signature_test(
    private_key: str,
    *,
    expected_source_wallet: str,
    chains: tuple[Chain, ...],
) -> OfflineSignatureTestReport:
    """Sign invalid gas=0 self-transfers for real chain IDs, entirely offline."""
    check = check_private_key_matches(
        private_key,
        expected_source_wallet=expected_source_wallet,
    )
    account = _account_from_private_key(private_key)

    tested: list[tuple[str, int]] = []
    for chain in chains:
        transaction = {
            "chainId": chain.chain_id,
            "nonce": 0,
            "to": to_checksum_address(check.derived_wallet),
            "value": 0,
            "data": "0x",
            # Menor que o gas intrinseco: a rede deve rejeitar estes bytes.
            "gas": 0,
            "type": 2,
            "maxFeePerGas": 0,
            "maxPriorityFeePerGas": 0,
            "accessList": [],
        }
        try:
            signed = account.sign_transaction(transaction)
            recovered = Account.recover_transaction(signed.raw_transaction)
        except (TypeError, ValueError) as exc:
            raise SigningError(
                f"Falha ao testar assinatura offline para {chain.name}."
            ) from exc
        if normalize_address(recovered) != check.derived_wallet:
            raise SigningError(
                f"Assinatura offline nao recuperou a origem em {chain.name}."
            )
        tested.append((chain.name, chain.chain_id))
        del signed

    return OfflineSignatureTestReport(
        chain_names_and_ids=tuple(tested),
        source_wallet=check.derived_wallet,
    )


def _load_keystore(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SigningError("Arquivo de keystore nao encontrado.") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SigningError("Arquivo de keystore invalido ou ilegivel.") from exc
    if not isinstance(payload, dict) or payload.get("version") != 3:
        raise SigningError("Keystore deve ser JSON Web3 Secret Storage v3.")
    return payload


def _validated_transaction(plan: NativeTransactionPlan) -> dict[str, Any]:
    transaction = dict(plan.unsigned_transaction)
    expected: dict[str, Any] = {
        "chainId": plan.chain.chain_id,
        "nonce": plan.nonce,
        "to": plan.safe_wallet,
        "value": plan.send_value,
        "data": "0x",
        "gas": plan.gas_limit,
    }
    for field, expected_value in expected.items():
        actual_value = transaction.get(field)
        if field == "to" and isinstance(actual_value, str):
            actual_value = normalize_address(actual_value)
            expected_value = normalize_address(str(expected_value))
        if actual_value != expected_value:
            raise SigningError(f"Plano alterado ou inconsistente no campo {field}.")

    if plan.fee_mode == "eip1559":
        if (
            transaction.get("type") != 2
            or transaction.get("maxFeePerGas") != plan.max_fee_per_gas
            or transaction.get("maxPriorityFeePerGas")
            != plan.max_priority_fee_per_gas
            or "gasPrice" in transaction
        ):
            raise SigningError("Campos EIP-1559 do plano estao inconsistentes.")
    elif plan.fee_mode == "legacy":
        if (
            transaction.get("gasPrice") != plan.gas_price
            or "maxFeePerGas" in transaction
            or "maxPriorityFeePerGas" in transaction
        ):
            raise SigningError("Campos legacy do plano estao inconsistentes.")
    else:
        raise SigningError("Modo de taxa desconhecido no plano.")

    transaction["to"] = to_checksum_address(plan.safe_wallet)
    return transaction


def _sign_native_plan_with_account(
    plan: NativeTransactionPlan,
    *,
    account: LocalAccount,
) -> SignedNativeTransaction:
    transaction = _validated_transaction(plan)
    if normalize_address(account.address) != normalize_address(plan.source_wallet):
        raise SigningError("A chave nao pertence a carteira de origem configurada.")
    try:
        signed = account.sign_transaction(transaction)
        recovered = Account.recover_transaction(signed.raw_transaction)
    except (TypeError, ValueError) as exc:
        raise SigningError("Nao foi possivel assinar o plano nativo.") from exc
    if normalize_address(recovered) != normalize_address(plan.source_wallet):
        raise SigningError("Remetente recuperado da assinatura nao confere.")
    transaction_hash = signed.hash.hex()
    if not transaction_hash.startswith("0x"):
        transaction_hash = f"0x{transaction_hash}"
    return SignedNativeTransaction(
        chain_key=plan.chain.key,
        source_wallet=plan.source_wallet,
        safe_wallet=plan.safe_wallet,
        nonce=plan.nonce,
        value=plan.send_value,
        transaction_hash=transaction_hash,
        raw_transaction=bytes(signed.raw_transaction),
    )


def sign_native_plan_from_private_key(
    plan: NativeTransactionPlan,
    *,
    private_key: str,
) -> SignedNativeTransaction:
    """Sign a validated native plan locally from the configured private key."""
    return _sign_native_plan_with_account(
        plan,
        account=_account_from_private_key(private_key),
    )


def sign_native_plan_from_keystore(
    plan: NativeTransactionPlan,
    *,
    keystore_path: Path,
    password: str,
) -> SignedNativeTransaction:
    """Decrypt a v3 keystore, sign once offline and verify the recovered sender."""
    if not password:
        raise SigningError("Senha do keystore nao pode ser vazia.")

    keystore = _load_keystore(keystore_path)
    try:
        private_key = Account.decrypt(keystore, password)
    except (TypeError, ValueError) as exc:
        raise SigningError("Nao foi possivel descriptografar o keystore.") from exc

    try:
        account = Account.from_key(private_key)
        if normalize_address(account.address) != normalize_address(plan.source_wallet):
            raise SigningError(
                "O keystore nao pertence a carteira de origem configurada."
            )
        return _sign_native_plan_with_account(
            plan,
            account=account,
        )
    finally:
        # Python nao garante limpeza total de copias imutaveis em memoria, mas
        # reduzimos a vida util da referencia e nunca a registramos ou retornamos.
        private_key = b""
