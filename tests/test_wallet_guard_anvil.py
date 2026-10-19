from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from eth_account import Account

from wallet_guard.broadcast import broadcast_signed_transaction
from wallet_guard.chains import Chain
from wallet_guard.native import build_native_plan
from wallet_guard.rpc import HttpBroadcastRpcClient, HttpJsonRpcClient, JsonRpcError
from wallet_guard.signer import sign_native_plan_from_keystore


ANVIL_FIRST_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff94"
    "4bacb478cbed5efcae784d7bf4f2ff80"
)


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.mark.skipif(shutil.which("anvil") is None, reason="anvil nao instalado")
def test_local_end_to_end_native_transfer(tmp_path: Path) -> None:
    port = _unused_local_port()
    rpc_url = f"http://127.0.0.1:{port}"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            str(shutil.which("anvil")),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--chain-id",
            "31337",
            "--accounts",
            "2",
            "--silent",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    try:
        chain = Chain(
            key="anvil-local",
            name="Anvil Local",
            chain_id=31_337,
            native_symbol="TEST",
            explorer_url="",
        )
        source = Account.from_key(ANVIL_FIRST_PRIVATE_KEY)
        safe = Account.create("wallet-guard-anvil-safe")

        ready = False
        for _ in range(50):
            try:
                with HttpJsonRpcClient(
                    rpc_url=rpc_url,
                    proxy_url=None,
                    timeout_seconds=1,
                ) as rpc:
                    ready = rpc.call("eth_chainId") == hex(chain.chain_id)
                if ready:
                    break
            except JsonRpcError:
                time.sleep(0.1)
        assert ready, "Anvil local nao iniciou"

        with HttpJsonRpcClient(
            rpc_url=rpc_url,
            proxy_url=None,
            timeout_seconds=2,
        ) as rpc:
            plan = build_native_plan(
                rpc,
                chain=chain,
                source_wallet=source.address,
                safe_wallet=safe.address,
            )

        keystore_path = tmp_path / "anvil-keystore.json"
        password = "somente-teste-local"
        keystore_path.write_text(
            json.dumps(
                Account.encrypt(
                    source.key,
                    password,
                    kdf="pbkdf2",
                    iterations=1_000,
                )
            ),
            encoding="utf-8",
        )
        signed = sign_native_plan_from_keystore(
            plan,
            keystore_path=keystore_path,
            password=password,
        )

        with HttpBroadcastRpcClient(
            rpc_url=rpc_url,
            proxy_url=None,
            timeout_seconds=2,
        ) as rpc:
            result = broadcast_signed_transaction(
                rpc,
                signed,
                sleep=lambda _: None,
            )

        with HttpJsonRpcClient(
            rpc_url=rpc_url,
            proxy_url=None,
            timeout_seconds=2,
        ) as rpc:
            safe_balance = int(
                rpc.call("eth_getBalance", (safe.address, "latest")), 16
            )

        assert result.transaction_hash == signed.transaction_hash
        assert result.attempts == 1
        assert safe_balance == plan.send_value
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
