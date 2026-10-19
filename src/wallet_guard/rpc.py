from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol

import httpx


READ_ONLY_METHODS = frozenset(
    {
        "eth_blockNumber",
        "eth_call",
        "eth_chainId",
        "eth_estimateGas",
        "eth_feeHistory",
        "eth_gasPrice",
        "eth_getBalance",
        "eth_getBlockByNumber",
        "eth_getCode",
        "eth_getTransactionCount",
        "eth_getTransactionReceipt",
        "eth_maxPriorityFeePerGas",
    }
)
BROADCAST_METHODS = frozenset(
    {
        "eth_getTransactionReceipt",
        "eth_sendRawTransaction",
    }
)
_ADDRESS_IN_TEXT = re.compile(r"0x[0-9a-fA-F]{40}")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")


def _sanitize_error(message: str) -> str:
    message = _URL_CREDENTIALS.sub(r"\g<scheme><credenciais>@", message)
    message = _ADDRESS_IN_TEXT.sub(
        lambda match: f"{match.group(0)[:6]}...{match.group(0)[-4:]}", message
    )
    return message[:500]


class UnsafeRpcMethodError(RuntimeError):
    """Raised before any RPC method capable of changing state is sent."""


class JsonRpcError(RuntimeError):
    def __init__(self, code: int | None, message: str) -> None:
        safe_message = _sanitize_error(message)
        super().__init__(
            f"RPC {code}: {safe_message}" if code is not None else safe_message
        )
        self.code = code
        self.message = safe_message


class RpcClient(Protocol):
    def call(self, method: str, params: Sequence[Any] = ()) -> Any: ...


class HttpJsonRpcClient:
    """Fail-closed JSON-RPC client that only exposes read-only EVM methods."""

    def __init__(
        self,
        *,
        rpc_url: str,
        proxy_url: str | None,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._rpc_url = rpc_url
        self._request_id = 0
        self._owns_client = client is None
        self._client = client or httpx.Client(
            proxy=proxy_url,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    def call(self, method: str, params: Sequence[Any] = ()) -> Any:
        if method not in READ_ONLY_METHODS:
            raise UnsafeRpcMethodError(
                f"Metodo RPC bloqueado pelo modo read-only: {method}."
            )
        return self._call_allowed(method, params)

    def _call_allowed(self, method: str, params: Sequence[Any]) -> Any:
        self._request_id += 1
        try:
            response = self._client.post(
                self._rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": list(params),
                },
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JsonRpcError(None, f"RPC respondeu HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise JsonRpcError(
                None, f"Falha de transporte RPC: {type(exc).__name__}."
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise JsonRpcError(None, "RPC retornou JSON invalido.") from exc
        if not isinstance(payload, dict):
            raise JsonRpcError(None, "RPC retornou estrutura invalida.")
        if "error" in payload:
            error = payload.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message", "Erro RPC sem mensagem")
                raise JsonRpcError(code if isinstance(code, int) else None, str(message))
            raise JsonRpcError(None, "RPC retornou erro sem estrutura valida.")
        if "result" not in payload:
            raise JsonRpcError(None, "RPC nao retornou result.")
        return payload["result"]

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpJsonRpcClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class HttpBroadcastRpcClient(HttpJsonRpcClient):
    """Narrow client for an already-signed raw tx and its receipt only."""

    def call(self, method: str, params: Sequence[Any] = ()) -> Any:
        if method not in BROADCAST_METHODS:
            raise UnsafeRpcMethodError(
                f"Metodo RPC bloqueado pelo modo broadcast restrito: {method}."
            )
        return self._call_allowed(method, params)
