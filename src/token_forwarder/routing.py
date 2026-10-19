from __future__ import annotations


def should_accept_message(
    *,
    chat_id: int | None,
    is_private: bool,
    destination_chat_id: int,
    allowed_source_ids: frozenset[int],
    allow_any_private_source: bool,
) -> bool:
    """Apply source allowlisting and prevent the destination bot from creating a loop."""
    if chat_id is None or chat_id == destination_chat_id:
        return False
    if allowed_source_ids:
        return chat_id in allowed_source_ids
    return allow_any_private_source and is_private

