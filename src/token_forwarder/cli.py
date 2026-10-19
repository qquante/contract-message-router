from __future__ import annotations

import argparse
import asyncio
import logging

from token_forwarder.app import run_forwarder
from token_forwarder.config import ConfigurationError, load_settings
from token_forwarder.extractor import extract_contracts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Encaminha somente contratos recebidos no Telegram."
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="valida o .env sem exibir segredos nem conectar ao Telegram",
    )
    parser.add_argument(
        "--extract",
        metavar="TEXTO",
        help="testa localmente a extracao de contratos, sem conectar ao Telegram",
    )
    parser.add_argument(
        "--network",
        choices=("auto", "solana", "evm"),
        default="auto",
        help="rede usada somente com --extract",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.extract is not None:
        contracts = extract_contracts(args.extract, args.network)
        if len(contracts) == 1:
            print(contracts[0])
            return
        if not contracts:
            raise SystemExit("Nenhum contrato valido encontrado.")
        raise SystemExit(f"Mensagem ambigua: {len(contracts)} contratos encontrados.")

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuracao invalida: {exc}") from exc

    if args.check_config:
        print(f"Configuracao valida: {settings.safe_summary()}")
        return

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        asyncio.run(run_forwarder(settings))
    except KeyboardInterrupt:
        logging.getLogger("token_forwarder").info("Encerrado pelo usuario.")

