from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wallet_guard.abi import is_eip7702_delegation_code, mask_address
from wallet_guard.chains import Chain
from wallet_guard.rpc import RpcClient


GAS_LIMIT_BUFFER_PERCENT = 20
NITRO_GAS_LIMIT_BUFFER_PERCENT = 35
LEGACY_FEE_BUFFER_PERCENT = 25
L1_FEE_BUFFER_PERCENT = 25
BASE_GAS_PRICE_ORACLE = "0x420000000000000000000000000000000000000f"
BASE_L1_UPPER_BOUND_SELECTOR = "f1c7a58b"
SIGNED_NATIVE_TX_SIZE_UPPER_BOUND = 200


class NativePlanError(RuntimeError):
    """Raised when a safe native sweep transaction cannot be prepared."""


@dataclass(frozen=True, slots=True)
class NativeTransactionPlan:
    chain: Chain
    source_wallet: str
    safe_wallet: str
    balance: int
    nonce: int
    estimated_gas: int
    gas_limit: int
    fee_mode: str
    gas_price: int | None
    max_fee_per_gas: int | None
    max_priority_fee_per_gas: int | None
    execution_fee_reserve: int
    l1_fee_reserve: int
    total_fee_reserve: int
    send_value: int
    source_is_eip7702: bool
    unsigned_transaction: dict[str, Any]

    def safe_lines(self) -> tuple[str, ...]:
        lines = [
            f"[{self.chain.name}] NATIVE PLAN PASS",
            (
                f"  origem={mask_address(self.source_wallet)} "
                f"destino={mask_address(self.safe_wallet)} nonce={self.nonce}"
            ),
            (
                f"  gas_estimado={self.estimated_gas} gas_limit={self.gas_limit} "
                f"fee_mode={self.fee_mode}"
            ),
            (
                f"  reserva_execucao_raw={self.execution_fee_reserve} "
                f"reserva_l1_raw={self.l1_fee_reserve} "
                f"enviavel_raw={self.send_value}"
            ),
        ]
        if self.source_is_eip7702:
            lines.append("  aviso: origem EIP-7702; transacao nativa padrao permitida")
        lines.append("  assinatura=NAO broadcast=NAO")
        return tuple(lines)


def _quantity(value: Any, method: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise NativePlanError(f"{method} retornou quantidade invalida.")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise NativePlanError(f"{method} retornou quantidade invalida.") from exc


def _buffer(value: int, percent: int) -> int:
    return (value * (100 + percent) + 99) // 100


def _has_code(code: Any) -> bool:
    return isinstance(code, str) and code not in {"0x", "0x0", "0x00"}


def _base_l1_fee_reserve(rpc: RpcClient) -> int:
    data = (
        f"0x{BASE_L1_UPPER_BOUND_SELECTOR}"
        f"{SIGNED_NATIVE_TX_SIZE_UPPER_BOUND:064x}"
    )
    upper_bound = _quantity(
        rpc.call(
            "eth_call",
            ({"to": BASE_GAS_PRICE_ORACLE, "data": data}, "latest"),
        ),
        "GasPriceOracle.getL1FeeUpperBound",
    )
    return _buffer(upper_bound, L1_FEE_BUFFER_PERCENT)


def build_native_plan(
    rpc: RpcClient,
    *,
    chain: Chain,
    source_wallet: str,
    safe_wallet: str,
) -> NativeTransactionPlan:
    actual_chain_id = _quantity(rpc.call("eth_chainId"), "eth_chainId")
    if actual_chain_id != chain.chain_id:
        raise NativePlanError(
            f"RPC da rede errada: esperado {chain.chain_id}, recebido {actual_chain_id}."
        )

    source_code = rpc.call("eth_getCode", (source_wallet, "latest"))
    source_is_eip7702 = is_eip7702_delegation_code(source_code)
    if _has_code(source_code) and not source_is_eip7702:
        raise NativePlanError("Origem possui codigo de contrato comum; envio recusado.")
    destination_code = rpc.call("eth_getCode", (safe_wallet, "latest"))
    if _has_code(destination_code):
        raise NativePlanError(
            "Destino possui codigo; fluxo exige uma carteira normal sem contrato."
        )

    balance = _quantity(
        rpc.call("eth_getBalance", (source_wallet, chain.state_block_tag)),
        "eth_getBalance",
    )
    nonce = _quantity(
        rpc.call(
            "eth_getTransactionCount", (source_wallet, chain.state_block_tag)
        ),
        "eth_getTransactionCount",
    )
    estimate_call: dict[str, str] = {
        "from": source_wallet,
        "to": safe_wallet,
        "value": "0x1",
        "data": "0x",
    }
    estimated_gas = _quantity(
        rpc.call("eth_estimateGas", (estimate_call,)), "eth_estimateGas"
    )
    gas_buffer_percent = (
        NITRO_GAS_LIMIT_BUFFER_PERCENT
        if chain.key in {"arbitrum", "robinhood"}
        else GAS_LIMIT_BUFFER_PERCENT
    )
    gas_limit = _buffer(estimated_gas, gas_buffer_percent)

    latest_block = rpc.call("eth_getBlockByNumber", ("latest", False))
    if not isinstance(latest_block, dict):
        raise NativePlanError("eth_getBlockByNumber retornou bloco invalido.")

    base_fee_raw = latest_block.get("baseFeePerGas")
    gas_price: int | None = None
    max_fee_per_gas: int | None = None
    max_priority_fee_per_gas: int | None = None
    if isinstance(base_fee_raw, str):
        base_fee = _quantity(base_fee_raw, "baseFeePerGas")
        # Stable documenta um modelo sem priority tip; definir tip desperdicaria
        # USDT0 sem acelerar a inclusao. Nas demais redes usamos a sugestao RPC.
        max_priority_fee_per_gas = (
            0
            if chain.key == "stable"
            else _quantity(
                rpc.call("eth_maxPriorityFeePerGas"),
                "eth_maxPriorityFeePerGas",
            )
        )
        max_fee_per_gas = base_fee * 2 + max_priority_fee_per_gas
        fee_mode = "eip1559"
        fee_per_gas_reserve = max_fee_per_gas
    else:
        gas_price = _buffer(
            _quantity(rpc.call("eth_gasPrice"), "eth_gasPrice"),
            LEGACY_FEE_BUFFER_PERCENT,
        )
        fee_mode = "legacy"
        fee_per_gas_reserve = gas_price

    execution_fee_reserve = gas_limit * fee_per_gas_reserve
    l1_fee_reserve = _base_l1_fee_reserve(rpc) if chain.key == "base" else 0
    total_fee_reserve = execution_fee_reserve + l1_fee_reserve
    send_value = balance - total_fee_reserve
    if send_value <= 0:
        raise NativePlanError(
            "Saldo nativo nao cobre a reserva conservadora de todas as taxas."
        )

    transaction: dict[str, Any] = {
        "chainId": chain.chain_id,
        "nonce": nonce,
        "to": safe_wallet,
        "value": send_value,
        "data": "0x",
        "gas": gas_limit,
    }
    if fee_mode == "eip1559":
        transaction.update(
            {
                "type": 2,
                "maxFeePerGas": max_fee_per_gas,
                "maxPriorityFeePerGas": max_priority_fee_per_gas,
                "accessList": [],
            }
        )
    else:
        transaction["gasPrice"] = gas_price

    final_call = {
        "from": source_wallet,
        "to": safe_wallet,
        "value": hex(send_value),
        "data": "0x",
    }
    if fee_mode == "eip1559":
        final_call.update(
            {
                "maxFeePerGas": hex(max_fee_per_gas or 0),
                "maxPriorityFeePerGas": hex(max_priority_fee_per_gas or 0),
            }
        )
    else:
        final_call["gasPrice"] = hex(gas_price or 0)
    final_estimate = _quantity(
        rpc.call("eth_estimateGas", (final_call,)), "eth_estimateGas final"
    )
    if final_estimate > gas_limit:
        raise NativePlanError(
            "Estimativa final excedeu o gas limit reservado; plano recusado."
        )

    return NativeTransactionPlan(
        chain=chain,
        source_wallet=source_wallet,
        safe_wallet=safe_wallet,
        balance=balance,
        nonce=nonce,
        estimated_gas=estimated_gas,
        gas_limit=gas_limit,
        fee_mode=fee_mode,
        gas_price=gas_price,
        max_fee_per_gas=max_fee_per_gas,
        max_priority_fee_per_gas=max_priority_fee_per_gas,
        execution_fee_reserve=execution_fee_reserve,
        l1_fee_reserve=l1_fee_reserve,
        total_fee_reserve=total_fee_reserve,
        send_value=send_value,
        source_is_eip7702=source_is_eip7702,
        unsigned_transaction=transaction,
    )
