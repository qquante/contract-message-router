from token_forwarder.routing import should_accept_message


def test_destination_is_always_rejected_to_prevent_loop() -> None:
    assert not should_accept_message(
        chat_id=99,
        is_private=True,
        destination_chat_id=99,
        allowed_source_ids=frozenset(),
        allow_any_private_source=True,
    )


def test_accepts_any_private_source_when_enabled() -> None:
    assert should_accept_message(
        chat_id=10,
        is_private=True,
        destination_chat_id=99,
        allowed_source_ids=frozenset(),
        allow_any_private_source=True,
    )
    assert not should_accept_message(
        chat_id=-10010,
        is_private=False,
        destination_chat_id=99,
        allowed_source_ids=frozenset(),
        allow_any_private_source=True,
    )


def test_allowlist_has_priority() -> None:
    assert should_accept_message(
        chat_id=-10010,
        is_private=False,
        destination_chat_id=99,
        allowed_source_ids=frozenset({-10010}),
        allow_any_private_source=False,
    )
    assert not should_accept_message(
        chat_id=20,
        is_private=True,
        destination_chat_id=99,
        allowed_source_ids=frozenset({-10010}),
        allow_any_private_source=True,
    )

