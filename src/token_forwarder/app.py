from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient, events, utils
from telethon.errors import RPCError

from token_forwarder.config import Settings
from token_forwarder.extractor import extract_contracts
from token_forwarder.history import ForwardHistory
from token_forwarder.notifier import BeepNotifier
from token_forwarder.routing import should_accept_message

LOGGER = logging.getLogger("token_forwarder")


async def _resolve_peer_id(client: TelegramClient, chat: str) -> int:
    entity = await client.get_entity(chat)
    return utils.get_peer_id(entity)


async def run_forwarder(settings: Settings) -> None:
    settings.session_path.parent.mkdir(parents=True, exist_ok=True)
    history = ForwardHistory(settings.state_db)
    forward_lock = asyncio.Lock()
    notifier = BeepNotifier(
        enabled=settings.beep_enabled,
        frequency_hz=settings.beep_frequency_hz,
        duration_ms=settings.beep_duration_ms,
        repeat=settings.beep_repeat,
        gap_ms=settings.beep_gap_ms,
    )

    client = TelegramClient(
        str(settings.session_path),
        settings.api_id,
        settings.api_hash,
        flood_sleep_threshold=60,
    )

    try:
        await client.start(phone=settings.phone)
        account = await client.get_me()
        actual_username = (account.username or "").lower()
        if (
            settings.expected_account_username
            and actual_username != settings.expected_account_username
        ):
            raise RuntimeError(
                "Conta incorreta: esperado "
                f"@{settings.expected_account_username}, conectado como "
                f"@{actual_username or '<sem_username>'}."
            )

        destination_entity = await client.get_input_entity(settings.destination_chat)
        destination_chat_id = await _resolve_peer_id(client, settings.destination_chat)
        allowed_source_ids = frozenset(
            [await _resolve_peer_id(client, source) for source in settings.source_chats]
        )

        LOGGER.info("Configuracao validada: %s", settings.safe_summary())
        notifier.start()
        if settings.dry_run:
            LOGGER.warning("DRY_RUN ativo: nenhum contrato sera enviado.")

        @client.on(events.NewMessage(incoming=True))
        async def on_new_message(event: events.NewMessage.Event) -> None:
            if not should_accept_message(
                chat_id=event.chat_id,
                is_private=event.is_private,
                destination_chat_id=destination_chat_id,
                allowed_source_ids=allowed_source_ids,
                allow_any_private_source=settings.allow_any_private_source,
            ):
                return

            contracts = extract_contracts(event.raw_text or "", settings.contract_network)
            if not contracts:
                LOGGER.debug("Mensagem %s sem contrato valido; ignorada.", event.id)
                return
            if len(contracts) > 1:
                LOGGER.warning(
                    "Mensagem %s contem %d contratos distintos; ignorada por ambiguidade.",
                    event.id,
                    len(contracts),
                )
                return

            contract = contracts[0]
            source_chat_id = event.chat_id
            if source_chat_id is None:
                return

            async with forward_lock:
                if history.was_sent(source_chat_id, event.id, contract):
                    LOGGER.info("Mensagem %s ja processada; ignorada.", event.id)
                    return

                if settings.dry_run:
                    LOGGER.info("DRY_RUN contrato detectado: %s", contract)
                    return

                try:
                    await client.send_message(
                        destination_entity,
                        contract,
                        link_preview=False,
                    )
                except RPCError:
                    LOGGER.exception("Telegram recusou o envio do contrato %s.", contract)
                    return

                history.record_sent(
                    source_chat_id,
                    event.id,
                    contract,
                    settings.destination_chat,
                )
                notifier.notify()
                LOGGER.info("Contrato enviado: %s", contract)

        LOGGER.info("Listener ativo. Pressione Ctrl+C para encerrar.")
        await client.run_until_disconnected()
    finally:
        notifier.close()
        history.close()
        if client.is_connected():
            await client.disconnect()
