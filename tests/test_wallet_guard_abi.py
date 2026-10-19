import pytest

from wallet_guard.abi import (
    AbiError,
    decode_uint256,
    encode_balance_of,
    encode_transfer,
    format_units,
    normalize_address,
    transfer_result_succeeded,
)

SOURCE = "0x1111111111111111111111111111111111111111"
DESTINATION = "0x2222222222222222222222222222222222222222"


def test_encodes_standard_erc20_calls_without_web3_dependency() -> None:
    assert encode_balance_of(SOURCE) == "0x70a08231" + "0" * 24 + "1" * 40
    transfer = encode_transfer(DESTINATION, 150_000_000)
    assert transfer.startswith("0xa9059cbb" + "0" * 24 + "2" * 40)
    assert transfer.endswith(f"{150_000_000:064x}")


def test_decodes_standard_and_nonstandard_transfer_results() -> None:
    assert transfer_result_succeeded("0x")
    assert transfer_result_succeeded("0x" + "0" * 63 + "1")
    assert not transfer_result_succeeded("0x" + "0" * 64)
    assert decode_uint256("0x2a") == 42


def test_formats_raw_units_without_float() -> None:
    assert format_units(150_000_000, 6) == "150"
    assert format_units(1, 18) == "0.000000000000000001"
    assert format_units(123, None) == "123"


def test_rejects_invalid_address_and_amount() -> None:
    with pytest.raises(AbiError):
        normalize_address("0x1234")
    with pytest.raises(AbiError):
        encode_transfer(DESTINATION, -1)
