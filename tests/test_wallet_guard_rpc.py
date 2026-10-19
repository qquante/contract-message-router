import httpx
import pytest

from wallet_guard.rpc import (
    HttpBroadcastRpcClient,
    HttpJsonRpcClient,
    JsonRpcError,
    UnsafeRpcMethodError,
)


def test_read_only_rpc_allows_reads_and_blocks_broadcast_before_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        calls.append(payload["method"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    rpc = HttpJsonRpcClient(
        rpc_url="https://rpc.example",
        proxy_url=None,
        timeout_seconds=5,
        client=http_client,
    )
    try:
        assert rpc.call("eth_chainId") == "0x1"
        with pytest.raises(UnsafeRpcMethodError, match="bloqueado"):
            rpc.call("eth_sendRawTransaction", ("0xdeadbeef",))
        with pytest.raises(UnsafeRpcMethodError, match="bloqueado"):
            rpc.call("eth_sendTransaction", ({},))
    finally:
        http_client.close()

    assert calls == ["eth_chainId"]


def test_rpc_errors_mask_addresses_and_proxy_credentials() -> None:
    address = "0x1111111111111111111111111111111111111111"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": -32000,
                    "message": (
                        f"wallet {address} via "
                        "socks5://private-user:private-password@proxy.example"
                    ),
                },
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    rpc = HttpJsonRpcClient(
        rpc_url="https://rpc.example",
        proxy_url=None,
        timeout_seconds=5,
        client=http_client,
    )
    try:
        with pytest.raises(JsonRpcError) as captured:
            rpc.call("eth_chainId")
    finally:
        http_client.close()

    message = str(captured.value)
    assert address not in message
    assert "private-password" not in message
    assert "0x1111...1111" in message


def test_broadcast_rpc_allows_only_raw_send_and_receipt() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        calls.append(payload["method"])
        result = "0x" + "12" * 32 if payload["method"] == "eth_sendRawTransaction" else None
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    rpc = HttpBroadcastRpcClient(
        rpc_url="https://rpc.example",
        proxy_url=None,
        timeout_seconds=5,
        client=http_client,
    )
    try:
        assert rpc.call("eth_sendRawTransaction", ("0xdeadbeef",)).startswith("0x")
        assert rpc.call("eth_getTransactionReceipt", ("0x" + "12" * 32,)) is None
        with pytest.raises(UnsafeRpcMethodError, match="broadcast restrito"):
            rpc.call("eth_getBalance", ("0x0", "latest"))
        with pytest.raises(UnsafeRpcMethodError, match="broadcast restrito"):
            rpc.call("eth_sendTransaction", ({},))
    finally:
        http_client.close()

    assert calls == ["eth_sendRawTransaction", "eth_getTransactionReceipt"]
