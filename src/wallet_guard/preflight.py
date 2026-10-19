from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wallet_guard.abi import (
    AbiError,
    decode_uint256,
    encode_balance_of,
    encode_decimals,
    encode_transfer,
    format_units,
    is_eip7702_delegation_code,
    mask_address,
    transfer_result_succeeded,
)
from wallet_guard.chains import Chain
from wallet_guard.rpc import JsonRpcError, RpcClient


GAS_LIMIT_BUFFER_PERCENT = 20
FEE_BUFFER_PERCENT = 25


class PreflightError(RuntimeError):
    """Raised when a chain-wide read-only validation cannot continue."""


@dataclass(frozen=True, slots=True)
class TokenPreflight:
    token_address: str
    balance_raw: int | None
    decimals: int | None
    estimated_gas: int | None
    reserved_fee_native_raw: int
    status: str
    error: str | None = None

    @property
    def display_balance(self) -> str:
        if self.balance_raw is None:
            return "desconhecido"
        return format_units(self.balance_raw, self.decimals)


@dataclass(frozen=True, slots=True)
class NativePreflight:
    symbol: str
    balance_raw: int
    estimated_gas: int | None
    total_reserved_fee_raw: int
    sendable_raw: int
    status: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChainPreflight:
    chain: Chain
    source_wallet: str
    safe_wallet: str
    block_number: int
    state_nonce: int
    gas_price_raw: int
    source_has_code: bool
    source_is_eip7702: bool
    destination_has_code: bool
    tokens: tuple[TokenPreflight, ...]
    native: NativePreflight
    execution_order: tuple[str, ...]
    passed: bool

    def safe_lines(self) -> tuple[str, ...]:
        lines = [
            f"[{self.chain.name}] {'PASS' if self.passed else 'FAIL'}",
            (
                f"  origem={mask_address(self.source_wallet)} "
                f"destino={mask_address(self.safe_wallet)} "
                f"bloco={self.block_number} "
                f"nonce_{self.chain.state_block_tag}={self.state_nonce}"
            ),
            f"  gas_price_raw={self.gas_price_raw}",
        ]
        if self.source_has_code:
            if self.source_is_eip7702:
                lines.append(
                    "  aviso: origem e EOA delegada EIP-7702; "
                    "origem de transacao permitida"
                )
            else:
                lines.append(
                    "  ERRO: origem possui codigo de contrato; "
                    "fluxo EOA nao comprovado"
                )
        if self.destination_has_code:
            lines.append("  aviso: destino possui codigo; gas foi estimado como contrato")
        for token in self.tokens:
            detail = (
                f"  token={mask_address(token.token_address)} "
                f"saldo={token.display_balance} status={token.status}"
            )
            if token.error:
                detail += f" erro={token.error}"
            lines.append(detail)
        native = (
            f"  nativo={self.native.symbol} saldo_raw={self.native.balance_raw} "
            f"enviavel_raw={self.native.sendable_raw} status={self.native.status}"
        )
        if self.native.error:
            native += f" erro={self.native.error}"
        lines.append(native)
        lines.append(f"  ordem={','.join(self.execution_order) or 'nenhuma'}")
        lines.append("  assinatura=NAO broadcast=NAO")
        return tuple(lines)


def _quantity(value: Any, name: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise PreflightError(f"{name} retornou quantidade hexadecimal invalida.")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise PreflightError(f"{name} retornou quantidade hexadecimal invalida.") from exc


def _buffered_gas(estimated_gas: int) -> int:
    return (estimated_gas * (100 + GAS_LIMIT_BUFFER_PERCENT) + 99) // 100


def _reserved_fee(estimated_gas: int, gas_price: int) -> int:
    gas_limit = _buffered_gas(estimated_gas)
    return (gas_limit * gas_price * (100 + FEE_BUFFER_PERCENT) + 99) // 100


def _eth_call(rpc: RpcClient, call: dict[str, str], state_block_tag: str) -> str:
    result = rpc.call("eth_call", (call, state_block_tag))
    if not isinstance(result, str):
        raise PreflightError("eth_call retornou tipo invalido.")
    return result


def _read_token(
    rpc: RpcClient,
    *,
    token_address: str,
    source_wallet: str,
    safe_wallet: str,
    gas_price: int,
    state_block_tag: str,
) -> TokenPreflight:
    try:
        code = rpc.call("eth_getCode", (token_address, "latest"))
        if not isinstance(code, str) or code in {"0x", "0x0", "0x00"}:
            return TokenPreflight(
                token_address, None, None, None, 0, "failed", "sem bytecode"
            )

        balance = decode_uint256(
            _eth_call(
                rpc,
                {
                    "to": token_address,
                    "data": encode_balance_of(source_wallet),
                },
                state_block_tag,
            )
        )

        decimals: int | None = None
        try:
            candidate = decode_uint256(
                _eth_call(
                    rpc,
                    {"to": token_address, "data": encode_decimals()},
                    state_block_tag,
                )
            )
            if 0 <= candidate <= 255:
                decimals = candidate
        except (AbiError, JsonRpcError, PreflightError):
            decimals = None

        if balance == 0:
            return TokenPreflight(
                token_address, balance, decimals, 0, 0, "zero_balance"
            )

        transfer_data = encode_transfer(safe_wallet, balance)
        transfer_call = {
            "from": source_wallet,
            "to": token_address,
            "value": "0x0",
            "data": transfer_data,
        }
        if not transfer_result_succeeded(
            _eth_call(rpc, transfer_call, state_block_tag)
        ):
            return TokenPreflight(
                token_address,
                balance,
                decimals,
                None,
                0,
                "failed",
                "transfer retornou false",
            )
        estimated_gas = _quantity(
            rpc.call("eth_estimateGas", (transfer_call,)),
            "eth_estimateGas token",
        )
        return TokenPreflight(
            token_address=token_address,
            balance_raw=balance,
            decimals=decimals,
            estimated_gas=estimated_gas,
            reserved_fee_native_raw=_reserved_fee(estimated_gas, gas_price),
            status="ready",
        )
    except (AbiError, JsonRpcError, PreflightError) as exc:
        return TokenPreflight(
            token_address=token_address,
            balance_raw=None,
            decimals=None,
            estimated_gas=None,
            reserved_fee_native_raw=0,
            status="failed",
            error=str(exc),
        )


def run_chain_preflight(
    rpc: RpcClient,
    *,
    chain: Chain,
    source_wallet: str,
    safe_wallet: str,
    token_addresses: tuple[str, ...],
) -> ChainPreflight:
    actual_chain_id = _quantity(rpc.call("eth_chainId"), "eth_chainId")
    if actual_chain_id != chain.chain_id:
        raise PreflightError(
            f"RPC da rede errada: esperado {chain.chain_id}, recebido {actual_chain_id}."
        )

    block_number = _quantity(rpc.call("eth_blockNumber"), "eth_blockNumber")
    balance = _quantity(
        rpc.call("eth_getBalance", (source_wallet, chain.state_block_tag)),
        "eth_getBalance",
    )
    state_nonce = _quantity(
        rpc.call(
            "eth_getTransactionCount", (source_wallet, chain.state_block_tag)
        ),
        "eth_getTransactionCount",
    )
    gas_price = _quantity(rpc.call("eth_gasPrice"), "eth_gasPrice")
    source_code = rpc.call("eth_getCode", (source_wallet, "latest"))
    destination_code = rpc.call("eth_getCode", (safe_wallet, "latest"))
    source_has_code = isinstance(source_code, str) and source_code not in {
        "0x",
        "0x0",
        "0x00",
    }
    source_is_eip7702 = is_eip7702_delegation_code(source_code)
    destination_has_code = isinstance(destination_code, str) and destination_code not in {
        "0x",
        "0x0",
        "0x00",
    }

    tokens = tuple(
        _read_token(
            rpc,
            token_address=token,
            source_wallet=source_wallet,
            safe_wallet=safe_wallet,
            gas_price=gas_price,
            state_block_tag=chain.state_block_tag,
        )
        for token in token_addresses
    )

    token_fee_reserve = sum(token.reserved_fee_native_raw for token in tokens)
    native_estimated_gas: int | None = None
    native_error: str | None = None
    native_fee_reserve = 0
    native_status = "zero_balance" if balance == 0 else "ready"
    if balance:
        try:
            native_call = {
                "from": source_wallet,
                "to": safe_wallet,
                "value": "0x1",
                "data": "0x",
            }
            native_estimated_gas = _quantity(
                rpc.call("eth_estimateGas", (native_call,)),
                "eth_estimateGas nativo",
            )
            native_fee_reserve = _reserved_fee(native_estimated_gas, gas_price)
        except (JsonRpcError, PreflightError) as exc:
            native_status = "failed"
            native_error = str(exc)

    total_fee_reserve = token_fee_reserve + native_fee_reserve
    sendable = max(0, balance - total_fee_reserve)
    if balance and sendable == 0 and native_status == "ready":
        native_status = "insufficient_gas_reserve"
        native_error = "saldo nativo nao cobre a reserva de todas as transferencias"

    native = NativePreflight(
        symbol=chain.native_symbol,
        balance_raw=balance,
        estimated_gas=native_estimated_gas,
        total_reserved_fee_raw=total_fee_reserve,
        sendable_raw=sendable,
        status=native_status,
        error=native_error,
    )
    execution_order = tuple(
        [
            *(f"token:{mask_address(token.token_address)}" for token in tokens if token.status == "ready"),
            *([f"native:{chain.native_symbol}"] if native.status == "ready" else []),
        ]
    )
    passed = (
        (not source_has_code or source_is_eip7702)
        and all(token.status != "failed" for token in tokens)
        and native.status not in {"failed", "insufficient_gas_reserve"}
    )
    return ChainPreflight(
        chain=chain,
        source_wallet=source_wallet,
        safe_wallet=safe_wallet,
        block_number=block_number,
        state_nonce=state_nonce,
        gas_price_raw=gas_price,
        source_has_code=source_has_code,
        source_is_eip7702=source_is_eip7702,
        destination_has_code=destination_has_code,
        tokens=tokens,
        native=native,
        execution_order=execution_order,
        passed=passed,
    )
